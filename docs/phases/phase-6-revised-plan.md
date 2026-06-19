# Phase 6 (Revised): Fast Anchor Chain — Productize the Proven Run

**Status:** In Progress (active core path)
**Supersedes:** the clock-OCR-first plan in [phase-6-clock-ocr-pipeline.md](phase-6-clock-ocr-pipeline.md)
**Builds on:** [phase-5a-full-game-pipeline.md](phase-5a-full-game-pipeline.md) (the proven run) and [first_run.md](first_run.md) (the clip-by-clip post-mortem)

## Why this plan exists

The Phase 5A agent-driven run (Claude `watch.py` confirming every play) **worked**: a
full-game run produced 37/37 clips. The clip-by-clip review in `first_run.md` lets us
score it honestly, and the result reframes everything:

| Outcome | Count | What it means |
|---------|-------|---------------|
| Perfect / good | 26/37 | timestamp right, fixed window fit |
| "Start a few seconds earlier/later" | 8/37 | **timestamp right** — the *fixed 7s/1s window* was wrong, not the time |
| No bucket in frame | 3/37 (clips 057, 064, 058) | **timestamp wrong** |

So the proven run was **~92% correct on timestamping** (34/37). The 8 "adjustment"
clips were a **clip-windowing** problem, not a timestamping problem — and windowing is
solvable from play-by-play data we already have.

**The mistake we're correcting:** Phases 5B/5C went back and re-solved timestamping
from scratch (scorebug OCR, then a separate clock-OCR pass). Timestamping was already
~92% solved. The clock-OCR pass is also **redundant** — the anchor chain already
positions each play from the previous confirmation; the successful run never used clock
OCR at all. We strayed from a working approach. This plan returns to it and fixes the
two things that were actually unsolved: **speed** and **windowing**.

## The two problems, kept separate

1. **Timestamping** — find the frame where the bucket happens. Proven solution: anchor
   chain + score-flip confirmation. Keep it.
2. **Windowing** — how many seconds before/after the bucket to cut. The fixed 7s/1s was
   a test scaffold. This is the genuinely-unsolved part; drive it from NBA play context.

## Architecture

```
NBA API (play-by-play, score signatures, prior-event context)
   │
   ▼
Anchor chain (refinement_service.py)
   for each scoring play in game order:
     window = last_confirmed_second + (clock_gap × DEAD_BALL_RATIO) ± margin
     ▼
   Score-flip confirmation (score_change_detector.py)  ← PRIMARY, ~0.7s/play
     find the frame where the correct score region flips score_before→score_after
     │
     ├─ clean flip near the anchor estimate → HIGH confidence, accept
     └─ no flip / disagrees with anchor    → LOW confidence
                                              └─ flag for review (demo default)
                                                 (optional later: Claude watch fallback)
   │
   ▼
Dynamic window (clip_service.py)
   end  = flip + POST_ROLL              (net is ~1s before the flip)
   start= flip − (LEAD + transition_lead)  (extend for steal/transition plays)
   │
   ▼
FFmpeg cut → per-player folders
```

### What changes vs the proven run
- **The per-play confirmation step is no longer a Claude call.** It's the deterministic
  white-pixel score-flip detector — the *codification* of exactly what the agent did
  (read the score box, find where it changes). ~0.7s/play instead of ~2 min/play. The
  sequential anchor chain is no longer a speed problem: 37 plays ≈ under a minute of
  detection plus one frame-extraction pass.
- **Claude `watch.py` is demoted to oracle/fallback**, used only on LOW-confidence
  plays (~3 per game), not all 37. For the hackathon demo the default is **flag-only**
  (surface them in the review UI); auto-firing watch on them is a later toggle.
- **Clip windows become dynamic** instead of a fixed 7s/1s.

## Score-flip detector — required fixes (validated this session)

The detector logic was validated against the 37 ground-truth timestamps; the working
version lives in `backend/scripts/validate_score_detector_v2.py` and must be ported into
`score_change_detector.py`:

1. **Tighter digit-only regions** in `scorebug_regions.py` (current regions include
   crowd above the bar and clip 3-digit scores). Verified ESPN coords:
   - `away_score_region = (210, 648, 95, 40)` — GSW digits, right-aligned (grows left for "100")
   - `home_score_region = (315, 648, 90, 40)` — LAL digits, left-aligned
2. **One batched ffmpeg call** per window (fps=2) instead of per-second seeks (~10× faster).
3. **Persistence check** — a mask change counts only if it stays changed ~2s (rejects
   jersey/animation blips).
4. **Single-side rule** — if both score regions jump on the same frame, it's a bar-wide
   animation/wipe, not a score change; skip it.
5. **Widen once** — if no flip in ±8s, retry ±16s before declaring LOW confidence.

Measured result with these fixes: 27/37 within ±2s of the (noisy) first-run labels at
0.7s/play. Note the first-run labels are themselves imperfect (Q3/Q4 several seconds
late in places), so agreement is corroboration, not the accuracy ceiling — the real
acceptance test is the clip review (below).

## Dynamic windowing — the actually-unsolved problem

Anchor on the flip; the net is ~1s before it (broadcast lag → `SCORE_FLIP_LAG_SECONDS`).

- **Default:** `[flip − 6s, flip + 2s]` = 5s before the net + 3s after.
- **Transition / steal plays** (the Matthews 047 case, where the play starts on a steal
  and a fixed window cut off the basket): inspect the prior NBA event in the same
  possession. If it's a steal / turnover / defensive rebound by the scoring team, extend
  the lead to capture the break, sized from the prior event's game-clock delta.

This fixes all 8 "adjustment" clips and Matthews 047 — a backend-only change.

## Confidence model

| Confidence | Condition | Action |
|------------|-----------|--------|
| HIGH | clean flip within a few seconds of the anchor estimate | accept timestamp |
| LOW | no flip found, or flip far from anchor estimate | flag for review (demo); optional watch fallback later |

The 3 truly-wrong first-run clips (057, 064, 058) are exactly the "no clean flip" cases
— they get flagged instead of shipping silently. This is a real improvement over the
first run, which shipped them wrong.

## Validation

The clip-by-clip grades in `first_run.md` are the gold standard — better than raw
timestamp seconds, because they tell us *which* plays were actually wrong vs merely
mis-windowed. Acceptance test: "does the bucket land in the clip with correct lead,"
scored against those grades. `scripts/validate_score_detector_v2.py` stays as a fast
regression gate.

## What we are NOT doing (parked)

- **Clock-OCR pass** (`clock_ocr_service.py`, `event_resolver_service.py`): redundant
  with the anchor chain for scoring plays. Keep the code, drop it from the critical
  path. Revisit only for **non-scoring events** (blocks, steals, assists) which don't
  flip the score and so can't be flip-detected — that's post-MVP (see PROJECT.md north star).
- **Scorebug OCR/template matching** (Phase 5B): abandoned, 0/37. Wrong target (read the
  score, which we already have from the API, instead of detecting the change).

## Sequencing

1. Port the v2 detector fixes into `score_change_detector.py`; fix `scorebug_regions.py`.
2. Wire the flip detector as the PRIMARY confirmation inside `refinement_service.py`'s
   anchor chain; demote `watch.py` to flagged-only fallback. Add the confidence label to
   each Moment.
3. Dynamic, play-aware windowing in `clip_service.py`; add `SCORE_FLIP_LAG_SECONDS` and
   transition-lead constants.
4. Re-run the full game; score against `first_run.md` grades.
5. Unified `POST /api/games/{id}/process` (fetch → anchor-chain confirm → window → cut)
   as a background task with a pollable status field.
6. Hand off to the Hackathon MVP Frontend (Phase 7).

Steps 1–4 return us to the successful run — fast, cheap, and with the windowing fixed.
Steps 5–6 wrap it for the demo.
