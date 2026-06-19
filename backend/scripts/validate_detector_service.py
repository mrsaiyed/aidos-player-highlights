"""Regression check: run the REAL score_change_detector service against the 37
watch-confirmed ground truths in app.db. Confirms the v2 port didn't regress.

Usage:
    .venv/Scripts/python.exe scripts/validate_detector_service.py
"""

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.score_change_detector import verify_score_change

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BACKEND, "data", "app.db")
VIDEO_PATH = os.path.join(BACKEND, "data", "uploads", "0052000121", "full_game.mp4")


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
        t1 = time.time()
        vr = verify_score_change(VIDEO_PATH, gt, before, after, profile_name="espn")
        el = time.time() - t1
        if not vr.verified:
            misses += 1
            print(f"MISS Q{period} {clock:>5} {player:<18} gt={gt:7.1f}s  ({el:.1f}s)")
            continue
        delta = vr.video_second - gt
        deltas.append(delta)
        ok = abs(delta) <= 2.0
        hits += ok
        misses += not ok
        print(f"{'OK ' if ok else 'OFF'} Q{period} {clock:>5} {player:<18} gt={gt:7.1f}s "
              f"det={vr.video_second:7.1f}s delta={delta:+5.1f}s [{vr.confidence}]  ({el:.1f}s)")

    total = time.time() - t0
    print(f"\nWithin +-2s: {hits}/{len(rows)}  |  off/miss: {misses}")
    if deltas:
        deltas.sort()
        print(f"delta median={deltas[len(deltas)//2]:+.1f}s min={deltas[0]:+.1f}s max={deltas[-1]:+.1f}s")
    print(f"Total: {total:.0f}s ({total/len(rows):.1f}s per event)")


if __name__ == "__main__":
    main()
