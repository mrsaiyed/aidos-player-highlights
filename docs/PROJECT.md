# NBA Highlight MVP — Project Document

## North Star (Long Term Vision)

For any NBA team, for any player, for any time period:
generate separate highlight reels by play type.

Reel types:
  Buckets      — all made shots
  3-pointers   — three pointers only
  Dunks        — dunks only
  Layups       — layups only
  Assists      — all assists
  Blocks       — all blocks
  Steals       — all steals
  Misses       — missed shots (analytics)
  Custom       — any combination the user defines

Time period scope:
  Single game
  Week
  Month
  Season
  Career

Example use cases:
  "LeBron all 3s this season"
  "AD all dunks this month"
  "Curry all assists from last night"
  "Full Lakers buckets reel from last night"
  "Steph all misses Q4 this season" (analytics)

Pipeline supports this today because:
  event_type stored on every moment (made_shot, block, steal)
  event_subtype stored on every moment (three_pointer, dunk, layup)
  player_name and team stored on every moment
  game_id stored on every moment
  Filtering happens at API layer — no pipeline changes needed

What needs to be built for full vision:
  Multi-game processing (loop over game IDs)
  Season-long data storage
  User-defined filter combinations in frontend
  YouTube upload per reel
  Cloud storage per user account

## MVP North Star
Local pipeline: NBA game ID + uploaded video
→ team selector + player selector
→ player-specific highlight clips → view per player in browser.
No YouTube upload. No cloud storage. No OAuth. NBA only.
MVP scope: one game, one team, buckets only.
All other reel types and time periods are post-MVP.
Architecture already supports them — just needs frontend filters and multi-game processing.

## How It Works

### In plain English (no tech knowledge needed)

You give it a full-game video and the game's ID. It gives back a folder of short highlight
clips for each player — every basket they made — and stitches them into one reel per player.

The hard part it solves: the video has no chapter markers, and the game clock doesn't match
the video time (the video includes timeouts, free throws, and commercials — dead time the game
clock ignores). So it does what a person would. It pulls the official NBA play-by-play (the
"answer key": who scored and the running score, in order), then watches the scoreboard in the
corner of the video. For each basket it waits for the score to tick up, reads the new number,
and checks it against the answer key. When the number matches, that's the exact moment of the
basket. It snips 5 seconds before the ball goes in and 3 after, files it under the player's
name, and moves on — picking up where it left off so it never re-watches the whole game. At the
end, each player's clips are joined into one reel.

### Technically

**What runs it:** a Python backend (FastAPI app + standalone scripts), Python 3.12, deps managed
by `uv` in a virtualenv (`backend/.venv`). It leans on a few engines:
- **FFmpeg / ffprobe** — extracts frames and cuts/joins clips (the video workhorse).
- **OpenCV (cv2)** — crops the scoreboard area and compares frames (white-digit masking) to spot a score change.
- **EasyOCR (PyTorch under the hood)** — reads the actual score/clock digits from the crop.
- **nba_api** — pulls the official play-by-play from the NBA stats API.
- **SQLAlchemy + SQLite** — stores games, plays (moments), and clips.

**The pipeline, file by file** (`backend/app/`):
1. `services/nba_service.py` — fetches play-by-play (`playbyplayv3`); builds each play's score-before/score-after (the *signature*).
2. `services/moment_service.py` — filters to the plays you want (e.g. all made shots); one `Moment` per basket.
3. `services/score_change_detector.py` — the core. Scans video frames forward; OpenCV finds candidate score changes; EasyOCR confirms the new value matches the expected score. Returns the exact video second.
4. `services/refinement_service.py` — the "anchor chain": walks every play in game order, calling the detector forward from the last confirmed play; records timestamp + confidence; self-heals on a miss.
5. `services/clip_service.py` — turns a confirmed second into clip bounds (net = flip − 3s; 5s before, 3s after) and calls FFmpeg.
6. `services/render_service.py` — joins each player's clips into one reel.
7. `utils/scorebug_regions.py` (clock/score box pixel coordinates per broadcast), `utils/constants.py` (tunable numbers), `utils/ffmpeg.py` + `utils/paths.py` (FFmpeg wrappers, file locations).
8. `api/clips.py` — `POST /process` (runs the whole pipeline as a background task) and `GET /status`.

**A successful run:**
1. Input: full-game MP4 + NBA game ID.
2. Fetch play-by-play → ordered baskets with score signatures.
3. Filter to the target team/players' made shots.
4. For each basket in order: scan forward from the last confirmed basket; OpenCV spots the score-box change; EasyOCR confirms it changed to the expected score → that frame is the basket's real video time. Confirmed timestamps re-anchor the search, so it stays fast and drift never accumulates.
5. Cut an 8-second clip around each confirmed time with FFmpeg; file per player.
6. Join each player's clips into a reel.
7. Output: per-player highlight reels. On the validated game (ESPN Play-In, `0052000121`) this confirmed **37/37** baskets and cut correctly-timed clips.

**Important caveat:** the scoreboard locations and digit colors in `scorebug_regions.py` are
calibrated to **one** broadcast (the ESPN Play-In game). A different broadcast needs the
scoreboard re-located first — that's the next piece of work (auto-calibration using the NBA API
score sequence as a reference to find the clock/score boxes on any video).

**Hackathon MVP Frontend (Phase 7):**
- Upload full game video + enter NBA game ID
- Choose team (LAL or GSW from the upload)
- Select players to clip (multi-select or "Full team — all scorers")
- Trigger pipeline (fetch moments → refine moments → generate clips)
- View generated clips per player in the browser
- No approve/reject flow in hackathon MVP — just view and download

## The Game We Are Using
- Teams: Golden State Warriors vs Los Angeles Lakers
- Date: May 19, 2021
- Context: Western Conference Play-In Tournament
- Result: Lakers win 103-100 (LeBron go-ahead 3 with 58s left)
- NBA Game ID: 0052000121

## Hard Rules (Never Break These)
- Never commit MP4 or video files to Git
- No YouTube upload in MVP
- No cloud storage in MVP
- No real OAuth in MVP (simple bcrypt login only)
- NBA only for now
- FFmpeg handles all video processing
- All file paths go through backend/app/utils/paths.py
- All pipeline results stored in SQLite

## Tech Stack
- Backend: FastAPI + Python 3.12
- Database: SQLite (via SQLAlchemy)
- Video processing: FFmpeg
- NBA data: nba_api library + mock JSON fallback
- Frontend: Next.js
- Auth: bcrypt + session token (cookie-based, simple)
- Environment: GitHub Codespaces
- AI coding: opencode + DeepSeek V4 Pro

## Current Phase
Phase 6 (revised): Fast Anchor Chain — see [phases/phase-6-revised-plan.md](phases/phase-6-revised-plan.md).
Keep the proven 5A anchor chain (validated ~92% timestamping, see [phases/first_run.md](phases/first_run.md))
but swap the per-play claude-video confirmation for the deterministic score-flip detector
(`score_change_detector.py`), demote `watch.py` to flagged-only fallback, and add dynamic
play-aware clip windows. Phase 5B (scorebug OCR/template) is abandoned; Phase 5C clock-OCR is
parked as redundant for scoring plays (kept for non-scoring events post-MVP).
Phase 1 auth is built; MVP demo auth strategy still needs a final decision.

## What Is Working
- FastAPI backend serving on port 8000
- /health endpoint returns status + game_id
- SQLite database with User and Game tables (auto-created on startup)
- Auth: register, login (JWT in httponly cookie), logout, me
- Games API: create, list, get, upload video
- NBA play-by-play fetch with mock fallback
- Moment extraction with importance scoring (score_before, score_after stored on each moment)
- moments table in SQLite with refinement_method and status columns
- Timeline mapping converts game clock to video timestamp (formula — drifts; replaced by anchor chain)
- FFmpeg clip cutting working (8s clips: 7s pre-roll, 1s post-roll)
- Clip records stored in SQLite with file paths
- RefinementService built with sequential anchor chain logic
- POST /api/games/{id}/refine-moments endpoint (BackgroundTask)
- Q1 hard cap removed — clips now generated for all 4 quarters
- Baseline full-game run completed for LAL scoring plays (37 clips generated)
- claude-video watch + anchor chain approach validated for correctness, but currently too slow for MVP UX

## What Is Blocked
- Scorebug scanner prototype exists but needs validation on game 0052000121 after HSV white-mask fix — see [phase-5b-hsv-mask-fix.md](phases/phase-5b-hsv-mask-fix.md)
- API/UX alignment gaps remain for MVP:
  - Team/both-team selection support end-to-end
  - Player/team filtering behavior on list endpoints
  - Unified process endpoint and status model

## Key Decisions Made
- Manual quarter timestamps for MVP, auto-detection added later
- Single sanitize_player_name function in paths.py used everywhere
- Static files served by FastAPI at /outputs for video preview
- Background tasks for pipeline so API does not time out
- Auth deprioritized — auth system built in Phase 1 but full confirmation deferred until frontend is ready in Phase 7. Core logic exists: register, login, logout, me endpoints all created. Confirmation blocked on PowerShell curl issues, not code issues.
- constants.py is the single source of truth for all pipeline numbers. If a number appears in more than one place it belongs in constants.py instead.
- conftest.py mock_events is the canonical test dataset. Any new test that needs play-by-play events uses this fixture.
- Timeline formula: elapsed = QUARTER_DURATION_SECONDS - clock_remaining, video_time = quarter_start + elapsed. Manual quarter timestamps for MVP; auto-detection in Phase 8.
- MAX_CLIPS_PER_PLAYER = 20 for current full-game reels.
- Switched from mock play-by-play to real NBA API data. Real Q1 data confirmed: 17 total events, 6 Lakers buckets. Real API uses PT format for clock — normalized in nba_service. real_play_by_play.json saved for offline/demo fallback.
- Two processing modes: buckets = all made shots, no filtering by type; highlights = dunks, threes, blocks, steals, clutch only. MVP uses buckets mode for all clip generation.
- **3-clip watch test (June 2026):** formula-only timeline unusable beyond early Q1 due to dead-ball drift. Confirmed that NBA API score_before/score_after + claude-video watch scan reliably finds exact video second within ±5s.
- **Self-correcting anchor chain (Phase 5A decision):** each confirmed video timestamp becomes the new search anchor for the next play. No manual Q2/Q3/Q4 timestamps needed. Q1 hard cap removed. Phase 8 auto quarter detection superseded by this approach.
- CLIP_PRE_ROLL_SECONDS = 7, CLIP_POST_ROLL_SECONDS = 1, CLIP_TOTAL_SECONDS = 8 (calibrated June 7 2026 from Q1 agent run — shot scores at exactly second 7 of the 8s clip, crowd reaction visible in post-roll second). **Superseded by Phase 6 revised:** the fixed window mis-fit 8/37 clips in the full-game review, so windowing moves to dynamic, play-aware bounds anchored on the score flip (`[flip − 6s, flip + 2s]` default; extra lead for transition/steal plays). See [phases/phase-6-revised-plan.md](phases/phase-6-revised-plan.md).
- score_before and score_after will be stored as strings on Moment model (e.g. "LAL 4 GSW 15") and sourced from scoreHome/scoreAway fields already present in the raw NBA API response.
- refinement_method stored on each Moment: "watch_confirmed" | "interpolated" | "formula" to track data quality.
- MVP speed decision (June 2026): move primary timestamping to deterministic scorebug scanning (OCR/template) once implemented; keep claude-video watch for fallback/validation of ambiguous timestamps.

## Documentation Rules
These docs are updated after every phase and every key decision.
No phase is marked complete without passing its acceptance criteria.
If a phase is deferred or partially complete it is marked as such.
ROADMAP.html status is updated in sync with PHASES.md.
- Unit tests written alongside every service
- Run pytest before every git push
- All tests must pass before a phase is marked complete
- Test files live in backend/tests/
- Constants live in backend/app/utils/constants.py

## Git Rules
- Push to main after every completed phase
- Always run git check-ignore on video files before committing
- Never commit files from backend/data/uploads/ or backend/data/outputs/
- Commit message format: "Phase N complete - one line summary"
- If a phase is partial, commit with: "Phase N partial - what is done"
- The video full_game.mp4 must never appear in git history
