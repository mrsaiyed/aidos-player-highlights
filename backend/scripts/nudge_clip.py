"""Review correction: shift a library clip earlier or later by N seconds and re-cut it.

The detector is high-accuracy; on the rare clip where the bucket is a touch early/late (the
scoreboard-flip lag varies), nudge it and re-cut in place. Re-run compose_reel afterward to
rebuild any reel that uses it.

Examples:
    # clip's bucket is before the window -> pull it earlier
    .venv/Scripts/python.exe scripts/nudge_clip.py --id 51 --earlier 5
    # too early in the clip -> push it later
    .venv/Scripts/python.exe scripts/nudge_clip.py --id 51 --later 3
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:  # accented player names crash the default Windows console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.library_clip import LibraryClip
from app.utils.ffmpeg import cut_clip, get_video_duration
from app.utils.paths import get_game_upload_dir

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIBRARY_DB = os.path.join(BACKEND, "data", "library.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, required=True, help="library clip id (shown by compose_reel)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--earlier", type=float, help="shift the clip earlier by N seconds")
    g.add_argument("--later", type=float, help="shift the clip later by N seconds")
    args = ap.parse_args()

    delta = -args.earlier if args.earlier is not None else args.later

    db = sessionmaker(bind=create_engine(f"sqlite:///{LIBRARY_DB}"))()
    clip = db.query(LibraryClip).get(args.id)
    if clip is None:
        print(f"No library clip id={args.id}"); return
    if clip.file_path is None:
        print(f"Clip id={args.id} was flagged (no file) — nothing to nudge."); return

    video = os.path.join(get_game_upload_dir(clip.nba_game_id), "full_game.mp4")
    if not os.path.exists(video):
        print(f"Source video not found: {video}"); return
    duration = get_video_duration(video)

    new_start = max(0.0, clip.clip_start + delta)
    new_end = min(duration, clip.clip_end + delta)
    print(f"Clip {args.id}: {clip.player_name} Q{clip.period} {clip.game_clock} "
          f"[{clip.clip_start:.1f},{clip.clip_end:.1f}] -> [{new_start:.1f},{new_end:.1f}]  ({delta:+.1f}s)")

    ok = cut_clip(video, clip.file_path, new_start, new_end)
    if not ok:
        print("Re-cut FAILED."); return
    clip.clip_start, clip.clip_end = new_start, new_end
    clip.adjust_seconds = (clip.adjust_seconds or 0.0) + delta
    db.commit()
    print(f"Re-cut OK -> {clip.file_path}  (total adjust {clip.adjust_seconds:+.1f}s)")
    print("Re-run compose_reel for any reel using this clip to rebuild it.")
    db.close()


if __name__ == "__main__":
    main()
