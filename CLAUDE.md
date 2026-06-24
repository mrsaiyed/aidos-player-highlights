# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See also [AGENTS.md](AGENTS.md) (short agent notes) and [docs/STRATEGY.md](docs/STRATEGY.md) (canonical product + architecture).

## Project

NBA Player Highlights: given a full-game NBA video + game ID, automatically produce per-player highlight reels and upload them to YouTube. A **single-operator CLI tool — no web frontend, no auth.** The pipeline fetches play-by-play, finds each basket's exact video moment by matching the on-screen scoreboard score to the play-by-play, cuts a clip per made shot into a tagged **clip library**, composes reels by **query** ("AD all 3s", "Steph floaters"), allows a quick human nudge-review, and publishes to YouTube. Buckets (made shots) only for now.

The test game is GSW vs LAL, May 19 2021, Play-In Tournament (game ID `0052000121`).

## Build & Run

```bash
cd backend && uv sync          # Python 3.12; FFmpeg + ffprobe on PATH

# Tests
cd backend && uv run pytest tests/ -v
cd backend && uv run pytest tests/ -k "test_name" -v   # single test

# The pipeline (CLI). Run from backend/ — uv run python …, or .venv/Scripts/python.exe … on Windows:
uv run python scripts/ingest_game.py <game_id> <video.mp4> <profile>    # -> data/library.db
uv run python scripts/compose_reel.py --player Davis --category dunk --name ad_dunks
uv run python scripts/nudge_clip.py --id <id> --earlier 5               # review fix, then re-compose
uv run python scripts/youtube_auth.py                                   # one-time YouTube connect
uv run python scripts/publish_reel.py --name ad_dunks --privacy unlisted
```

The FastAPI app + `POST /process` endpoint exist, but the product is **script-driven (no frontend)**.

## Architecture

Five layers (see [docs/STRATEGY.md](docs/STRATEGY.md)): **ingest (clip engine) → clip library → compose (query → reel) → review/nudge → publish (YouTube)**. The clip engine is *sealed* — its only output is a tagged clip in the library, and broadcast is a per-game profile.

**Clip engine** (`backend/app/services/`) — find each basket's exact video moment, deterministically:
- `nba_service.py` - play-by-play (`playbyplayv3`) + mock fallback; derives home/away tricodes + season; carries raw shot fields (distance, value, subtype, court x/y, action_id)
- `moment_service.py` - filters to made shots; computes per-shot transition-lead (stored, not applied to bounds)
- `score_change_detector.py` - **the detector.** Scans frames forward, finds candidate score-box changes (OpenCV white mask), then EasyOCR confirms the value transitions `score_before → score_after` (the score *signature*). Returns the exact video second
- `refinement_service.py` - the anchor chain: walks every made shot in game order, calling the detector forward from the last confirmed play; records timestamp + confidence; self-heals on a miss. `watch.py` (Claude) is a default-off fallback
- `clip_service.py` - dynamic clip bounds (net = flip − 3s; 5s before / 3s after) + FFmpeg cut

**Library / compose / publish:**
- `ingest_service.py` - runs the engine over all made shots (both teams) → tagged `LibraryClip` rows in `data/library.db` (dedup on game_id+action_id); takes a broadcast-profile param
- `compose_service.py` - query the library on any dimension (player/team/opponent/value/subtype/category/period/season/month/distance/date) → ordered clips → stitched reel + metadata sidecar
- `render_service.py` - concatenate clips into a reel
- `youtube_publisher.py` - one-time OAuth (`youtube_auth.py`) + `videos.insert`; auto title/description from the reel sidecar

**Parked** (kept for future non-scoring events, NOT in the current path): `clock_ocr_service.py`, `event_resolver_service.py` (clock-OCR pipeline), `timeline_service.py` (legacy formula).

**Utilities** (`backend/app/utils/`): `constants.py` (all magic numbers), `paths.py` (`sanitize_player_name()`), `ffmpeg.py` (`cut_clip`/`get_video_duration`/`concatenate_clips`), `scorebug_regions.py` (per-broadcast scorebug pixel regions; `espn` matches the test game).

**Data layout:**
- `backend/data/uploads/{game_id}/` - uploaded full game video
- `backend/data/outputs/{game_id}/clips/` - individual moment clips by player
- `backend/data/mock/` - mock play-by-play JSON fallback

**Databases (SQLite via SQLAlchemy):**
- `data/library.db` — the durable **clip library** (`library_clips` table), written by ingest, queried by compose. The product's source of truth.
- `data/app.db` — the FastAPI app's tables (games, moments, clips); used by `/process` and the older per-game flow. Auth tables exist but are unused.

## Hard Rules

- Never commit MP4/video files or anything under `backend/data/`. Never commit `backend/secrets/` (OAuth client + tokens).
- Buckets (made shots) only for now — no non-scoring stats yet.
- Broadcast is a per-game profile (`scorebug_regions.py`) — never hardcode one broadcast.
- The clip engine is sealed — downstream (compose/publish) depends on "a tagged clip in the library", not on detection internals.
- All magic numbers go in `constants.py`; all file paths through `paths.py`.
- All tests must pass before work is marked complete. Test fixtures use `conftest.py` shared `mock_events` and `db` fixtures.

## Current State

The proven approach is the **Phase 5A anchor chain**: for each scoring play in game order, scan a narrow video window (positioned from the previous confirmed play + the NBA clock gap) and confirm the timestamp by finding where the scorebug score flips `score_before → score_after`. A full-game run validated it at ~92% timestamping (34/37); see `docs/phases/first_run.md` for the clip-by-clip post-mortem. Its only problems were **speed** (Claude `watch.py` confirmed every play, ~2 min each) and a **fixed 7s/1s clip window** that mis-fit 8 plays.

**Phase 6 (revised) is implemented** — `docs/phases/phase-6-implementation-plan.md`. The anchor chain (`refinement_service.py`) now scans **forward** from the last confirmed play and confirms each timestamp by **score signature**: a cheap white-mask diff finds candidate score-box changes, then targeted OCR requires the value to transition `score_before → score_after` (`score_change_detector.py:find_score_transition`). This rejects free throws / other baskets / animation blips that a pixel-only flip detector caught wrongly, and it self-heals (a missed play doesn't advance the anchor, so it can't cascade). `watch.py` is a flagged-only fallback (default off). Clip windows are **dynamic and play-aware** (`clip_service.py`: net = flip − lag; transition/steal plays get extra lead). One-shot entry point: `POST /api/games/{id}/process` with `GET /status`. Full-game check: 37/37 plays confirmable vs the first-run labels (`scripts/checkpoint_full_run.py`).

Two earlier directions are **not** active: Phase 5B scorebug OCR/template matching (abandoned, 0/37 — wrong target) and the Phase 5C clock-OCR pass (`clock_ocr_service` + `event_resolver_service`) which is **parked as redundant** with the anchor chain for scoring plays — kept only for future non-scoring events (blocks/steals/assists). Validation harness: `backend/scripts/validate_score_detector_v2.py`.

**Product direction** (`docs/STRATEGY.md` is canonical): a single-operator **CLI tool, no web frontend, no auth**. Each game is ingested **once** into a tagged **clip library** (all made shots, both teams); reels are composed by **query** ("AD all 3s this season"), nudge-reviewed, and uploaded to **YouTube**. The clip engine is **sealed**; **broadcast is a per-game profile**.

**Track A is built and validated end-to-end on the demo game** — ingest (`ingest_service`) → library (`library_clip`) → compose (`compose_service`) → review (`nudge_clip`) → publish (`youtube_publisher`). All 10 Lakers per-player reels were uploaded to YouTube in one batch run (`make_player_reels.py` → `publish_player_reels.py`). Step-by-step usage is in `docs/USAGE.md`.

**Track B (broadcast generalization) is proven** — auto-calibration (`autocalibrate_service.auto_calibrate`) locates the scoreboard on an unseen broadcast purely from the API score sequence. Validated on a **second broadcast** (the Hawks feed, Luka 73-pt game `0022300634`): it placed both score boxes + clock and assigned home/away with nothing hardcoded. Wired into ingest: `ingest_game.py <id> <video> auto`. `NBAService.find_game_id(team, date)` (+ `find_game_id.py`) identifies an untitled game so any download/capture can be ingested.

**Current state / handoff notes:**
- Library `data/library.db`: demo game (`0052000121`, LAL clips currently **10s** via `extend_clips.py`) and the Luka game (`0022300634`, ingested via `auto`).
- Helper scripts beyond the core CLI: `find_game_id.py`, `make_player_reels.py` (one reel per player), `extend_clips.py` (lengthen clips), `publish_player_reels.py` (batch upload, video/Short by duration), `autocalibrate_poc.py`/`test_calib_luka.py`/`debug_calib_luka.py` (calibration diagnostics).
- **Open thread — vertical Shorts.** `--vertical` (compose/make_player_reels) converts reels to 9:16 via `ffmpeg.to_vertical`, currently a **static center-crop**. It fills the frame but the ball drifts out on wing plays — **not good enough**. The planned fix is **dynamic reframing (auto-pan to follow the action)**; researching approaches before building (do NOT ship another quick crop hack). The earlier letterbox version was rejected too.
- Test uploads to YouTube exist (Lakers per-player reels + several Shorts attempts, unlisted); the quota cap turned out higher than the documented ~6/day (a full 10-reel batch uploaded fine).
- Work is on branch **`phase-6-signature-detection`** (not merged to main); GitHub remote renamed to `aidos-player-highlights` (local origin still uses the old URL via redirect).

See `docs/PHASES.md` and `docs/STRATEGY.md`.
