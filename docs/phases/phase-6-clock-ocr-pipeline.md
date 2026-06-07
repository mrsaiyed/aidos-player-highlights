# Phase 6: Clock OCR Pipeline

## What We're Building

A single-pass OCR scanner that reads the **game clock** from the scorebug in the video, builds a lookup table mapping video seconds to game clock times, then joins that table with NBA API play-by-play data to resolve exact video timestamps for every scoring play.

## Why This Works

The NBA API already tells us everything about each scoring play: who scored, what the score was before and after, and the **game clock** when it happened (e.g., "Q2 5:32"). The only missing piece is: what video second corresponds to Q2 5:32?

If we can read the game clock from the scorebug at regular intervals, we get a mapping like:

```
video_sec=0     -> Q1 12:00
video_sec=2     -> Q1 11:58
video_sec=45    -> Q1 11:15
...
video_sec=1423  -> Q3 8:14
```

Then for any NBA event at "Q3 8:14", we look up that clock time in our table and get video second 1423. Interpolate between nearest readings for sub-second accuracy. Cut clip. Done.

We do NOT need to OCR the score. The NBA API already has the score. We just need the clock.

## What Went Wrong Earlier

### Attempt 1: Formula mapping (Phase 3)
A formula (`video_time = quarter_start + elapsed_in_period`) assumed linear time. This works for the first few minutes of Q1 but drifts badly because the video includes dead time (timeouts, free throws, commercials, halftime) that the game clock doesn't. By Q4, drift exceeded 25+ minutes.

### Attempt 2: Claude Watch anchor chain (Phase 5A)
Used the claude-video `/watch` skill to visually scan each play's search window and confirm timestamps by watching the scoreboard change. This **worked correctly** (37/37 clips generated, ~70% frame-perfect) but took ~1h15m for one game because it called the AI video scanner once per scoring play. Too slow for MVP.

### Attempt 3: Scorebug OCR with template matching (Phase 5B)
Previous agents attempted digit template matching with HSV masking to read scores from the scorebug. This went off on tangents: building digit template libraries, complex HSV threshold configs, morphological operations. It got 0/37 matches on the test game's TNT scorebug. The fundamental error was trying to OCR the **score** (which we already have from the API) instead of the **clock**.

### Why clock-only OCR is simpler
- The clock is always in the same position within the scorebug
- Clock digits are larger and higher-contrast than score digits
- We only need to read MM:SS (4-5 digits), not team names + scores
- Failed reads are easy to detect: if the clock jumps backwards impossibly or reads gibberish, just skip that frame
- We don't need 100% accuracy — even 60% of frames reading correctly gives us enough data points to interpolate the rest

## Pipeline Design

### Step 1: Frame Sampling
Extract one frame every 1-2 seconds from the full game video using FFmpeg. For an 88-minute game, that's ~2,600-5,300 frames.

### Step 2: Scorebug Region Crop
Crop the known scorebug region from each frame. The scorebug position is consistent within a broadcast (top-left for TNT, top-center for ESPN, etc.). One-time config per broadcast network.

### Step 3: Clock OCR
Run Tesseract (or OpenCV digit recognition) on the cropped clock region only. Output: `(period, minutes, seconds)` or `FAILED`.

### Step 4: Sanity Filtering
Discard readings where:
- OCR confidence is below threshold
- Clock jumps forward by more than a few seconds between consecutive frames (would mean time ran backwards)
- Clock jumps backward by more than 30 seconds between consecutive frames (would mean a huge gap was somehow missed)
- Period number is impossible (e.g., Q7)

Consecutive `FAILED` readings = commercial break / halftime / no scorebug. Mark these as gaps.

### Step 5: Build Clock-to-Video Table
Store clean readings as `(video_second, period, clock_remaining_seconds)`. This is the lookup table.

### Step 6: Event Resolution
For each NBA API scoring event:
1. Find its `(period, clock_time)` in the lookup table
2. If exact match exists, use it
3. If not, interpolate between the two nearest readings in the same period
4. Assign confidence: HIGH if readings are within 5 seconds of the event, MEDIUM if within 30 seconds, LOW if nearest reading is 30+ seconds away

### Step 7: Fallback (Claude Watch)
Only for LOW confidence events (maybe 2-5 per game, typically plays near commercial breaks where OCR had gaps). Send a 30-second window to Claude Watch to confirm. This replaces calling Watch 37 times with calling it 2-3 times.

### Step 8: Clip Cutting
Use existing `clip_service.py` with resolved timestamps. 7s pre-roll, 1s post-roll.

## Implementation Plan

### Files to create:
- `backend/app/services/clock_ocr_service.py` — frame sampling, scorebug crop, clock OCR, sanity filtering
- `backend/app/services/event_resolver_service.py` — joins clock table with NBA events, assigns confidence, handles fallback
- `backend/app/utils/scorebug_regions.py` — scorebug position configs per broadcast network
- `backend/tests/test_clock_ocr_service.py`
- `backend/tests/test_event_resolver_service.py`

### Files to modify:
- `backend/app/utils/constants.py` — add OCR-related constants
- `backend/app/api/games.py` — add endpoint to trigger the new pipeline

### Files to remove (dead-end Phase 5B experiments):
- `backend/app/services/scoreboard_scan_service.py` (doesn't exist yet, but referenced in docs — don't create it)
- Any digit template / HSV mask code if it exists

### Dependencies:
- `pytesseract` — already in pyproject.toml
- `opencv-python-headless` — already in pyproject.toml
- `ffmpeg` — already available for frame extraction
