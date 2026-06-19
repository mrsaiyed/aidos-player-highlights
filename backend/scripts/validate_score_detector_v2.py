"""Improved score-change detector, validated against the 37 ground truths.

Changes vs score_change_detector.py:
  1. Tightened digit-only regions (no crowd above the bar, full 3-digit span):
     away right-aligned (210,648,95,40), home left-aligned (315,648,90,40).
  2. One ffmpeg call per event window (fps=2 over 16s) instead of 33 seeks.
  3. Persistence: a transition counts only if the mask stays changed for the
     following ~2s (rejects jersey/animation blips).
  4. Single-side rule: if the other team's region jumps at the same frame, it
     is a bar-wide animation/wipe, not a score change — skip it.

Usage:
    .venv/Scripts/python.exe scripts/validate_score_detector_v2.py
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np

from app.utils.ffmpeg import _resolve_tool

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BACKEND, "data", "app.db")
VIDEO_PATH = os.path.join(BACKEND, "data", "uploads", "0052000121", "full_game.mp4")

REGIONS = {
    "away": (210, 648, 95, 40),   # GSW score digits, right-aligned
    "home": (315, 648, 90, 40),   # LAL score digits, left-aligned
}
WHITE = 170
TH = 70          # mask-diff px to call a change
WINDOW = 8.0     # seconds each side of rough timestamp
FPS = 2
PERSIST = 4      # of the next 4 frames, >=3 must stay changed


def white_mask(img, region):
    x, y, w, h = region
    crop = img[y:y + h, x:x + w]
    return cv2.inRange(crop, (WHITE, WHITE, WHITE), (255, 255, 255))


def extract_window(video, start, dur, out_dir):
    ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"
    pattern = os.path.join(out_dir, "f_%04d.jpg")
    subprocess.run(
        [ffmpeg, "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", video,
         "-vf", f"fps={FPS}", "-q:v", "2", "-y", pattern],
        capture_output=True, timeout=120,
    )
    frames = []
    i = 1
    while True:
        p = os.path.join(out_dir, f"f_{i:04d}.jpg")
        if not os.path.exists(p):
            break
        img = cv2.imread(p)
        if img is not None:
            frames.append((start + (i - 1) / FPS, img))
        i += 1
    return frames


def detect(video, rough_ts, side):
    """Return video second of the persistent single-side mask transition, or None."""
    start = max(0.0, rough_ts - WINDOW)
    other = "home" if side == "away" else "away"

    with tempfile.TemporaryDirectory() as tmpdir:
        frames = extract_window(video, start, 2 * WINDOW, tmpdir)
        if len(frames) < PERSIST + 2:
            return None

        ref = {s: white_mask(frames[0][1], REGIONS[s]) for s in REGIONS}
        diffs = {s: [] for s in REGIONS}
        for _, img in frames:
            for s in REGIONS:
                m = white_mask(img, REGIONS[s])
                diffs[s].append(int(np.sum(cv2.bitwise_xor(m, ref[s]) > 0)))

        n = len(frames)
        for i in range(1, n):
            if diffs[side][i] <= TH or diffs[side][i - 1] > TH:
                continue  # not a fresh crossing
            # persistence: >=3 of next 4 frames stay changed
            future = diffs[side][i + 1:i + 1 + PERSIST]
            if future and sum(1 for d in future if d > TH) < min(3, len(future)):
                continue
            # single-side: other region must not freshly jump at the same moment
            if diffs[other][i] > TH and diffs[other][i - 1] <= TH:
                continue
            return frames[i][0]
    return None


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "select period, game_clock, player_name, score_before, score_after, video_time_seconds "
        "from moments where refinement_method='watch_confirmed' order by period, video_time_seconds"
    )
    rows = cur.fetchall()
    print(f"Ground-truth events: {len(rows)}\n")

    hits = misses = 0
    deltas = []
    t0 = time.time()

    for period, clock, player, before, after, gt in rows:
        # side: home (LAL) score listed first in 'LAL 98 GSW 98'
        b, a = before.split(), after.split()
        side = "home" if b[1] != a[1] else "away"
        t1 = time.time()
        det = detect(VIDEO_PATH, gt, side)
        el = time.time() - t1
        if det is None:
            misses += 1
            print(f"MISS Q{period} {clock:>5} {player:<18} gt={gt:7.1f}s  ({el:.1f}s)")
            continue
        delta = det - gt
        deltas.append(delta)
        ok = abs(delta) <= 2.0
        hits += ok
        misses += not ok
        print(f"{'OK ' if ok else 'OFF'} Q{period} {clock:>5} {player:<18} gt={gt:7.1f}s "
              f"det={det:7.1f}s delta={delta:+5.1f}s  ({el:.1f}s)")

    total = time.time() - t0
    print(f"\nWithin +-2s: {hits}/{len(rows)}  |  off/miss: {misses}")
    if deltas:
        deltas.sort()
        print(f"delta median={deltas[len(deltas)//2]:+.1f}s min={deltas[0]:+.1f}s max={deltas[-1]:+.1f}s")
    print(f"Total: {total:.0f}s ({total/len(rows):.1f}s per event)")


if __name__ == "__main__":
    main()
