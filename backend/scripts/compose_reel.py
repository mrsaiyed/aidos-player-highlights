"""Compose a reel from the clip library by filter (Compose layer / Track A2).

"Reels are queries." Examples:
    compose_reel.py --player Curry --category two --name curry_2pt
    compose_reel.py --category three --name all_threes
    compose_reel.py --player Davis --category dunk --name ad_dunks
    compose_reel.py --player Davis --category three --season 2020-21 --name ad_season_3s
    compose_reel.py --player Davis --month 12 --category three --name ad_december_3s
    compose_reel.py --player Curry --category floater --name curry_floaters
    compose_reel.py --player Davis --category midrange --name ad_middies
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

from app.services.compose_service import ComposeService

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIBRARY_DB = os.path.join(BACKEND, "data", "library.db")
COMPOSED_DIR = os.path.join(BACKEND, "data", "outputs", "composed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="output folder / reel name")
    ap.add_argument("--player")
    ap.add_argument("--team")
    ap.add_argument("--opponent")
    ap.add_argument("--value", type=int, help="2 or 3")
    ap.add_argument("--subtype", help="dunk/layup/jump_shot/three_pointer/hook_shot")
    ap.add_argument("--category", help="dunk/layup/three/two/floater/midrange/paint")
    ap.add_argument("--period", type=int)
    ap.add_argument("--season")
    ap.add_argument("--game")
    ap.add_argument("--distance-min", type=int, dest="distance_min")
    ap.add_argument("--distance-max", type=int, dest="distance_max")
    ap.add_argument("--month", type=int, help="1-12, filters on game month")
    ap.add_argument("--from", dest="date_from", help="ISO date lower bound")
    ap.add_argument("--to", dest="date_to", help="ISO date upper bound")
    ap.add_argument("--vertical", action="store_true", help="build a 9:16 reel for YouTube Shorts")
    args = ap.parse_args()

    filters = {k: v for k, v in vars(args).items()
               if k not in ("name", "vertical") and v is not None}
    db = sessionmaker(bind=create_engine(f"sqlite:///{LIBRARY_DB}"))()
    svc = ComposeService()
    clips = svc.query(db, **filters)

    print(f"Matched {len(clips)} clips for '{args.name}'  filters={filters}")
    for i, c in enumerate(clips, 1):
        print(f"  {i:02d}  id={c.id:<4} {c.game_date or '????-??-??'} Q{c.period} {c.game_clock:>5}  "
              f"{c.player_name:<16} {c.team} vs {c.opponent}  {c.sub_type_raw}")
    if not clips:
        print("Nothing to compose."); return

    res = svc.build_reel(clips, os.path.join(COMPOSED_DIR, args.name), args.name, filters, args.vertical)
    print(f"\nFolder: {res['folder']}")
    print(f"Reel:   {res['reel']}  ({res['clips']} clips)")
    db.close()


if __name__ == "__main__":
    main()
