"""Stage 3 checkpoint: run the NEW flip-detector anchor chain on the full game and
compare against the 37 watch-confirmed ground truths. Uses a throwaway temp DB so the
real app.db (which holds the ground truth) is untouched.

Usage:
    .venv/Scripts/python.exe scripts/checkpoint_full_run.py
"""

import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
import app.models.user  # noqa: F401  (register tables)
import app.models.game  # noqa: F401
import app.models.clip  # noqa: F401
from app.models.moment import Moment
from app.services.nba_service import NBAService
from app.services.moment_service import MomentService
from app.services.refinement_service import RefinementService

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REAL_DB = os.path.join(BACKEND, "data", "app.db")
NBA_GAME_ID = "0052000121"


def load_ground_truth():
    con = sqlite3.connect(REAL_DB)
    cur = con.cursor()
    cur.execute(
        "select period, game_clock, player_name, video_time_seconds "
        "from moments where refinement_method='watch_confirmed'"
    )
    gt = {(p, c, pl): v for p, c, pl, v in cur.fetchall()}
    con.close()
    return gt


def main():
    gt = load_ground_truth()
    print(f"Loaded {len(gt)} ground-truth timestamps.\n")

    tmp_db = os.path.join(tempfile.gettempdir(), "checkpoint_run.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    engine = create_engine(f"sqlite:///{tmp_db}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    events = NBAService().fetch_play_by_play(NBA_GAME_ID)
    moments = MomentService().process_events(events, game_id=1, db=db, mode="buckets")
    lal = [m for m in moments if m.team == "LAL"]
    print(f"LAL made-shot moments: {len(lal)}\n")

    t0 = time.time()
    summary = RefinementService().refine_moments(1, NBA_GAME_ID, lal, db, use_watch_fallback=False)
    elapsed = time.time() - t0

    rows = sorted(lal, key=lambda m: (m.period, -RefinementService()._parse_game_clock(m.game_clock)))
    print(f"{'Q':>2} {'clock':>5} {'player':<18} {'video':>8} {'conf':<5} {'lead':>5} {'dGT':>8}")
    print("-" * 60)
    within2 = 0
    for m in rows:
        key = (m.period, m.game_clock, m.player_name)
        g = gt.get(key)
        if g is not None and m.video_time_seconds is not None:
            delta = m.video_time_seconds - g
            within2 += abs(delta) <= 2.0
            dstr = f"{delta:+.1f}"
        else:
            dstr = "n/a"
        lead = f"{m.transition_lead_seconds:.0f}" if m.transition_lead_seconds else "-"
        vt = f"{m.video_time_seconds:.1f}" if m.video_time_seconds is not None else "None"
        print(f"{m.period:>2} {m.game_clock:>5} {m.player_name:<18} {vt:>8} {m.confidence or '-':<5} {lead:>5} {dstr:>8}")

    print("-" * 60)
    print(f"summary: {summary}")
    print(f"within ±2s of GT: {within2}/{len(rows)}  |  wall: {elapsed:.0f}s ({elapsed/len(rows):.1f}s/play)")
    db.close()


if __name__ == "__main__":
    main()
