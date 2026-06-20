# Agent Notes

Guidance for AI coding assistants working in this repo. Full project instructions are in
[CLAUDE.md](CLAUDE.md); product direction is in [docs/STRATEGY.md](docs/STRATEGY.md).

## What this is

A single-operator **command-line** tool that turns an NBA game video + game ID into per-player
highlight reels and uploads them to YouTube. **No web frontend, no auth.** Python / FastAPI
backend, driven as scripts. Detection is **deterministic** (matching the on-screen scoreboard
score to the NBA play-by-play); **buckets / made shots only** for now.

## The pipeline (layers)

`ingest (clip engine) → clip library → compose (query → reel) → review/nudge → publish (YouTube)`

- `ingest_service` runs the sealed engine over all made shots and writes tagged `LibraryClip`
  rows; `compose_service` queries the library into reels; `youtube_publisher` uploads.
- The **clip engine is sealed**: its only output is "a tagged clip in the library." Compose and
  publish depend on that contract, never on detection internals — so detection can be refined
  without touching them.

## Conventions

- All magic numbers live in `backend/app/utils/constants.py`; all paths via `paths.py`.
- **Never commit** video files (`backend/data/`) or secrets (`backend/secrets/`).
- **Broadcast is a per-game profile** (`scorebug_regions.py`) — never hardcode one broadcast.
- Tests must pass before a change is done: `cd backend && uv run pytest tests/ -v`.

## Layout

- `backend/app/services/` — `nba_service`, `moment_service`, `score_change_detector`,
  `refinement_service`, `clip_service`, `render_service`, `ingest_service`, `compose_service`,
  `youtube_publisher`
- `backend/scripts/` — the CLI: `ingest_game`, `compose_reel`, `nudge_clip`, `youtube_auth`,
  `publish_reel` (plus validation/diagnostic scripts)
- `docs/` — `STRATEGY` (canonical), `PROJECT`, `ARCHITECTURE`, `PHASES`, `phases/`

## What's left

- **Track B** — broadcast generalization / auto-calibration (the gate to arbitrary games).
- Parked: clock-OCR pipeline (kept for future non-scoring events). Buckets-only is current scope.
