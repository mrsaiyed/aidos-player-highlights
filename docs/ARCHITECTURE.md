# Architecture

## Pipeline Flow
### Current Implemented Flow (as of June 2026)
User uploads video + enters NBA game ID
→ backend fetches NBA play-by-play via nba_api
→ moment service extracts made shots; stores score_before/score_after
→ refinement service runs sequential anchor chain:
    for each scoring play: watch.py scans a window, then returns FOUND/NOT_FOUND
→ FFmpeg cuts fixed-window clips around stored timestamps
→ clips grouped by player in output folders

### Target MVP Flow (planned, not implemented yet)
User uploads video + enters NBA game ID + selects one team or both + selects players/all scorers
→ backend fetches NBA play-by-play and builds expected scoring events in game order
→ scorebug scanner pass (OCR/template matching) runs once over the game to build score/clock timeline
→ mapper aligns NBA scoring events to observed score changes, writing timestamp + confidence
→ only low-confidence events are sent to claude-video watch fallback
→ frontend opens rapid review on timestamped segments first
→ FFmpeg rendering/export runs after review (or on-demand)

## Pipeline Services

| Service | File | Responsibility |
|---------|------|----------------|
| NBAService | `nba_service.py` | Fetch play-by-play from nba_api with mock JSON fallback; populate score_before/score_after |
| MomentService | `moment_service.py` | Filter highlight-worthy events and assign importance scores |
| TimelineService | `timeline_service.py` | Legacy formula mapper (kept as fallback only; drifts in full games) |
| RefinementService | `refinement_service.py` | Current baseline: sequential watch.py anchor-chain timestamping |
| ScoreboardScanService | `scoreboard_scan_service.py` | Deterministic scorebug scan (template/OCR), one pass per game — see [phase-5b-hsv-mask-fix.md](phases/phase-5b-hsv-mask-fix.md) |
| EventAlignmentService | `TBD` | Planned: map NBA score transitions to video timeline + confidence labels |
| ClipService | `clip_service.py` | Cut clips around timestamps; move to post-review export path for MVP speed |

### Role of Claude-video Watch

- Keep `watch.py` as fallback for ambiguous/low-confidence mappings.
- Use it for calibration/debug, not for every scoring play.
- This reduces end-to-end latency and keeps AI in the loop only when deterministic parsing is uncertain.

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
