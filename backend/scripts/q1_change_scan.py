"""Q1 ordinal score-change scan experiment.

One ffmpeg pass extracts 1fps frames for Q1 (0-1300s). For each frame we
compute white-pixel masks of both score regions plus a scorebug-present gate
(white pixels in the clock region). A score change = the mask differs from the
previous frame and stays changed, while the scorebug is visible in both frames.

The detected (time, side) sequence is compared against the expected Q1 scoring
sequence from the play-by-play JSON (made shots + made free throws), and the 7
LAL watch-confirmed ground truths.

Usage:
    uv run python scripts/q1_change_scan.py
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np

from app.utils.ffmpeg import _resolve_tool
from app.utils.scorebug_regions import get_profile

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VIDEO_PATH = os.path.join(BACKEND, "data", "uploads", "0052000121", "full_game.mp4")
PBP_PATH = os.path.join(BACKEND, "data", "mock", "real_play_by_play.json")

Q1_END = 1300
WHITE = 170
CHANGE_PX = 80          # mask diff pixels to call it a change
SCOREBUG_MIN_WHITE = 40  # clock region white px for "scorebug present"

GROUND_TRUTH = [  # (video_sec, clock, player) — watch-confirmed LAL plays
    (82, "11:10", "Drummond"), (258, "8:29", "James"), (442, "6:40", "KCP"),
    (687, "4:43", "KCP"), (752, "4:13", "Caruso"), (947, "2:49", "Caruso"),
    (1176, "0:55", "Davis"),
]


def white_mask(img, region):
    x, y, w, h = region
    crop = img[y:y + h, x:x + w]
    return cv2.inRange(crop, (WHITE, WHITE, WHITE), (255, 255, 255))


def expected_sequence():
    """Ordered list of expected Q1 score changes from play-by-play."""
    with open(PBP_PATH, encoding="utf-8") as f:
        events = json.load(f)
    seq = []
    prev = ("0", "0")
    for e in events:
        h, a = e.get("scoreHome", ""), e.get("scoreAway", "")
        if not h or not a:
            continue
        if (h, a) != prev:
            side = "home" if h != prev[0] else "away"
            seq.append({
                "clock": e["clock"], "side": side, "score": f"{h}-{a}",
                "type": e.get("actionType"), "player": e.get("playerName"),
            })
            prev = (h, a)
    return seq


def main():
    profile = get_profile("espn")
    regions = {"away": profile["away_score_region"], "home": profile["home_score_region"]}
    clock_region = profile["clock_region"]

    expected = expected_sequence()
    print(f"Expected Q1 score changes from play-by-play: {len(expected)}")
    for e in expected:
        print(f"  {e['clock']:>14} {e['side']:<5} {e['score']:>7}  {e['type']:<10} {e['player']}")

    ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"
    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = os.path.join(tmpdir, "f_%05d.jpg")
        print("\nExtracting 1fps frames (single ffmpeg pass)...")
        subprocess.run(
            [ffmpeg, "-t", str(Q1_END), "-i", VIDEO_PATH,
             "-vf", "fps=1", "-q:v", "2", "-y", pattern],
            capture_output=True, timeout=900, check=True,
        )
        n_frames = len(os.listdir(tmpdir))
        print(f"Extracted {n_frames} frames. Scanning masks...")

        prev_masks = {}
        prev_bug = False
        detections = []  # (t, side, diff_px)
        pending = None   # candidate change awaiting persistence check

        for i in range(1, n_frames + 1):
            t = i - 1  # fps=1: frame N is at second N-1
            img = cv2.imread(os.path.join(tmpdir, f"f_{i:05d}.jpg"))
            if img is None:
                continue
            bug_present = int(np.sum(white_mask(img, clock_region) > 0)) >= SCOREBUG_MIN_WHITE
            masks = {s: white_mask(img, r) for s, r in regions.items()}

            if prev_masks and bug_present and prev_bug:
                for side in ("away", "home"):
                    diff = int(np.sum(cv2.bitwise_xor(masks[side], prev_masks[side]) > 0))
                    if diff > CHANGE_PX:
                        if pending and pending["side"] == side and t - pending["t"] <= 2:
                            continue  # settling of same change
                        pending = {"t": t, "side": side, "diff": diff}
                        detections.append((t, side, diff))
            prev_masks = masks
            prev_bug = bug_present

    print(f"\nDetected raw change points: {len(detections)}")
    for t, side, diff in detections:
        gt = next((g for g in GROUND_TRUTH if abs(g[0] - t) <= 3), None)
        tag = f"  <-- GT {gt[2]} {gt[1]} ({gt[0]}s)" if gt else ""
        print(f"  t={t:5d}s  {side:<5} diff={diff:5d}{tag}")

    print(f"\nGround truths matched: "
          f"{sum(1 for g in GROUND_TRUTH if any(abs(g[0]-t)<=3 and s=='home' for t, s, _ in detections))}/7")


if __name__ == "__main__":
    main()
