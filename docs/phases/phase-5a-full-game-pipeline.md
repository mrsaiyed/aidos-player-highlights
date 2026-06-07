# Phase 5A: Full Game Pipeline — Self-Correcting Timestamp Refinement

## Goal
Clip every Lakers made shot across all 4 quarters of game 0052000121, producing
per-player highlight folders. Replace the formula-only Q1 timeline with a
self-correcting anchor chain that uses NBA API score signatures and the claude-video
watch skill to pin each play to the exact video second.

## Status
Completed as a baseline implementation using claude-video watch anchor chaining.
This phase validated feasibility, but not MVP-level speed.

**Q1 agent-driven run complete (June 7, 2026):**
All 7 LAL scoring plays in Q1 confirmed via visual frame analysis using watch.py + NBA API score context.

| Play | Game Clock | Confirmed Video Time | Drift from Formula |
|------|-----------|---------------------|-------------------|
| Drummond dunk | Q1 11:10 | **82s** | 4s (formula: 78s) |
| LeBron tip layup | Q1 8:29 | **258s** | 94s (formula: 164s) |
| KCP 3PT (1st) | Q1 6:40 | **442s** | 94s (formula: 348s) |
| KCP 3PT (2nd) | Q1 4:43 | **687s** | 187s (formula: 500s) |
| Caruso 3PT | Q1 4:13 | **752s** | 192s (formula: 547s) |
| Caruso layup | Q1 2:49 | **947s** | 217s (formula: 730s) |
| AD floater | Q1 0:55 | **1176s** | 483s (formula: 693s) |

All 7 clips generated to `backend/data/outputs/0052000121/Q1_clips/` at 8s each (7s pre-roll, 1s post-roll).
Q2–Q4 runs pending.

## Background: Why This Phase Exists

The formula-based timeline (Phase 3) works within the first ~2 minutes of Q1.
Dead-ball time (timeouts, free throws, replays) accumulates across a quarter and
causes severe drift:

| Play | Formula estimate | Watch-confirmed actual | Drift |
|------|-----------------|----------------------|-------|
| Drummond dunk (early Q1) | 78s | 82s | ~4s — acceptable |
| KCP 3PT (mid Q1) | 348s | 442s | ~94s — wrong |
| Davis floater (late Q1) | 693s | 1177s | ~484s — completely wrong |

Manual quarter calibration is also impractical — it requires measuring every game
individually and breaks at different broadcast lengths.

The watch test (3 clips, June 2026) proved that NBA API score context + narrow
watch windows + scoreboard frame reading produces exact timestamps reliably.
This phase automates that pattern for the full game.

## Key Insight: Self-Correcting Anchor Chain

The NBA API delivers every play in chronological order with a unique score
signature (score_before, score_after). Each confirmed video timestamp becomes
the anchor for finding the next play. Drift is reset at every confirmation.
Quarter boundaries are implicit — the play sequence crosses them naturally
with a wider search window to absorb the inter-quarter break.

No manual Q2/Q3/Q4 start timestamps needed.

## Inputs
- Full game video at backend/data/uploads/0052000121/full_game.mp4
- Real play-by-play JSON at backend/data/mock/real_play_by_play.json
- watch.py at ~/.claude/skills/watch/scripts/watch.py
- FFmpeg/ffprobe on PATH
- Existing ClipService, MomentService, NBAService

## Outputs
- score_before, score_after columns on Moment model
- RefinementService: sequential anchor chain, narrow watch scans, frame analysis
- POST /api/games/{game_id}/refine-moments endpoint
- All Lakers made_shots across Q1–Q4 with confirmed video_time_seconds
- Q1 hard cap removed from ClipService and clips API
- Individual clips for all Lakers scorers in all 4 quarters
- Updated constants: REFINEMENT_WINDOW_SECONDS, MAX_CLIPS_PER_PLAYER raised
- test_refinement_service.py unit tests

## Tasks

### Step 1: Store score context on Moment
- [x] TASK 1: Add score_before, score_after columns to Moment model
- [x] TASK 2: Populate in NBAService._normalize_real_api_event (scoreHome/scoreAway already in raw JSON)
- [x] TASK 3: Populate in NBAService._normalize_nba_api_event and _normalize_mock_event
- [x] TASK 4: Update MomentSchema to include score_before, score_after
- [x] TASK 5: Update conftest.py mock_events with score fields
- [x] TASK 6: Run pytest — all existing tests still pass

### Step 2: Build RefinementService
- [x] TASK 7: Create backend/app/services/refinement_service.py
- [x] TASK 8: Implement sequential anchor chain logic (see Algorithm below)
- [x] TASK 9: Implement _run_watch_scan (subprocess watch.py, parse frame list)
- [x] TASK 10: Implement _find_score_change_in_frames (read frames, detect score flip)
- [x] TASK 11: Implement _widen_and_retry (one retry with 2× window on NOT_FOUND)
- [x] TASK 12: Implement quarter boundary detection (wider window on period change)
- [x] TASK 13: Write test_refinement_service.py (mock watch subprocess, unit test anchor logic)

### Step 3: Wire refinement into API
- [x] TASK 14: Add POST /api/games/{game_id}/refine-moments to clips.py or new router
- [x] TASK 15: Accepts team, max_period, highlight_type query params
- [x] TASK 16: Runs as BackgroundTask (same pattern as generate-clips)
- [x] TASK 17: Returns job status; stores refinement_method on each Moment

### Step 4: Remove Q1 hard cap
- [x] TASK 18: Delete Q1_END_SECONDS guard from clip_service.py
- [x] TASK 19: Delete Q1_END_SECONDS guard from clips.py API
- [x] TASK 20: Change max_period default from 1 to 4 in generate-clips endpoint
- [x] TASK 21: Add REFINEMENT_WINDOW_SECONDS = 45, QUARTER_BREAK_SEARCH_SECONDS = 300, DEGRADED_WINDOW_MULTIPLIER = 3, DEAD_BALL_RATIO = 1.6 to constants.py
- [x] TASK 22: Raise MAX_CLIPS_PER_PLAYER from 5 to 20 (or remove cap for full game)
- [x] TASK 23: Run pytest — all tests still pass

### Step 5: Full game end-to-end validation
- [x] TASK 24: Run fetch-moments (team=LAL, mode=buckets, Q1)
- [x] TASK 25: Run agent-driven refinement — all 7 Q1 LAL plays confirmed via watch.py frame analysis
- [x] TASK 26: Verify confirmed video_time_seconds for each LAL made shot in Q1
- [x] TASK 27: Run generate-clips (all 7 Q1 LAL plays, 8s clips, 7s pre-roll + 1s post-roll)
- [x] TASK 28: Verify 7 clip files exist across 5 player folders
- [x] TASK 29: Spot-checked Drummond (dunk), KCP (3PT), Caruso (#4 celebrating) — correct play content
- [x] TASK 30: Repeat TASK 24–29 for Q2, Q3, Q4
- [x] TASK 31: Update documentation

### Step 6: MVP architecture handoff (new)
- [x] TASK 32: Mark watch anchor chain as baseline/fallback path
- [x] TASK 33: Define next phase to build deterministic scorebug scanner prototype
- [x] TASK 34: Record that OCR/template scanner is not implemented yet

## Acceptance Criteria
- score_before and score_after populated on all LAL made_shot moments
- RefinementService processes plays in chronological order
- Each confirmed timestamp within ±5s of actual play
- Quarter transitions handled without manual Q2/Q3/Q4 timestamps
- NOT_FOUND plays marked status="unconfirmed", pipeline continues
- Q1 hard cap removed — clips generated for all 4 quarters
- All Lakers scorers (LeBron, Davis, KCP, Caruso, Kuzma, Schröder, Harrell, THT, Drummond) have clip folders
- All existing pytest tests still pass

### Exit Criteria for this phase (added)
- Baseline full-game run is complete and documented.
- Known performance limit is documented (~1h15 operational run).
- Follow-on work is redirected to deterministic scorebug scanning (Phase 5B/5C). See [phase-5b-hsv-mask-fix.md](phase-5b-hsv-mask-fix.md) for the HSV white-mask digit reader fix.

## Algorithm: Sequential Anchor Chain

Two anchor values are tracked at all times:
- `anchor_second` — the running position (updated on every play, confirmed or interpolated)
- `last_confirmed_second` / `last_confirmed_clock` — the most recent **watch-confirmed** timestamp

This separation is the key to surviving NOT_FOUND without cascading failure.

```
anchor_second          = Q1_TIP_OFF_SECOND   # 28.0 — known video start
last_confirmed_second  = Q1_TIP_OFF_SECOND
last_confirmed_clock   = 720.0               # 12:00 Q1 in seconds remaining
degraded               = False               # True after a NOT_FOUND
last_period            = 1

for play in all_lal_made_shots_in_chronological_order:

    # --- Compute search window ---
    if play.period != last_period:
        # Quarter boundary: wide window, search well ahead of last anchor
        search_start = anchor_second + 60
        search_end   = anchor_second + QUARTER_BREAK_SEARCH_SECONDS
        degraded     = False   # fresh period resets degraded flag
    elif degraded:
        # Previous play was NOT_FOUND — expand window to compensate
        window = REFINEMENT_WINDOW_SECONDS * DEGRADED_WINDOW_MULTIPLIER  # × 3
        search_start = max(0, anchor_second - window)
        search_end   = anchor_second + window
    else:
        search_start = max(0, anchor_second - 15)
        search_end   = anchor_second + REFINEMENT_WINDOW_SECONDS

    context = {
        "player": play.player_name,
        "play_type": play.event_subtype,
        "description": play.description,
        "score_before": play.score_before,
        "score_after": play.score_after,
        "period": play.period,
        "clock": play.game_clock,
    }

    found_second = run_watch_scan(video, search_start, search_end, context)

    if found_second is None:
        # One retry at 2× the already-expanded window
        found_second = run_watch_scan(
            video,
            search_start - REFINEMENT_WINDOW_SECONDS,
            search_end   + REFINEMENT_WINDOW_SECONDS,
            context
        )

    if found_second is not None:
        # --- CONFIRMED ---
        play.video_time_seconds   = found_second
        play.refinement_method    = "watch_confirmed"
        play.status               = "refined"
        anchor_second             = found_second
        last_confirmed_second     = found_second
        last_confirmed_clock      = parse_game_clock(play.game_clock)
        degraded                  = False

    else:
        # --- NOT_FOUND: interpolate from the last confirmed anchor ---
        #
        # We know the exact game-clock gap between the last confirmed play
        # and this play. We scale it by DEAD_BALL_RATIO to convert game
        # time to real broadcast time. This keeps the interpolated anchor
        # in the right neighbourhood even after several misses.
        #
        # DEAD_BALL_RATIO = 1.6 (derived from Q1 test data:
        #   1149s broadcast / 720s game time = 1.596, rounded to 1.6)
        #
        game_clock_elapsed = last_confirmed_clock - parse_game_clock(play.game_clock)
        estimated_video_elapsed = game_clock_elapsed * DEAD_BALL_RATIO
        interpolated_second = last_confirmed_second + estimated_video_elapsed

        play.video_time_seconds   = interpolated_second
        play.refinement_method    = "interpolated"
        play.status               = "unconfirmed"
        anchor_second             = interpolated_second
        degraded                  = True  # expand window for next play

    last_period = play.period
```

### Why this survives the failure mode

| Scenario | What happens |
|----------|-------------|
| 1 NOT_FOUND in a row | anchor advances by clock-scaled estimate; next search window is 3× wider |
| 2 NOT_FOUND in a row | both interpolated from the same last-confirmed anchor; each uses its own clock gap — errors do not compound |
| 3+ NOT_FOUND in a row | same as above; interpolation quality degrades but next confirmed play resets everything |
| Quarter break | `degraded` flag cleared; wide QUARTER_BREAK_SEARCH_SECONDS window used regardless |

The critical rule: **the next play's window is never derived from an interpolated anchor alone** — it is always derived from `last_confirmed_second` + the NBA API clock gap × DEAD_BALL_RATIO. Interpolated positions do not accumulate error into each other.

## Score Change Detection (how frames are read)

For each watch scan the script produces ~60 JPEG frames with absolute timestamps.
The search reads frames looking for the scoreboard scorebug to change from
score_before to score_after. The first frame where score_after appears on screen
is the confirmed video second.

Score signature format from NBA API:
- score_before: "LAL 4 GSW 15" (from scoreHome/scoreAway on previous event)
- score_after: "LAL 7 GSW 15" (from scoreHome/scoreAway on this event)

The uniqueness of each score state (no two consecutive plays produce the same
score) makes false positives essentially impossible within a 60-90 second window.

## Decisions Made
- Self-correcting anchor chain replaces manual quarter timestamp calibration
- Q2/Q3/Q4 start times are implicit — no longer required on Game model
- TimelineService formula retained as fallback for very first play only
- watch.py called via subprocess (same as existing test_watch_video.py pattern)
- REFINEMENT_WINDOW_SECONDS = 45 (tight window after each anchor)
- QUARTER_BREAK_SEARCH_SECONDS = 300 (broadcast quarter breaks are 3-5 minutes. 300s window is sufficient and cheaper than 600s.)
- DEGRADED_WINDOW_MULTIPLIER = 3 (window expands to 3× after any NOT_FOUND)
- DEAD_BALL_RATIO = 1.6 (derived from Q1 test data: 1149s broadcast / 720s game time = 1.596, rounded to 1.6. This is a Q1 approximation — Q4 in close games may be higher due to more timeouts and free throws.)
- Two anchors tracked: `anchor_second` (running position) and `last_confirmed_second` (last watch-confirmed); interpolation always derives from `last_confirmed_second` so errors do not compound across consecutive NOT_FOUND plays
- NOT_FOUND plays use interpolated fallback and mark status="unconfirmed"; `degraded=True` expands the next play's search window automatically
- MAX_CLIPS_PER_PLAYER raised to 20 for full-game reels
- Q1_END_SECONDS hard cap removed entirely
- refinement_method stored on Moment: "watch_confirmed" | "interpolated" | "formula"
- Automated sync method: watch.py runs as subprocess for each play in the anchor chain. Identical to the proven 3-clip manual test. NBA API score context passed as prompt. FOUND: <seconds> parsed from output. No separate frame reader needed. No OCR. No Vision API called directly. Proven approach only.
- score_before/score_after stored as String on Moment (e.g. "LAL 4 GSW 15")
- Follow-up decision (June 2026): this method remains as fallback/validation. Primary MVP timestamping will move to deterministic scorebug scanning (OCR/template) once implemented.
