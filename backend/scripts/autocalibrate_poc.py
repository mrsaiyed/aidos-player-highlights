"""Track B proof-of-concept: auto-derive a broadcast scoreboard profile from the API score
sequence — no hardcoded regions.

Sample frames across the game, run full-frame OCR, then:
  - SCORE boxes = the two fixed-location regions whose integer readings climb across the game and
    top out near the two final scores. Which final value each matches gives home vs away.
  - CLOCK = the fixed-location region reading MM:SS.

Validation: run on the demo ESPN game; the discovered regions should match the hardcoded espn
profile (away=(210,648,95,40) home=(315,648,90,40) clock=(598,636,125,32)).

    .venv/Scripts/python.exe scripts/autocalibrate_poc.py
"""

import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2

from app.services.nba_service import NBAService
from app.utils.ffmpeg import _resolve_tool, get_video_duration

GAME_ID = "0052000121"
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VIDEO = os.path.join(BACKEND, "data", "uploads", GAME_ID, "full_game.mp4")
N_FRAMES = 28
GRID = 40
CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def final_scores():
    home = away = 0
    for e in NBAService().fetch_play_by_play(GAME_ID):
        sa = (e.get("score_after") or "").split()
        if len(sa) >= 4:
            try:
                home, away = int(sa[1]), int(sa[3])
            except ValueError:
                pass
    return home, away


def bbox_of(obs):
    xs1 = [o["x"] for o in obs]; ys1 = [o["y"] for o in obs]
    xs2 = [o["x"] + o["w"] for o in obs]; ys2 = [o["y"] + o["h"] for o in obs]
    x, y = int(min(xs1)), int(min(ys1))
    return (x, y, int(max(xs2)) - x, int(max(ys2)) - y)


def main():
    import easyocr
    duration = get_video_duration(VIDEO)
    fracs = [0.04 + 0.89 * i / (N_FRAMES - 1) for i in range(N_FRAMES)]
    times = [duration * f for f in fracs]
    home_final, away_final = final_scores()
    print(f"Game {GAME_ID}: final home={home_final} away={away_final}; {N_FRAMES} frames\n")

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"

    num_cells = defaultdict(list)   # cell -> [{i,val,x,y,w,h}]
    clock_cells = defaultdict(list)
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            p = os.path.join(tmp, f"f{i}.jpg")
            subprocess.run([ffmpeg, "-ss", f"{t:.2f}", "-i", VIDEO, "-vframes", "1",
                            "-q:v", "2", "-y", p], capture_output=True)
            img = cv2.imread(p)
            if img is None:
                continue
            for box, text, conf in reader.readtext(img, allowlist="0123456789:"):
                xs = [pt[0] for pt in box]; ys = [pt[1] for pt in box]
                x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
                cell = (int((x + w / 2) // GRID), int((y + h / 2) // GRID))
                rec = {"i": i, "x": x, "y": y, "w": w, "h": h}
                m = CLOCK_RE.match(text.strip())
                if m and int(m.group(1)) <= 12 and int(m.group(2)) <= 59:
                    clock_cells[cell].append({**rec, "val": text.strip()})
                else:
                    digits = "".join(c for c in text if c.isdigit())
                    if digits and int(digits) <= 199:
                        num_cells[cell].append({**rec, "val": int(digits)})

    # --- persistent numeric regions (candidates) ---
    cands = []
    for cell, obs in num_cells.items():
        if len(obs) < N_FRAMES * 0.35:
            continue
        obs.sort(key=lambda o: o["i"])
        vals = [o["val"] for o in obs]
        nondec = sum(vals[k] <= vals[k + 1] for k in range(len(vals) - 1)) / max(1, len(vals) - 1)
        cands.append({"obs": obs, "vals": vals, "nondec": nondec, "max": max(vals),
                      "n": len(obs), "bbox": bbox_of(obs)})
    cands.sort(key=lambda c: c["max"], reverse=True)
    print("Persistent numeric regions:")
    for c in cands:
        print(f"  bbox={str(c['bbox']):<20} n={c['n']:>2} nondec={c['nondec']:.2f} max={c['max']:>3} "
              f"vals={c['vals'][:3]}..{c['vals'][-3:]}")

    # score boxes = two spatially-distinct regions whose max sits AT a real final score
    def near_final(m):
        return min(abs(m - home_final), abs(m - away_final)) <= 8
    score_like = [c for c in cands if c["nondec"] > 0.8 and near_final(c["max"])]
    boxes = []
    for c in score_like:
        if all(abs(c["bbox"][0] - b["bbox"][0]) > GRID for b in boxes):
            boxes.append(c)
        if len(boxes) == 2:
            break

    print("\nDiscovered score boxes (auto):")
    if len(boxes) == 2:
        # home/away by matching joint (left,right) readings to API (home,away) pairs
        api_pairs = set()
        for e in NBAService().fetch_play_by_play(GAME_ID):
            sa = (e.get("score_after") or "").split()
            if len(sa) >= 4:
                try:
                    api_pairs.add((int(sa[1]), int(sa[3])))
                except ValueError:
                    pass
        boxes.sort(key=lambda c: c["bbox"][0])  # left, right
        left = {o["i"]: o["val"] for o in boxes[0]["obs"]}
        right = {o["i"]: o["val"] for o in boxes[1]["obs"]}
        common = set(left) & set(right)
        lr = sum(1 for i in common if (left[i], right[i]) in api_pairs)   # left=home, right=away
        rl = sum(1 for i in common if (right[i], left[i]) in api_pairs)   # left=away, right=home
        home_b, away_b = (boxes[0], boxes[1]) if lr >= rl else (boxes[1], boxes[0])
        print(f"  HOME ~= {home_b['bbox']}  max={home_b['max']}   (joint-match home-left={lr} home-right={rl})")
        print(f"  AWAY ~= {away_b['bbox']}  max={away_b['max']}")
    else:
        print(f"  only found {len(boxes)} distinct score box(es): {[b['bbox'] for b in boxes]}")

    # --- clock: most-populated MM:SS cell ---
    if clock_cells:
        cell, obs = max(clock_cells.items(), key=lambda kv: len(kv[1]))
        print(f"\nDiscovered clock (auto):")
        print(f"  CLOCK ~= {bbox_of(obs)}   seen {len(obs)}x  e.g. {[o['val'] for o in obs[:4]]}")
    else:
        print("\nNo clock region found.")

    print("\nHardcoded espn: away=(210,648,95,40) home=(315,648,90,40) clock=(598,636,125,32)")


if __name__ == "__main__":
    main()
