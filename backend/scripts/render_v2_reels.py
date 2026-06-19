"""Stitch the v2 clips into one highlight reel per player.

Reads data/outputs/{game}/clips_v2/{player}/*.mp4 (sorted by the leading sequence number =
game order) and writes data/outputs/{game}/reels_v2/{player}.mp4.

Usage:
    .venv/Scripts/python.exe scripts/render_v2_reels.py
"""

import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.render_service import RenderService
from app.utils.paths import get_game_output_dir

NBA_GAME_ID = "0052000121"


def main():
    out_dir = get_game_output_dir(NBA_GAME_ID)
    clips_root = os.path.join(out_dir, "clips_v2")
    reels_root = os.path.join(out_dir, "reels_v2")
    os.makedirs(reels_root, exist_ok=True)

    renderer = RenderService()
    players = sorted(
        d for d in os.listdir(clips_root)
        if os.path.isdir(os.path.join(clips_root, d))
    )
    print(f"Players: {len(players)}\n")

    for player in players:
        clips = sorted(glob.glob(os.path.join(clips_root, player, "*.mp4")))
        if not clips:
            continue
        out_path = os.path.join(reels_root, f"{player}.mp4")
        result = renderer.render_reel(clips, out_path)
        status = "OK" if result else "FAILED"
        print(f"  {status}  {player:<20} {len(clips)} clips -> {os.path.basename(out_path)}")

    print(f"\nReels in: {reels_root}")


if __name__ == "__main__":
    main()
