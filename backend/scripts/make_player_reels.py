"""Batch-compose one reel PER player from a library query.

The everyday use case: "every Lakers player gets their own buckets reel from this game."
Queries the library with the given filters, groups the matched clips by player, and builds a
separate reel per player named {prefix}_{player}. Each is a normal composed reel, so
publish_reel.py --name {prefix}_{player} works directly.

Examples:
    # every Lakers player's buckets from one game
    .venv/Scripts/python.exe scripts/make_player_reels.py --team LAL --game 0052000121 --prefix lakers_buckets
    # every Laker's 3s across everything ingested this season
    .venv/Scripts/python.exe scripts/make_player_reels.py --team LAL --category three --season 2020-21 --prefix lal_threes
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
from app.utils.paths import sanitize_player_name

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIBRARY_DB = os.path.join(BACKEND, "data", "library.db")
COMPOSED_DIR = os.path.join(BACKEND, "data", "outputs", "composed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True, help="reel name prefix; each reel is {prefix}_{player}")
    ap.add_argument("--team")
    ap.add_argument("--opponent")
    ap.add_argument("--game")
    ap.add_argument("--category", help="dunk/layup/three/two/floater/midrange/paint")
    ap.add_argument("--value", type=int)
    ap.add_argument("--subtype")
    ap.add_argument("--period", type=int)
    ap.add_argument("--season")
    ap.add_argument("--month", type=int)
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--vertical", action="store_true", help="build 9:16 reels for YouTube Shorts")
    args = ap.parse_args()

    filters = {k: v for k, v in vars(args).items()
               if k not in ("prefix", "vertical") and v is not None}
    db = sessionmaker(bind=create_engine(f"sqlite:///{LIBRARY_DB}"))()
    svc = ComposeService()
    clips = svc.query(db, **filters)

    by_player: dict[str, list] = {}
    for c in clips:
        by_player.setdefault(c.player_name, []).append(c)

    print(f"{len(clips)} clips across {len(by_player)} players  filters={filters}\n")
    for player in sorted(by_player):
        group = by_player[player]
        name = f"{args.prefix}_{sanitize_player_name(player)}"
        res = svc.build_reel(group, os.path.join(COMPOSED_DIR, name), name,
                             {**filters, "player": player}, args.vertical)
        print(f"  {player:<18} {res['clips']:>2} clips -> composed/{name}/{name}.mp4")

    print(f"\nDone. Publish any with:  scripts/publish_reel.py --name {args.prefix}_<player> --privacy unlisted")
    db.close()


if __name__ == "__main__":
    main()
