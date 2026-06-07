# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Project

NBA Highlight MVP: given a full-game NBA video file + an NBA game ID, automatically generate per-player highlight clip reels. The pipeline fetches play-by-play data from the NBA API, maps scoring events to video timestamps, and cuts clips with FFmpeg.

The test game is GSW vs LAL, May 19 2021, Play-In Tournament (game ID `0052000121`).

## Build & Run

```bash
# Install dependencies (from backend/)
cd backend && uv sync

# Run backend server
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Run all tests
cd backend && uv run pytest tests/ -v

# Run a single test file
cd backend && uv run pytest tests/test_moment_service.py -v

# Run a single test by name
cd backend && uv run pytest tests/ -k "test_name" -v
```

## Architecture

**Pipeline flow:** Upload video + game ID -> NBA API fetch -> moment extraction -> timestamp refinement -> FFmpeg clip cutting -> per-player output folders.

**Key services** (all in `backend/app/services/`):
- `nba_service.py` - Fetches play-by-play from nba_api; normalizes PT clock format; mock JSON fallback
- `moment_service.py` - Extracts highlight-worthy events, assigns importance scores
- `timeline_service.py` - Legacy formula mapper (game clock -> video timestamp); drifts in full games
- `refinement_service.py` - Sequential anchor chain: each confirmed timestamp anchors the next search
- `clip_service.py` - Calculates clip bounds, cuts via FFmpeg
- `scoreboard_scan_service.py` - Deterministic scorebug OCR/template scanner (in progress)

**Utilities** (`backend/app/utils/`):
- `constants.py` - Single source of truth for all magic numbers (clip durations, quarter lengths, etc.)
- `paths.py` - All file path resolution; `sanitize_player_name()` used everywhere
- `ffmpeg.py` - `cut_clip()`, `get_video_duration()`, `concatenate_clips()`

**Data layout:**
- `backend/data/uploads/{game_id}/` - uploaded full game video
- `backend/data/outputs/{game_id}/clips/` - individual moment clips by player
- `backend/data/mock/` - mock play-by-play JSON fallback

**API routes** (`backend/app/api/`): auth, games, moments, clips - all under `/api/` prefix. Health at `/health`.

**Database:** SQLite via SQLAlchemy. Tables: users, games, moments, clips, rendered_videos. Auto-created on startup.

## Hard Rules

- Never commit MP4/video files to git. Never commit files from `backend/data/uploads/` or `backend/data/outputs/`.
- All magic numbers go in `constants.py`, nowhere else.
- All file paths go through `paths.py`, never hardcoded.
- All tests must pass before a phase is marked complete.
- Test fixtures use `conftest.py` shared `mock_events` dataset and `db` fixture.

## Current State

Phase 5A (anchor chain baseline) complete but too slow for MVP. Phases 5B (deterministic scorebug scanner) and 5C (event mapping + confidence) are in progress. See `docs/PHASES.md` for full roadmap and `docs/ARCHITECTURE.md` for pipeline details.
