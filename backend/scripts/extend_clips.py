"""Extend matching library clips by N seconds at the END (re-cut in place).

Adds time to the tail of each clip without changing its start — e.g. turn the 8s clips into 10s.
Updates the library so every future reel uses the longer clips. Re-run compose/make_player_reels
afterward to rebuild reels.

    .venv/Scripts/python.exe scripts/extend_clips.py --team LAL --game 0052000121 --seconds 2
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.compose_service import ComposeService
from app.utils.ffmpeg import cut_clip, get_video_duration
from app.utils.paths import get_game_upload_dir

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIBRARY_DB = os.path.join(BACKEND, "data", "library.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, required=True, help="seconds to add to each clip's end")
    ap.add_argument("--team")
    ap.add_argument("--game")
    ap.add_argument("--player")
    ap.add_argument("--category")
    ap.add_argument("--season")
    args = ap.parse_args()

    filters = {k: v for k, v in vars(args).items() if k != "seconds" and v is not None}
    db = sessionmaker(bind=create_engine(f"sqlite:///{LIBRARY_DB}"))()
    clips = ComposeService().query(db, **filters)
    print(f"Extending {len(clips)} clips by +{args.seconds}s at the end  filters={filters}\n")

    durations: dict[str, float] = {}
    done = 0
    for c in clips:
        video = os.path.join(get_game_upload_dir(c.nba_game_id), "full_game.mp4")
        if c.nba_game_id not in durations:
            durations[c.nba_game_id] = get_video_duration(video)
        new_end = min(durations[c.nba_game_id], c.clip_end + args.seconds)
        if cut_clip(video, c.file_path, c.clip_start, new_end):
            c.clip_end = new_end
            db.commit()
            done += 1
        else:
            print(f"  re-cut FAILED for id={c.id}")
    print(f"Re-cut {done}/{len(clips)} clips. New length ~= old + {args.seconds}s.")
    db.close()


if __name__ == "__main__":
    main()
