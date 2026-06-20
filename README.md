# NBA Player Highlights

Turn a full NBA game video + the game's ID into **per-player highlight reels** — automatically
detected, cut, tagged, and uploaded to YouTube. A single-operator command-line tool. No web app,
no accounts.

## What it does

Given a full-game recording and an NBA game ID:

1. Pulls the official play-by-play (every made shot, with score + game clock).
2. **Finds the exact video moment of each basket** by matching the on-screen scoreboard score to
   the play-by-play — deterministic, no AI at runtime.
3. Cuts a clip per made shot into a **tagged clip library** (player, shot type, distance, period,
   date, season, …).
4. Composes any reel as a **query** — "AD all 3s," "Steph floaters," "Q4 buckets," "December 3s" —
   into one stitched video.
5. Quick human review (nudge a clip a couple seconds earlier/later) → **upload to YouTube**.

## Status

Working and **validated end-to-end on the demo game** (ESPN Play-In, GSW vs LAL, 2021-05-19):
74 baskets ingested, reels composed by query, reviewed, and uploaded to YouTube. It runs today on
that one broadcast. Making it work on **arbitrary broadcasts** (League Pass downloads) is the next
piece — see [`docs/STRATEGY.md`](docs/STRATEGY.md) (Track B: auto-calibration).

## Setup

```bash
cd backend && uv sync          # Python 3.12; needs FFmpeg + ffprobe on PATH
```

## The pipeline (CLI)

Run from `backend/` (use `uv run python …`, or `.venv/Scripts/python.exe …` directly on Windows):

```bash
# 1. Ingest a game into the library (data/library.db)
uv run python scripts/ingest_game.py <game_id> <video.mp4> <broadcast_profile>

# 2. Compose a reel by query
uv run python scripts/compose_reel.py --player Davis --category dunk --name ad_dunks
#   filters: --player --team --opponent --value --subtype --category(dunk/layup/three/two/
#            floater/midrange/paint) --period --season --month --from/--to --distance-min/max

# 3. (optional) review fix: nudge a clip earlier/later, then re-compose
uv run python scripts/nudge_clip.py --id <id> --earlier 5

# 4. Connect YouTube once, then publish a reviewed reel
uv run python scripts/youtube_auth.py
uv run python scripts/publish_reel.py --name ad_dunks --privacy unlisted
```

## Tests

```bash
cd backend && uv run pytest tests/ -v
```

## Docs

- [`docs/STRATEGY.md`](docs/STRATEGY.md) — product strategy + five-layer architecture (**start here**)
- [`docs/PROJECT.md`](docs/PROJECT.md) — what it is + "How It Works" (plain-English & technical)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the sealed clip engine
- [`docs/PHASES.md`](docs/PHASES.md) — phase history + roadmap
- [`docs/phases/`](docs/phases/) — per-phase records, including `first_run.md` (the original validation run)

## Hard rules

Never commit video files (`backend/data/`) or secrets (`backend/secrets/`). Buckets (made shots)
only for now. The clip engine is sealed — downstream depends on "a tagged clip in the library,"
not on detection internals. Broadcast is a per-game profile, never hardcoded.
