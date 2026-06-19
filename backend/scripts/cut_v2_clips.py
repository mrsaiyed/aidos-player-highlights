"""Cut the Phase 6 (v2) clip set for review WITHOUT touching the graded first-run clips.

Runs the real pipeline — forward score-signature anchor chain + dynamic play-aware windows —
in a throwaway DB, and writes clips to data/outputs/{game}/clips_v2/{player}/. The first-run
clips in clips/ and the ground truth in app.db are left untouched.

Usage:
    .venv/Scripts/python.exe scripts/cut_v2_clips.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
import app.models.user  # noqa: F401
import app.models.game  # noqa: F401
import app.models.clip  # noqa: F401
from app.services.nba_service import NBAService
from app.services.moment_service import MomentService
from app.services.refinement_service import RefinementService
from app.services.clip_service import ClipService
from app.utils.ffmpeg import cut_clip, get_video_duration
from app.utils.paths import get_game_output_dir, sanitize_player_name

NBA_GAME_ID = "0052000121"
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VIDEO = os.path.join(BACKEND, "data", "uploads", NBA_GAME_ID, "full_game.mp4")


def main():
    out_root = os.path.join(get_game_output_dir(NBA_GAME_ID), "clips_v2")
    os.makedirs(out_root, exist_ok=True)

    tmp_db = os.path.join(tempfile.gettempdir(), "cut_v2.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    engine = create_engine(f"sqlite:///{tmp_db}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    print("Fetching play-by-play and building moments...")
    events = NBAService().fetch_play_by_play(NBA_GAME_ID)
    moments = MomentService().process_events(events, game_id=1, db=db, mode="buckets")
    lal = [m for m in moments if m.team == "LAL"]
    print(f"LAL made-shot moments: {len(lal)}\n")

    print("Running forward score-signature anchor chain (this is the slow part)...")
    summary = RefinementService().refine_moments(1, NBA_GAME_ID, lal, db, use_watch_fallback=False)
    print(f"chain: {summary}\n")

    duration = get_video_duration(VIDEO)
    clipper = ClipService()
    ordered = sorted(lal, key=lambda m: (m.period, -RefinementService()._parse_game_clock(m.game_clock)))

    manifest = []
    seq = 0
    for m in ordered:
        seq += 1
        if m.video_time_seconds is None:
            manifest.append(f"{seq:02d}  Q{m.period} {m.game_clock:>5} {m.player_name:<18} FLAGGED (no timestamp)")
            continue
        start, end = clipper.calculate_clip_bounds(m.video_time_seconds, duration, m.transition_lead_seconds)
        player_dir = os.path.join(out_root, sanitize_player_name(m.player_name))
        os.makedirs(player_dir, exist_ok=True)
        clock_tag = m.game_clock.replace(":", "m") + "s"
        fname = f"{seq:02d}_Q{m.period}_{clock_tag}_{m.event_subtype or 'shot'}.mp4"
        out_path = os.path.join(player_dir, fname)
        ok = cut_clip(VIDEO, out_path, start, end)
        lead = f" +lead{m.transition_lead_seconds:.0f}" if m.transition_lead_seconds else ""
        manifest.append(
            f"{seq:02d}  Q{m.period} {m.game_clock:>5} {m.player_name:<18} "
            f"flip={m.video_time_seconds:7.1f}  clip=[{start:7.1f},{end:7.1f}]{lead}  "
            f"{'OK' if ok else 'FAILED'}  {fname}"
        )
        print(f"  [{seq:02d}] {'OK' if ok else 'FAIL'}  {m.player_name} {fname}")

    manifest_path = os.path.join(out_root, "manifest.txt")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("Phase 6 (v2) clip set — forward signature chain + dynamic windows\n")
        f.write(f"chain summary: {summary}\n\n")
        f.write("\n".join(manifest) + "\n")

    print(f"\nDone. {seq} plays processed -> {out_root}")
    print(f"Manifest: {manifest_path}")
    db.close()


if __name__ == "__main__":
    main()
