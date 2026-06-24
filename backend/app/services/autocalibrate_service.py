"""Auto-calibrate a broadcast's scoreboard from the NBA API score sequence (Track B).

Given a game video + NBA game ID, sample frames, run full-frame OCR, and derive the scorebug
regions with NO hardcoded coordinates:
  - score boxes = the two fixed-location regions whose integer readings climb across the game and
    top out at the two final scores; home/away is fixed by matching the joint (left, right)
    readings to the API's (home, away) pairs.
  - clock = the fixed-location region reading MM:SS.

Returns a profile dict (same shape as scorebug_regions entries) so the detector can use it.
Validated on the demo ESPN game (reproduces the hardcoded `espn` profile).
"""

import logging
import os
import re
import subprocess
import tempfile
from collections import defaultdict

import cv2

from app.services.nba_service import NBAService
from app.services.score_change_detector import _get_reader
from app.utils.ffmpeg import _resolve_tool, get_video_duration

logger = logging.getLogger(__name__)

CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
GRID = 40
DEFAULT_FRAMES = 28
PAD = 5  # px padding added around tight OCR boxes so the detector crop has margin


def _api_score_info(game_id: str):
    """Return (home_final, away_final, set_of_(home,away)_pairs) from the play-by-play."""
    pairs = set()
    home = away = 0
    for e in NBAService().fetch_play_by_play(game_id):
        sa = (e.get("score_after") or "").split()
        if len(sa) >= 4:
            try:
                h, a = int(sa[1]), int(sa[3])
            except ValueError:
                continue
            home, away = h, a
            pairs.add((h, a))
    return home, away, pairs


def _pad(box, w_max, h_max):
    x, y, w, h = box
    x2, y2 = min(w_max, x + w + PAD), min(h_max, y + h + PAD)
    x, y = max(0, x - PAD), max(0, y - PAD)
    return (x, y, x2 - x, y2 - y)


def auto_calibrate(video_path: str, game_id: str, n_frames: int = DEFAULT_FRAMES) -> dict | None:
    """Discover a scorebug profile for this broadcast. Returns the profile dict, or None."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    duration = get_video_duration(video_path)
    times = [duration * (0.04 + 0.89 * i / (n_frames - 1)) for i in range(n_frames)]
    home_final, away_final, api_pairs = _api_score_info(game_id)
    logger.info("Auto-calibrating %s (final %d-%d) over %d frames", game_id, home_final, away_final, n_frames)

    reader = _get_reader()
    ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"
    num_cells = defaultdict(list)
    clock_cells = defaultdict(list)
    frame_w = frame_h = 0

    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            p = os.path.join(tmp, f"f{i}.jpg")
            subprocess.run([ffmpeg, "-ss", f"{t:.2f}", "-i", video_path, "-vframes", "1",
                            "-q:v", "2", "-y", p], capture_output=True)
            img = cv2.imread(p)
            if img is None:
                continue
            frame_h, frame_w = img.shape[:2]
            for box, text, _ in reader.readtext(img, allowlist="0123456789:"):
                xs = [pt[0] for pt in box]; ys = [pt[1] for pt in box]
                x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
                cell = (int((x + w / 2) // GRID), int((y + h / 2) // GRID))
                rec = {"i": i, "x": x, "y": y, "w": w, "h": h}
                m = CLOCK_RE.match(text.strip())
                if m and int(m.group(1)) <= 12 and int(m.group(2)) <= 59:
                    clock_cells[cell].append(rec)
                else:
                    digits = "".join(c for c in text if c.isdigit())
                    if digits and int(digits) <= 199:
                        num_cells[cell].append({**rec, "val": int(digits)})

    def bbox_of(obs):
        x = int(min(o["x"] for o in obs)); y = int(min(o["y"] for o in obs))
        w = int(max(o["x"] + o["w"] for o in obs)) - x
        h = int(max(o["y"] + o["h"] for o in obs)) - y
        return (x, y, w, h)

    # candidate numeric regions: persistent + cleanly increasing (a team's score climbs all
    # game and never decreases). Don't require max == the final score — frame sampling can miss
    # the last baskets — just a plausibly high value that never exceeds the final.
    hi = max(home_final, away_final)
    cands = []
    for obs in num_cells.values():
        if len(obs) < n_frames * 0.35:
            continue
        obs.sort(key=lambda o: o["i"])
        vals = [o["val"] for o in obs]
        nondec = sum(vals[k] <= vals[k + 1] for k in range(len(vals) - 1)) / max(1, len(vals) - 1)
        mx = max(vals)
        if nondec >= 0.85 and 0.4 * hi <= mx <= hi + 5:
            cands.append({"obs": obs, "max": mx, "bbox": bbox_of(obs)})
    cands.sort(key=lambda c: c["max"], reverse=True)

    boxes = []
    for c in cands:
        if all(abs(c["bbox"][0] - b["bbox"][0]) > GRID for b in boxes):
            boxes.append(c)
        if len(boxes) == 2:
            break
    if len(boxes) < 2:
        logger.warning("Auto-calibrate found %d score boxes (need 2)", len(boxes))
        return None

    boxes.sort(key=lambda c: c["bbox"][0])  # left, right
    left = {o["i"]: o["val"] for o in boxes[0]["obs"]}
    right = {o["i"]: o["val"] for o in boxes[1]["obs"]}
    common = set(left) & set(right)
    lr = sum(1 for i in common if (left[i], right[i]) in api_pairs)   # left=home, right=away
    rl = sum(1 for i in common if (right[i], left[i]) in api_pairs)   # left=away, right=home
    home_b, away_b = (boxes[0], boxes[1]) if lr >= rl else (boxes[1], boxes[0])

    profile = {
        "home_score_region": _pad(home_b["bbox"], frame_w, frame_h),
        "away_score_region": _pad(away_b["bbox"], frame_w, frame_h),
    }
    if clock_cells:
        clock_obs = max(clock_cells.values(), key=len)
        profile["clock_region"] = _pad(bbox_of(clock_obs), frame_w, frame_h)
    logger.info("Calibrated profile: %s (home/away match %d vs %d)", profile, lr, rl)
    return profile
