"""Ingest a game into the durable clip library (data/library.db).

Usage:
    .venv/Scripts/python.exe scripts/ingest_game.py [nba_game_id] [video_path] [profile]

Defaults to the demo game. Re-running the same game is idempotent (dedup on game_id+action_id).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
import app.models.user        # noqa: F401  (register tables)
import app.models.game        # noqa: F401
import app.models.clip        # noqa: F401
import app.models.moment      # noqa: F401
from app.models.library_clip import LibraryClip
from app.services.ingest_service import IngestService

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIBRARY_DB = os.path.join(BACKEND, "data", "library.db")


def main():
    game_id = sys.argv[1] if len(sys.argv) > 1 else "0052000121"
    video = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        BACKEND, "data", "uploads", game_id, "full_game.mp4")
    profile = sys.argv[3] if len(sys.argv) > 3 else "espn"

    if not os.path.exists(video):
        print(f"Video not found: {video}")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{LIBRARY_DB}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    print(f"Ingesting {game_id} (profile={profile})\n  video: {video}\n  library: {LIBRARY_DB}\n")
    summary = IngestService(profile).ingest(game_id, video, db)
    print(f"\nSummary: {summary}\n")

    # Prove the library is queryable — the same op behind any reel.
    total = db.query(func.count(LibraryClip.id)).scalar()
    print(f"Library now holds {total} clips.\n")

    print("Clips per player (this game):")
    rows = (db.query(LibraryClip.player_name, func.count(LibraryClip.id))
            .filter(LibraryClip.nba_game_id == game_id)
            .group_by(LibraryClip.player_name)
            .order_by(func.count(LibraryClip.id).desc()).all())
    for name, n in rows:
        print(f"  {name:<20} {n}")

    print("\nExample query — Davis 3-pointers:")
    threes = (db.query(LibraryClip)
              .filter(LibraryClip.player_name == "Davis", LibraryClip.shot_value == 3)
              .order_by(LibraryClip.period, LibraryClip.game_clock.desc()).all())
    for c in threes:
        print(f"  Q{c.period} {c.game_clock:>5}  {c.sub_type_raw}  conf={c.confidence}  {c.file_path and os.path.basename(c.file_path)}")

    db.close()


if __name__ == "__main__":
    main()
