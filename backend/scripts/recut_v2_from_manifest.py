"""Re-cut the v2 clips using the already-computed flip timestamps in clips_v2/manifest.txt.

The detection chain is deterministic, so the flip seconds don't change when only the clip
window changes — this re-cuts with the current ClipService.calculate_clip_bounds (no 9-min
chain re-run). Overwrites clips in clips_v2/ and rewrites the manifest.

Usage:
    .venv/Scripts/python.exe scripts/recut_v2_from_manifest.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.clip_service import ClipService
from app.utils.ffmpeg import cut_clip, get_video_duration
from app.utils.paths import get_game_output_dir, sanitize_player_name

NBA_GAME_ID = "0052000121"
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VIDEO = os.path.join(BACKEND, "data", "uploads", NBA_GAME_ID, "full_game.mp4")

LINE = re.compile(
    r"^\s*(\d+)\s+Q(\d+)\s+([\d:]+)\s+(\S+)\s+flip=\s*([\d.]+).*?(\S+\.mp4)\s*$"
)


def main():
    out_root = os.path.join(get_game_output_dir(NBA_GAME_ID), "clips_v2")
    manifest_path = os.path.join(out_root, "manifest.txt")
    with open(manifest_path, encoding="utf-8") as f:
        lines = f.readlines()

    duration = get_video_duration(VIDEO)
    clipper = ClipService()
    new_manifest = ["Phase 6 (v2) clip set — re-cut with SCORE_FLIP_LAG=3 uniform window\n\n"]

    for line in lines:
        m = LINE.match(line)
        if not m:
            continue
        seq, period, clock, player, flip, fname = m.groups()
        flip = float(flip)
        start, end = clipper.calculate_clip_bounds(flip, duration)
        player_dir = os.path.join(out_root, sanitize_player_name(player))
        os.makedirs(player_dir, exist_ok=True)
        out_path = os.path.join(player_dir, fname)
        ok = cut_clip(VIDEO, out_path, start, end)
        new_manifest.append(
            f"{seq}  Q{period} {clock:>5} {player:<18} flip={flip:7.1f}  "
            f"clip=[{start:7.1f},{end:7.1f}] ({end - start:.0f}s)  {'OK' if ok else 'FAILED'}  {fname}\n"
        )
        print(f"  [{seq}] {'OK' if ok else 'FAIL'}  {player} {fname}  [{start:.1f},{end:.1f}]")

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.writelines(new_manifest)
    print(f"\nRe-cut complete -> {out_root}")


if __name__ == "__main__":
    main()
