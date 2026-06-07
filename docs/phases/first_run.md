# First Full-Game Run — Post-Mortem & Clip Analysis

**Game:** LAL vs GSW — NBA Play-In Tournament, 2020-21 Season  
**Game ID:** 0052000121  
**Run Date:** June 7, 2026  
**Total Moments:** 37 LAL scoring plays (Q1–Q4)  
**Result:** 37/37 clips generated

> Note (June 2026 roadmap update): this document mixes baseline run time and debugging from multiple sessions.  
> The practical end-to-end run after fixes was approximately **1h15m**, which is still too slow for the MVP rapid-review target.

---

## The Simple Version 

Imagine you want to make a highlight reel of every basket the Lakers scored in an 88-minute game. You have:

- The full game video on your computer
- An official NBA stats sheet that tells you the exact game clock when each basket happened (like "LeBron scored at 8:29 left in Q1")

The problem is the NBA clock and the video time don't match. The NBA clock only counts **live game time**. The video also records all the **dead time** — timeouts, free throw pauses, halftime, players walking back, TV commercials cut back in. So a play at "8:29 left in Q1" might actually appear at minute 4:18 in the video, not at minute 1:31 (which is where the math would put it if you ignored dead time).

**What we did:** We looked at video frames one by one, found each basket by watching the scoreboard change, and wrote down the exact video second it happened. Then we told FFmpeg (a video-cutting tool) to cut 7 seconds before and 1 second after each basket. We repeated this for all 37 baskets across all 4 quarters.

**What worked great:** Finding each play using scoreboard scores as proof ("if the scoreboard goes from LAL 26 to LAL 28, we found Kuzma's shot").  
**What was hard:** LeBron's ankle injury in Q4 froze the game clock at 2:07 for almost 4 real minutes. The video kept rolling but the clock didn't move — this made the Q4 late-game plays much harder to estimate.

---

## How It Actually Worked (Technical)

### Step 1: Data Source — NBA Play-By-Play API

We pulled all LAL scoring plays from `nba_api.stats.endpoints.playbyplayv3` (the v2 endpoint was deprecated mid-session and returned empty data, causing a fallback to a mock Q1-only JSON file — caught and fixed).

Each play record contains:

- `player_name`, `period`, `game_clock` (e.g. `"11:10"`)
- `score_before` (e.g. `"LAL 0 GSW 2"`) and `score_after` (e.g. `"LAL 2 GSW 2"`)
- `shot_type` (2PT/3PT) and `action_type` (DUNK, JUMP SHOT, etc.)

This gave us **37 LAL made shots** stored as `Moment` records in SQLite (`app.db`).

### Step 2: The Timestamp Problem

A naive formula would say: if a play is at game clock `MM:SS` in Q2, compute:

```
video_time ≈ Q1_duration + Q1Q2_break + (Q2_duration - MM:SS_elapsed)
```

But this breaks immediately because each quarter has:

- ~2 timeouts per team = 3–5 min of dead time
- Free throw pauses (~15s each)
- Out-of-bounds stoppages
- Variable halftime (NBA = ~15–20 min broadcast time)

By Q4, the cumulative drift from a naive formula exceeded **25+ minutes**.

**Our constant:** `DEAD_BALL_RATIO = 1.6` — meaning for every 1 second of NBA game clock elapsed, approximately 1.6 seconds of video elapses. This was calibrated from Q1 but used only as a search window estimate, not as the truth.

### Step 3: The Watch Skill — Frame Extraction

`~/.claude/skills/watch/scripts/watch.py` was invoked for every play. It uses FFmpeg to extract frames from a time window of the video at 1–2 fps, then presents them as images for visual inspection.

**Example invocation:**

```powershell
$env:PYTHONIOENCODING = "utf-8"
python watch.py full_game.mp4 --start 30:00 --end 32:00 --fps 2 --resolution 1024 --max-frames 240 --no-whisper
```

`--no-whisper` skips audio transcription (unneeded, saves time).  
`--fps 2` gives 2 frames per second — enough to catch scoreboard changes without too many images.  
The working directory temp folder (`watch-XXXXXXXX`) contained numbered JPEG frames.

**Critical note:** The watch skill extracts frames for visual inspection. It does not parse them automatically. Every timestamp confirmation in this run was done by reading frame images and inspecting the scoreboard numbers in the bottom bar.

### Step 4: The Anchor Chain Method (Self-Correcting)

The key technique: each confirmed timestamp becomes the **anchor** for finding the next play.

```
Anchor: "Davis Q3 0:44 happened at video second 3759"
  → Next play: Caruso Q3 0:13, which is 31 game-seconds later
  → At DEAD_BALL_RATIO 1.6, estimate: 3759 + (31 × 1.6) = ~3809s
  → Scan 63:00–64:00, find scoreboard flip from LAL 73 to LAL 75
  → Confirm: 3796s
  → Update DB: video_time_seconds = 3796, refinement_method = 'watch_confirmed'
```

The error never compounds because each found play resets the anchor. A bad estimate only affects the search window (we might need to expand the scan range), never the confirmed value.

### Step 5: Quarter Transition Handling

Each quarter boundary required a fresh anchor since accumulated drift was unpredictable:


| Transition | Strategy                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------- |
| Q1 → Q2    | Found Horton-Tucker Q2 11:30 by scanning from Q1 end (~1310s) + estimated 60s break          |
| Q2 → Q3    | Halftime break ~6 minutes video time; estimated and confirmed James Q3 10:32 at 2777s        |
| Q3 → Q4    | 3-4 minute break; confirmed Davis Q4 11:45 at 3849s (just 7 seconds after Q3 ended at 3803s) |


### Step 6: Clip Generation

`ClipService.generate_clips()` was called with all 37 confirmed moments.

**FFmpeg command used (after fast-seek fix):**

```
ffmpeg -ss {start} -i full_game.mp4 -t {duration} -c:v libx264 -c:a aac -avoid_negative_ts make_zero -y output.mp4
```

Constants from `app/utils/constants.py`:

- `CLIP_PRE_ROLL_SECONDS = 7` — start 7 seconds before the basket
- `CLIP_POST_ROLL_SECONDS = 1` — end 1 second after the basket
- `CLIP_TOTAL_SECONDS = 8` — total clip length

Output path: `backend/data/outputs/0052000121/clips/{player_name}/clip_{moment_id:03d}.mp4`

---

## Technical Issues Encountered

### Issue 1: `playbyplayv2` Deprecated — Silent Empty Data

**What happened:** `nba_api.stats.endpoints.playbyplayv2` returned empty data mid-session. The code silently fell back to a mock JSON file containing only Q1 plays.  
**Fix:** Updated `nba_service.py` to use `playbyplayv3`. Cleared all moments from DB, re-fetched all 4 quarters.  
**Impact:** ~30 minutes lost.

### Issue 2: SQLAlchemy `NoReferencedTableError` in Standalone Scripts

**What happened:** Running `MomentService` from a standalone Python script failed because SQLAlchemy didn't know about all tables.  
**Fix:** Explicitly imported all models (`User`, `Game`, `Moment`, `Clip`) before any DB operation.

### Issue 3: FFmpeg `-ss` After `-i` = Full Video Decode (Catastrophic Slowdown)

**What happened:** The original `cut_clip` in `ffmpeg.py` placed `-ss` (seek) AFTER `-i` (input), which forces FFmpeg to decode the entire video from frame 0 to the cut point. For a clip at 5200 seconds into an 88-minute video, this meant decoding ~87 minutes of video to cut 8 seconds.  
**Observed:** The first clip generation attempt ran for 10+ minutes and produced 0 files.  
**Fix:** Moved `-ss` BEFORE `-i` (fast keyframe seeking) and changed `-to` to `-t` (duration-based):

```python
# Before (slow):
cmd = [ffmpeg, "-i", input_path, "-ss", str(start), "-to", str(end), ...]
# After (fast):
cmd = [ffmpeg, "-ss", str(start), "-i", input_path, "-t", str(duration), ...]
```

**Impact:** Clip generation time dropped from estimated 10+ hours to ~9 minutes (37 clips × ~15s each).

### Issue 4: `ffmpeg`/`ffprobe` Not on PATH in Python Subprocess

**What happened:** The Python subprocess spawned by our script did not inherit the PATH override set in the shell. `shutil.which("ffmpeg")` returned `None`, causing `get_video_duration()` to invoke bare `"ffmpeg"` which hung waiting for an OS resolution that never came.  
**Fix:** Set `$env:PATH` before running the Python script in the same PowerShell command.

### Issue 5: UnicodeEncodeError on Schröder

**What happened:** `ö` in Schröder's name caused a `UnicodeEncodeError` when Python tried to print it to the Windows console.  
**Fix:** Set `$env:PYTHONIOENCODING = "utf-8"` before every Python invocation.  
**Side effect:** The clips folder was created as `SchrAder` instead of `Schröder` (Windows path encoding artifact). The clips exist and play correctly but the folder name is mangled.

### Issue 6: LeBron Ankle Injury — Long Dead Ball (Q4 2:07)

**What happened:** LeBron went down with an ankle injury with 2:07 left in Q4. The game clock was frozen at 2:07 for ~4 real minutes while medical staff attended to him. This caused a massive video drift at exactly the worst time (late Q4 with multiple scoring plays to find).  
**Observed in frames:** Frame at 82:20 showed GS 98 LAL 97, clock 2:07. Frame at 84:00 showed GS 98 LAL 98, clock still 2:07. Frame at 85:00 showed GS 98 LAL 98, clock 1:52 — game finally resumed.  
**Impact:** Davis Q4 1:31 was found at ~5118s (85:18 in video), and James Q4 0:58 game-winner at ~5213s (86:53 in video). The final 1:31 of game clock took 26 real minutes of video.

---

## Timing Breakdown


| Phase                                       | Duration                |
| ------------------------------------------- | ----------------------- |
| NBA API fetch (playbyplayv3, 37 moments)    | ~2 min                  |
| Timestamp confirmation (all 37 plays)       | ~60 min                 |
| Clip generation (37 clips × ~15s each)      | ~9 min                  |
| Buffer + reruns + spot checks               | ~6 min                  |
| **Operational total (post-fixes)**          | **~1h15m**              |

Historical context from earlier iterations:
- API deprecation, FFmpeg seek bug, and environment/debug work consumed substantial extra time before the final successful run.
- The previous "~4.5 hours" number represented cumulative effort across troubleshooting, not the final repeatable path.


---

## Full Confirmed Timestamp Table


| ID  | Player        | Q   | Game Clock | Score Change    | Video Time | Video MM:SS |
| --- | ------------- | --- | ---------- | --------------- | ---------- | ----------- |
| 2   | Drummond      | 1   | 11:10      | LAL 0→2         | 82s        | 1:22        |
| 6   | James         | 1   | 8:29       | LAL 4→6         | 258s       | 4:18        |
| 9   | Caldwell-Pope | 1   | 6:40       | LAL 8→11        | 442s       | 7:22        |
| 11  | Caldwell-Pope | 1   | 4:43       | LAL 13→16       | 687s       | 11:27       |
| 12  | Caruso        | 1   | 4:13       | LAL 16→19       | 752s       | 12:32       |
| 13  | Caruso        | 1   | 2:49       | LAL 19→21       | 947s       | 15:47       |
| 16  | Davis         | 1   | 0:55       | LAL 21→23       | 1176s      | 19:36       |
| 18  | Horton-Tucker | 2   | 11:30      | LAL 22→25       | 1365s      | 22:45       |
| 22  | Kuzma         | 2   | 6:52       | LAL 26→28       | 1823s      | 30:23       |
| 23  | Harrell       | 2   | 6:22       | LAL 28→30       | 1854s      | 30:54       |
| 26  | Caruso        | 2   | 4:36       | LAL 30→33       | 2056s      | 34:16       |
| 28  | Davis         | 2   | 3:30       | LAL 33→35       | 2220s      | 37:00       |
| 30  | Caruso        | 2   | 2:20       | LAL 35→37       | 2288s      | 38:08       |
| 32  | Caruso        | 2   | 0:48       | LAL 38→40       | 2464s      | 41:04       |
| 34  | Schröder      | 2   | 0:10       | LAL 40→42       | 2513s      | 41:53       |
| 36  | James         | 3   | 10:32      | LAL 46→48       | 2777s      | 46:17       |
| 38  | Caldwell-Pope | 3   | 9:58       | LAL 49→51       | 2849s      | 47:29       |
| 39  | Schröder      | 3   | 8:47       | LAL 53→56       | 2974s      | 49:34       |
| 41  | James         | 3   | 7:30       | LAL 56→58       | 3134s      | 52:14       |
| 44  | Drummond      | 3   | 5:51       | LAL 58→60       | 3272s      | 54:32       |
| 47  | Matthews      | 3   | 4:46       | LAL 60→63       | 3363s      | 56:03       |
| 48  | Davis         | 3   | 4:14       | LAL 63→65       | 3430s      | 57:10       |
| 50  | Davis         | 3   | 2:17       | LAL 66→68       | 3650s      | 60:50       |
| 51  | Kuzma         | 3   | 1:48       | LAL 68→70       | 3681s      | 61:21       |
| 53  | James         | 3   | 1:05       | LAL 70→73       | 3729s      | 62:09       |
| 54  | Davis         | 3   | 0:44       | LAL 73→75       | 3759s      | 62:39       |
| 56  | Caruso        | 3   | 0:13       | LAL 75→77       | 3796s      | 63:16       |
| 57  | Davis         | 4   | 11:45      | LAL 77→79       | 3849s      | 64:09       |
| 58  | Kuzma         | 4   | 11:05      | LAL 79→81       | 3912s      | 65:12       |
| 59  | James         | 4   | 10:23      | LAL 81→83       | 3944s      | 65:44       |
| 60  | James         | 4   | 9:50       | LAL 83→85       | 3984s      | 66:24       |
| 61  | Davis         | 4   | 8:36       | LAL 85→87       | 4151s      | 69:11       |
| 64  | Davis         | 4   | 7:29       | LAL 87→90 3PT   | 4227s      | 70:27       |
| 68  | Davis         | 4   | 5:14       | LAL 91→93       | 4516s      | 75:16       |
| 70  | Schröder      | 4   | 4:03       | LAL 93→95       | 4627s      | 77:07       |
| 73  | Davis         | 4   | 1:31       | LAL 98→100      | 5118s      | 85:18       |
| 74  | James         | 4   | 0:58       | LAL 100→103 3PT | 5213s      | 86:53       |


---

## Drift Analysis: Formula vs. Reality

The naive formula (only counting live game time × DEAD_BALL_RATIO) would have placed clips here:


| Quarter | Formula Error at End of Quarter                      |
| ------- | ---------------------------------------------------- |
| Q1      | ~8 min late                                          |
| Q2      | ~16 min late                                         |
| Q3      | ~22 min late                                         |
| Q4      | ~25+ min late (exacerbated by LeBron injury timeout) |


The anchor chain method kept error near 0 for every play because each confirmed timestamp reset the estimate.

---

## Clip Quality Analysis (First Run Review)

Clip cut formula: `start = video_time - 7s`, `end = video_time + 1s`

**Caldwell-Pope**


| Clip | Assessment |
| ---- | ---------- |
| 009  | Perfect    |
| 011  | Perfect    |
| 038  | Perfect    |


**Caruso**


| Clip | Assessment        | Note                           |
| ---- | ----------------- | ------------------------------ |
| 012  | Needs start +1–2s | Clip starts slightly too early |
| 013  | Perfect           |                                |
| 026  | Good              |                                |
| 030  | Perfect           |                                |
| 032  | Needs start +2s   |                                |
| 056  | Perfect           |                                |


**Davis**


| Clip | Assessment               | Note                                                     |
| ---- | ------------------------ | -------------------------------------------------------- |
| 016  | Good                     |                                                          |
| 028  | Good                     |                                                          |
| 048  | Needs start −4 to −5s    | Timestamp confirmed too late; pre-roll misses play start |
| 050  | Good                     |                                                          |
| 054  | Needs start −5s at least | Same — timestamp confirmed too late                      |
| 057  | **No bucket in clip**    | `video_time` 3849s is wrong; play may be 5–8s later      |
| 061  | Needs start +1–2s        |                                                          |
| 064  | **No bucket in clip**    | `video_time` 4227s is wrong; started too early           |
| 068  | Good                     |                                                          |
| 073  | Needs start +3s          |                                                          |


**Drummond**


| Clip | Assessment      | Note |
| ---- | --------------- | ---- |
| 002  | Good            |      |
| 044  | Needs start +3s |      |


**Harrell**


| Clip | Assessment |
| ---- | ---------- |
| 023  | Good       |


**Horton-Tucker**


| Clip | Assessment |
| ---- | ---------- |
| 018  | Good       |


**James**


| Clip | Assessment            | Note                               |
| ---- | --------------------- | ---------------------------------- |
| 006  | Good                  |                                    |
| 036  | Needs start −4s       | Play begins earlier than timestamp |
| 041  | Perfect               |                                    |
| 053  | Perfect               |                                    |
| 059  | Perfect               |                                    |
| 060  | Perfect               |                                    |
| 074  | Perfect (game winner) |                                    |


**Kuzma**


| Clip | Assessment            | Note                        |
| ---- | --------------------- | --------------------------- |
| 022  | Perfect               |                             |
| 051  | Perfect               |                             |
| 058  | **No bucket in clip** | `video_time` 3912s is wrong |


**Matthews**


| Clip | Assessment                   | Note                                                                                                                                                                                                                                                 |
| ---- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 047  | Unique — steal-to-score play | Clip captured the steal and approach perfectly, but the 8-second window cuts off the actual basket. Need +5–6s of post-roll to capture bucket + celebration. Recommend: `video_time - 7s` to `video_time + 6s` = 13s clip for this play specifically |


**Schröder**


| Clip | Assessment |
| ---- | ---------- |
| 034  | Perfect    |
| 039  | Perfect    |
| 070  | Perfect    |


---

## Summary Stats: Clip Quality


| Grade                               | Count | %   |
| ----------------------------------- | ----- | --- |
| Perfect / Good                      | 26    | 70% |
| Needs pre-roll shift (+/−)          | 8     | 22% |
| No bucket visible (wrong timestamp) | 3     | 8%  |


**Clips with wrong timestamps (no bucket visible):**

- `057` — Davis Q4 11:45 at 3849s: bucket appears to be 5–8s later
- `064` — Davis Q4 7:29 at 4227s: started too early
- `058` — Kuzma Q4 11:05 at 3912s: no bucket visible

**Notable special case:**

- `047` — Matthews Q3 4:46: Full possession context captured (steal → drive → basket) but the 8s clip window clips the basket itself. This play type argues for a dynamic clip length based on play context rather than a fixed 8-second window.

---

## Lessons Learned for Next Run

1. **Timestamp precision:** Visual confirmation via 1fps frames misses intra-second precision. At 1fps, a play confirmed at "frame 80" (e.g., 4240s) could be anywhere in a 1-second window. At 2fps it's ±0.5s. For plays that scored (clip 57, 64, 58), the 1fps sampling left us on the wrong side of the basket.
2. **Post-confirmation verification:** After writing a timestamp, we should immediately check the next frame to confirm the scoreboard change is present. We caught most plays on the frame where the score had already changed (meaning the basket was in the previous 0.5–1s), but sometimes the basket slipped out of the pre-roll window.
3. **Dynamic clip windows:** A fixed 7s pre-roll / 1s post-roll is too rigid. Long possessions (like Matthews' steal-and-score) need more post-roll. Pull-up catch-and-shoot plays need less pre-roll. A future version could vary `pre_roll` and `post_roll` per `action_type`.
4. **3PT shots need more post-roll:** The game winner (clip 074, James 3PT) was marked perfect — but 3PT shots often have exciting reactions for 2–3s after the make. Consider `post_roll = 3s` for 3PT shots.
5. **Q4 late-game drift:** The LeBron ankle injury (2:07 frozen for ~4 min of video) is the kind of event that no ratio-based model can predict. Future robustness: after identifying a large dead-ball gap (e.g., scoreboard frozen for >100s of video), re-anchor rather than assuming previous drift continues.
6. **FFmpeg fast-seek is essential:** Always use `-ss` before `-i` for seeking in long videos. The difference is 87-minute decode vs. sub-second keyframe jump.
7. **Fix the Schröder encoding:** `ö` in folder names creates `SchrAder` on Windows. Normalize player names to ASCII before building output paths.
8. **MVP architecture needs deterministic timestamping:** claude-video watch is excellent for validation/fallback, but using it for every play is too slow for a "pick team(s) + all scorers + rapid review" product flow. OCR/template scorebug scanning should become the primary timestamp engine (not yet implemented).

