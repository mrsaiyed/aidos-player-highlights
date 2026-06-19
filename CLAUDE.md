# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

(Note: `AGENTS.md` describes the original hackathon template scaffolding this repo was created from — devcontainer/Dockerfile conventions. It does not describe this project; this file does.)

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
- `refinement_service.py` - Phase 5A baseline: sequential anchor chain via Claude Watch (works, ~70% frame-perfect, but ~1h15m per game — too slow for MVP)
- `clip_service.py` - Calculates clip bounds, cuts via FFmpeg
- `clock_ocr_service.py` - Phase 6: single-pass EasyOCR over sampled frames reads the scorebug *clock* (not the score), builds a `ClockTable` mapping video seconds -> (period, clock remaining). Lookup is gap-aware: uses 1:1 offset from the nearest reading across dead-ball gaps instead of linear interpolation
- `event_resolver_service.py` - Phase 6: joins the `ClockTable` with moments, resolves each moment's video timestamp with high/medium/low confidence (by gap to nearest clock reading); Claude Watch fallback only for low-confidence events
- `score_change_detector.py` - Phase 6 verification step: white-pixel-mask diff in the score region finds the exact frame the scorebug score updates (no OCR, ~1s per event)

**Key design insight (Phase 6):** OCR the *clock*, not the score — the NBA API already provides scores and game clock per play; only the clock->video-second mapping is missing. An earlier score-OCR/template-matching attempt (Phase 5B) got 0/37 matches and was abandoned. See `docs/phases/phase-6-clock-ocr-pipeline.md`.

**Utilities** (`backend/app/utils/`):
- `constants.py` - Single source of truth for all magic numbers (clip durations, quarter lengths, OCR sample interval, confidence thresholds, etc.)
- `paths.py` - All file path resolution; `sanitize_player_name()` used everywhere
- `ffmpeg.py` - `cut_clip()`, `get_video_duration()`, `concatenate_clips()`
- `scorebug_regions.py` - Per-broadcast-network scorebug pixel-region profiles (clock/period/score crop boxes); `espn` is the default and matches the test game

**Diagnostic scripts** (`backend/scripts/`, run from `backend/` with `uv run python scripts/<name>.py`):
- `diagnose_ocr.py` - Runs clock OCR on a short sample, dumps cropped frames + readings to `data/outputs/{game_id}/ocr_diag/` for inspection
- `test_q1_ocr.py` - End-to-end Q1 hybrid pipeline test: clock table -> event resolution -> score-change verification -> clip cutting

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

The proven approach is the **Phase 5A anchor chain**: for each scoring play in game order, scan a narrow video window (positioned from the previous confirmed play + the NBA clock gap) and confirm the timestamp by finding where the scorebug score flips `score_before → score_after`. A full-game run validated it at ~92% timestamping (34/37); see `docs/phases/first_run.md` for the clip-by-clip post-mortem. Its only problems were **speed** (Claude `watch.py` confirmed every play, ~2 min each) and a **fixed 7s/1s clip window** that mis-fit 8 plays.

**Phase 6 (revised) is implemented** — `docs/phases/phase-6-implementation-plan.md`. The anchor chain (`refinement_service.py`) now scans **forward** from the last confirmed play and confirms each timestamp by **score signature**: a cheap white-mask diff finds candidate score-box changes, then targeted OCR requires the value to transition `score_before → score_after` (`score_change_detector.py:find_score_transition`). This rejects free throws / other baskets / animation blips that a pixel-only flip detector caught wrongly, and it self-heals (a missed play doesn't advance the anchor, so it can't cascade). `watch.py` is a flagged-only fallback (default off). Clip windows are **dynamic and play-aware** (`clip_service.py`: net = flip − lag; transition/steal plays get extra lead). One-shot entry point: `POST /api/games/{id}/process` with `GET /status`. Full-game check: 37/37 plays confirmable vs the first-run labels (`scripts/checkpoint_full_run.py`).

Two earlier directions are **not** active: Phase 5B scorebug OCR/template matching (abandoned, 0/37 — wrong target) and the Phase 5C clock-OCR pass (`clock_ocr_service` + `event_resolver_service`) which is **parked as redundant** with the anchor chain for scoring plays — kept only for future non-scoring events (blocks/steals/assists). Validation harness: `backend/scripts/validate_score_detector_v2.py`. See `docs/PHASES.md` for the roadmap and `docs/ARCHITECTURE.md` for the pipeline.
