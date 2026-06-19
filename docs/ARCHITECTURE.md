# Architecture

## Pipeline Flow

### Proven Baseline (Phase 5A — validated, slow)
User uploads video + enters NBA game ID
→ backend fetches NBA play-by-play via nba_api
→ moment service extracts made shots; stores score_before/score_after
→ refinement service runs sequential anchor chain:
    for each scoring play: `watch.py` (Claude) scans a window, returns FOUND/NOT_FOUND
→ FFmpeg cuts fixed-window clips around stored timestamps
→ clips grouped by player in output folders

This worked: 37/37 clips, ~92% timestamping (34/37). Too slow (~2 min/play of Claude)
and the fixed 7s/1s window mis-fit 8 plays. See [phases/first_run.md](phases/first_run.md).

### Active MVP Flow (Phase 6 revised — see [phases/phase-6-revised-plan.md](phases/phase-6-revised-plan.md))
User uploads video + enters NBA game ID + selects team + selects players / full team
→ backend fetches NBA play-by-play, builds expected scoring events in game order
→ refinement service runs the same sequential anchor chain, but the per-play confirmation
   is the **deterministic score-flip detector** (`score_change_detector.py`, ~0.7s/play),
   not a Claude call — it finds the frame where the score region flips score_before→after
→ each play gets a confidence label: HIGH (clean flip near anchor) or LOW (no flip / disagreement)
→ LOW-confidence plays (~3/game) are flagged for review (demo default); Claude `watch.py`
   fallback on them is an optional later toggle
→ clip service cuts **dynamic, play-aware windows** (transition/steal plays get extra lead)
→ clips grouped by player; frontend opens review on flagged segments first

Key point: the per-play confirmation is the *codification of what the 5A agent did*
(read the score box, detect the change), so accuracy is preserved while removing the AI
cost. The clock-OCR pass is **not** in this path — the anchor chain already positions
each play from the previous confirmation.

## Pipeline Services

| Service | File | Responsibility |
|---------|------|----------------|
| NBAService | `nba_service.py` | Fetch play-by-play from nba_api with mock JSON fallback; populate score_before/score_after |
| MomentService | `moment_service.py` | Filter highlight-worthy events and assign importance scores |
| TimelineService | `timeline_service.py` | Legacy formula mapper (kept as fallback only; drifts in full games) |
| RefinementService | `refinement_service.py` | Sequential anchor chain. Per-play confirmation is being swapped from `watch.py` (Claude) to the deterministic flip detector; `watch.py` becomes flagged-only fallback |
| ScoreChangeDetector | `score_change_detector.py` | **Primary confirmation.** White-pixel mask diff finds the exact frame the score region flips score_before→after (~0.7s/play). The codified version of what the 5A agent did |
| ClipService | `clip_service.py` | Cut clips around confirmed timestamps; dynamic play-aware windows (Phase 6 revised) |
| ClockOCRService / EventResolverService | `clock_ocr_service.py`, `event_resolver_service.py` | **Parked.** Clock-OCR pass — redundant with the anchor chain for scoring plays. Keep for non-scoring events (blocks/steals/assists) post-MVP |

### Role of Claude-video Watch

- `watch.py` is the **oracle/fallback**, not the per-play workhorse — used only on
  LOW-confidence plays the flip detector can't confirm (~3/game).
- Demo default is **flag-only** (surface in the review UI); auto-firing watch on flagged
  plays is a later toggle.
- It was also the source of the 5A gold-label run that the deterministic detector is
  validated against.

### FFmpeg Utility (`ffmpeg.py`)

| Function | Responsibility |
|----------|----------------|
| `cut_clip` | Cut a segment from full game video using libx264 + aac |
| `get_video_duration` | Probe video length via ffprobe (ffmpeg fallback on Windows) |
| `concatenate_clips` | Concatenate clips via FFmpeg concat demuxer (used in Phase 5) |

All file paths are resolved through `paths.py` — never hardcoded.

### Timeline Formula

```
clock_remaining = parse_game_clock(game_clock)       # "MM:SS" → seconds remaining
elapsed_in_period = QUARTER_DURATION_SECONDS - clock_remaining
quarter_start = get_quarter_start(period, q1..q4)
video_time = max(0.0, quarter_start + elapsed_in_period)
```

**Quarter start lookup:**
- Period 1–4 → q1_start through q4_start
- Period 5+ → q4_start + QUARTER_DURATION_SECONDS + (period - 5) × OVERTIME_DURATION_SECONDS

**Example:** Q4 clock 0:58 with q4_start=6900 → elapsed=662s → video_time=7562.0

## Folder Structure
backend/data/uploads/{game_id}/          ← uploaded full game video
backend/data/outputs/{game_id}/clips/    ← individual moment clips by player
backend/data/outputs/{game_id}/rendered/ ← one compiled video per player
backend/data/outputs/{game_id}/approved/ ← approved final videos
backend/data/mock/                       ← mock play-by-play JSON fallback

## DB Schema

Tables: users, games, moments, clips, rendered_videos

### clips
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | Primary key |
| game_id | Integer | FK → games.id, indexed |
| moment_id | Integer | FK → moments.id |
| player_name | String | Not null |
| start_seconds | Float | Clip start in full video |
| end_seconds | Float | Clip end in full video |
| duration_seconds | Float | end - start |
| file_path | String | Nullable; absolute path to MP4 |
| status | String | pending, generated, failed |
| error_message | String | Nullable |
| created_at | DateTime | UTC default |

## API Endpoints (to be defined in Phase 1)
See phase-1-backend.md when complete.

## Testing Architecture

All tests live in backend/tests/
Run with: cd backend && pytest tests/ -v

Test files:
- conftest.py — shared fixtures: test DB, mock_events dataset
- test_moment_service.py — moment extraction and scoring logic
- test_timeline_service.py — game clock parsing and video time calculation
- test_clip_service.py — clip bounds calculation and top-moment selection
- test_render_service.py — to be added in Phase 5

Rules:
- Every service gets a corresponding test file
- All tests must pass before phase is marked complete
- All tests must pass before git push
- Use the shared mock_events fixture from conftest.py
- Use the shared db fixture for any database operations

## Constants

All magic numbers live in backend/app/utils/constants.py
No hardcoded numbers anywhere else in the codebase.

Current constants:
- QUARTER_DURATION_SECONDS = 720 (12 minutes)
- CLIP_PRE_ROLL_SECONDS = 7 (shot lands at second 7 of 8s clip)
- CLIP_POST_ROLL_SECONDS = 1 (1s for crowd reaction after score updates)
- CLIP_TOTAL_SECONDS = 8
- SHORT_MAX_DURATION_SECONDS = 120
- MINIMUM_IMPORTANCE_SCORE = 70
- FRAME_SAMPLE_INTERVAL_SECONDS = 30
- NBA_QUARTERS = [1, 2, 3, 4]
- OVERTIME_DURATION_SECONDS = 300
- MAX_CLIPS_PER_PLAYER = 20 (raised for full-game reels)
- REFINEMENT_WINDOW_SECONDS = 45 (watch scan window per play)
- QUARTER_BREAK_SEARCH_SECONDS = 300 (wider window at quarter transitions)
- DEGRADED_WINDOW_MULTIPLIER = 3 (expand 3× after NOT_FOUND)
- DEAD_BALL_RATIO = 1.6 (broadcast time / game time; derived Q1: 1149s / 720s = 1.596)
