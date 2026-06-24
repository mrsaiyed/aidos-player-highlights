"""Find an NBA game_id from a team + date (so you can ingest a downloaded/captured game).

    .venv/Scripts/python.exe scripts/find_game_id.py --team DAL --date 2024-01-26
    .venv/Scripts/python.exe scripts/find_game_id.py --team Houston --date 2025-01-15

Prints:  <game_id>  <AWAY @ HOME>   — feed the game_id to ingest_game.py.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.nba_service import NBAService


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", required=True, help="tricode (DAL) or city (Dallas)")
    ap.add_argument("--date", required=True, help="game date, YYYY-MM-DD")
    args = ap.parse_args()

    gid, matchup = NBAService.find_game_id(args.team, args.date)
    if gid:
        print(f"{gid}  {matchup}")
    else:
        print(f"No game found for {args.team} on {args.date}")
        sys.exit(1)


if __name__ == "__main__":
    main()
