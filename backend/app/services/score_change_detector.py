"""Score Change Detector — finds the exact video frame where the scorebug score updates.

This is the deterministic codification of what the Phase 5A Claude agent did per play: read
the score box and find the frame where it changes from score_before to score_after.

Two signals are combined:
  1. White-pixel mask diff (cheap) locates candidate change frames — frames where the digit
     shapes in the scoring side's box differ from the previous frame. ESPN score digits are
     white, so masking BGR > threshold isolates them.
  2. Targeted OCR (only at candidates) reads the actual integer score just before and just
     after the change, and requires it to transition expected_before -> expected_after. This
     is the score *signature* the agent relied on: it rejects free throws and other baskets
     (which flip the same region but to a different number) and rejects animation blips
     (where the value doesn't actually change).

The primary entry point is `find_score_transition`, which scans FORWARD from the last
confirmed position — the anchor chain processes plays in game order, so the first
before->after signature match ahead is this play's basket, regardless of intervening dead
ball or quarter breaks.
"""

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass

import cv2
import numpy as np

from app.utils.constants import (
    SCORE_VERIFY_FPS,
    SCORE_WHITE_THRESHOLD,
    SCORE_CHANGE_PX,
)
from app.utils.ffmpeg import _resolve_tool
from app.utils.scorebug_regions import get_profile

logger = logging.getLogger(__name__)

# Forward-scan chunks (seconds after the search origin). Most plays resolve in the near
# chunk; the far chunks cover timeouts, quarter/halftime breaks, and long stoppages (e.g.
# the ~4-min injury freeze late in this game). Slight overlap so a transition on a boundary
# isn't split.
_SCAN_CHUNKS = [(2.0, 160.0), (150.0, 320.0), (300.0, 520.0), (500.0, 720.0)]

# EasyOCR reader is expensive to construct — build once, lazily.
_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        logger.info("Initializing EasyOCR reader for score confirmation...")
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader


@dataclass
class VerificationResult:
    verified: bool
    video_second: float
    confidence: str  # "high" when the before->after signature matched, "low" otherwise
    method: str      # "score_change" or "fallback"


def _detect_scoring_side(score_before: str, score_after: str) -> str:
    """Which side of the scorebug changed: 'home' (LAL) or 'away' (GSW).

    Score strings are 'LAL {home} GSW {away}' (see NBAService._build_score_context).
    Home (LAL) is the second token; away (GSW) is the fourth.
    """
    b = score_before.split()
    a = score_after.split()
    if len(b) >= 4 and len(a) >= 4 and b[1] != a[1]:
        return "home"
    return "away"


def _expected_value(score_str: str, side: str) -> int | None:
    """The scoring side's numeric score in a 'LAL h GSW a' string."""
    parts = score_str.split()
    idx = 1 if side == "home" else 3
    if len(parts) > idx:
        try:
            return int(parts[idx])
        except ValueError:
            return None
    return None


def _white_mask(img, region: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = region
    crop = img[y:y + h, x:x + w]
    lower = np.array([SCORE_WHITE_THRESHOLD, SCORE_WHITE_THRESHOLD, SCORE_WHITE_THRESHOLD])
    upper = np.array([255, 255, 255])
    return cv2.inRange(crop, lower, upper)


def _read_score(img, region: tuple[int, int, int, int]) -> int | None:
    """OCR the integer score in a region. Returns None if unreadable.

    Picks the most-confident plausible (0-199) numeric token rather than concatenating every
    digit blob. Late-game scorebugs add bonus/timeout/foul digits next to the score, and gluing
    them on produced garbage like "137" + "86" -> "13786", which then fails the signature match.
    """
    x, y, w, h = region
    crop = img[y:y + h, x:x + w]
    big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    try:
        out = _get_reader().readtext(big, detail=1, allowlist="0123456789")
    except Exception:
        return None
    best_val, best_conf = None, 0.0
    for _box, text, conf in out:
        d = "".join(ch for ch in text if ch.isdigit())
        if d and int(d) <= 199 and conf > best_conf:
            best_val, best_conf = int(d), conf
    return best_val if best_conf >= 0.3 else None


def _extract_window_frames(video_path, out_dir, start, duration):
    """Extract frames at SCORE_VERIFY_FPS over [start, start+duration] in one ffmpeg call."""
    ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"
    pattern = os.path.join(out_dir, "f_%05d.jpg")
    subprocess.run(
        [ffmpeg, "-ss", f"{start:.2f}", "-t", f"{duration:.2f}", "-i", video_path,
         "-vf", f"fps={SCORE_VERIFY_FPS}", "-q:v", "2", "-y", pattern],
        capture_output=True, timeout=300,
    )
    frames = []
    i = 1
    while True:
        p = os.path.join(out_dir, f"f_{i:05d}.jpg")
        if not os.path.exists(p):
            break
        img = cv2.imread(p)
        if img is not None:
            frames.append((start + (i - 1) / SCORE_VERIFY_FPS, img))
        i += 1
    return frames


def _scan_transition(frames, regions, side, before_val, after_val) -> float | None:
    """First frame where the scoring side's score changes before_val -> after_val.

    Mask diff (frame-to-frame) finds candidate change frames cheaply; OCR confirms the value
    transition at each candidate. The score box must not be matched by the other side moving
    on the same frame (bar-wide animation).
    """
    n = len(frames)
    if n < 3:
        return None
    other = "home" if side == "away" else "away"
    masks = [_white_mask(img, regions[side]) for _, img in frames]
    omasks = [_white_mask(img, regions[other]) for _, img in frames]

    for i in range(1, n):
        if int(np.sum(cv2.bitwise_xor(masks[i], masks[i - 1]) > 0)) <= SCORE_CHANGE_PX:
            continue
        # single-side: the other region must not change on the same frame
        if int(np.sum(cv2.bitwise_xor(omasks[i], omasks[i - 1]) > 0)) > SCORE_CHANGE_PX:
            continue
        # OCR a stable frame ~1s before and ~1s after the change to confirm the signature
        before = _read_score(frames[max(0, i - 2)][1], regions[side])
        after = _read_score(frames[min(n - 1, i + 2)][1], regions[side])
        if before == before_val and after == after_val:
            return frames[i][0]
    return None


def find_score_transition(
    video_path: str,
    search_from: float,
    score_before: str,
    score_after: str,
    profile_name: str | None = None,
) -> VerificationResult:
    """Scan forward from `search_from` for the score box's before->after signature.

    Used by the anchor chain: plays are processed in game order, so the first matching
    transition ahead of the last confirmed position is this play's basket. Scans in widening
    chunks so most plays resolve quickly while timeouts/breaks are still covered.
    """
    profile = get_profile(profile_name)
    away, home = profile.get("away_score_region"), profile.get("home_score_region")
    if away is None or home is None:
        return VerificationResult(False, search_from, "low", "fallback")
    regions = {"away": away, "home": home}
    side = _detect_scoring_side(score_before, score_after)
    before_val = _expected_value(score_before, side)
    after_val = _expected_value(score_after, side)

    for lo, hi in _SCAN_CHUNKS:
        start = max(0.0, search_from + lo)
        with tempfile.TemporaryDirectory() as tmpdir:
            frames = _extract_window_frames(video_path, tmpdir, start, hi - lo)
            t = _scan_transition(frames, regions, side, before_val, after_val)
        if t is not None:
            logger.info("Score transition (%s %s->%s) at t=%.1fs", side, before_val, after_val, t)
            return VerificationResult(True, t, "high", "score_change")

    logger.warning("No %s transition %s->%s after %.0fs", side, before_val, after_val, search_from)
    return VerificationResult(False, search_from, "low", "fallback")


def verify_score_change(
    video_path: str,
    rough_timestamp: float,
    score_before: str,
    score_after: str,
    profile_name: str | None = None,
    base_window: float = 30.0,
) -> VerificationResult:
    """Centered variant: confirm a known-approximate timestamp by the score signature.

    Searches ±base_window around rough_timestamp. Used for spot-checks / regression scripts
    where the timestamp is already roughly known; the anchor chain uses find_score_transition.
    """
    profile = get_profile(profile_name)
    away, home = profile.get("away_score_region"), profile.get("home_score_region")
    if away is None or home is None:
        return VerificationResult(False, rough_timestamp, "low", "fallback")
    regions = {"away": away, "home": home}
    side = _detect_scoring_side(score_before, score_after)
    before_val = _expected_value(score_before, side)
    after_val = _expected_value(score_after, side)

    for window in (base_window, base_window * 2):
        start = max(0.0, rough_timestamp - window)
        with tempfile.TemporaryDirectory() as tmpdir:
            frames = _extract_window_frames(video_path, tmpdir, start, 2 * window)
            t = _scan_transition(frames, regions, side, before_val, after_val)
        if t is not None:
            return VerificationResult(True, t, "high", "score_change")
    return VerificationResult(False, rough_timestamp, "low", "fallback")
