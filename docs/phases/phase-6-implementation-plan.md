# Phase 6 (Revised) — Implementation Plan

**Companion to:** [phase-6-revised-plan.md](phase-6-revised-plan.md) (the strategy). This doc is
the concrete, file-by-file build plan.

**Goal:** a pipeline behind a single frontend action — pick team + game ID + players → per-player
bucket clips — at first-run accuracy (~92% timestamping, validated in [first_run.md](first_run.md)),
fast, and without a Claude call per play.

Build order is bottom-up: confirmation engine → the data it writes → the chain that drives it →
windowing → endpoint → validation.

---

## Stage 1 — Accurate, fast confirmation engine

### Change 1 · `app/utils/scorebug_regions.py` — fix score crop boxes
Replace ESPN `away_score_region`/`home_score_region` with verified digit-only boxes:
`away = (210, 648, 95, 40)` (GSW, right-aligned, fits "100"), `home = (315, 648, 90, 40)`
(LAL, left-aligned). Every timestamp confirmation is a white-pixel comparison of these boxes;
the current boxes catch crowd above the bar and clip 3-digit scores → false flips and misses.
Foundation for everything downstream.

### Change 2 · `app/services/score_change_detector.py` — port validated v2 logic
From `scripts/validate_score_detector_v2.py`:
- one batched ffmpeg call per window (fps=2) instead of per-second seeks (~10× faster),
- persistence check (change must hold ~2s — rejects jersey/animation blips),
- single-side rule (both boxes jump same frame = bar animation, skip),
- widen-once retry (no flip in ±8s → retry ±16s),
- return `(verified, video_second, confidence, method)`.

This is the deterministic codification of the AI's per-play job ("find the frame where the score
flips X→Y"): ~2 min/play → ~0.7s/play. Validated 27/37 within ±2s; the rest become LOW → fallback.

### Change 3 · `app/utils/constants.py` — windowing + detection constants
Add `SCORE_FLIP_LAG_SECONDS = 1.0`, `CLIP_LEAD_SECONDS = 5`, `CLIP_TRAIL_SECONDS = 3`,
`SCORE_VERIFY_WIDEN_WINDOW = 16`, `TRANSITION_MAX_LEAD_SECONDS = 10`, plus persistence/threshold
constants. Mark old `CLIP_PRE_ROLL/POST_ROLL` legacy. Project rule: all magic numbers live here.

---

## Stage 2 — Carry the data the pipeline needs

### Change 4 · `app/models/moment.py` — add `confidence`, `transition_lead_seconds`
Nullable `confidence` (String "high"/"low") drives HIGH→auto-accept / LOW→flag routing and frontend
review surfacing. `transition_lead_seconds` (Float) carries play-context to windowing. SQLite only
creates columns on a fresh table → recreate `app.db` and re-fetch (no data to preserve).

### Change 5 · `app/services/moment_service.py` — compute transition lead from event stream
In `process_events`, while iterating the **full** event list, detect when a made-shot possession was
triggered by a steal / turnover / defensive rebound by the scoring team in the preceding events;
store an estimated extra lead (game-clock gap to the trigger, capped at `TRANSITION_MAX_LEAD_SECONDS`)
on the moment. This is the **Matthews 047 fix** — the trigger event is filtered out of moments, so
this is the only place with access to it.

---

## Stage 3 — Drive the proven anchor chain with the fast engine

### Change 6 · `app/services/refinement_service.py` — flip primary, watch fallback, confidence
Keep anchor-chain bookkeeping (anchors advance on confirm, interpolate on miss, wide window at
quarter breaks). Replace per-play `_run_watch_scan` with flip detection centered on the anchor
estimate (`last_confirmed_second + clock_gap × DEAD_BALL_RATIO`). Clean flip near estimate →
`confidence="high"`, confirmed. No flip / disagreement → `confidence="low"`, flagged. Keep `watch.py`
wired but **default-off** (flag-only). Preserves the self-correction that gave the first run its 92%;
only the expensive step changes. Clips 057/064/058 (the 3 truly-wrong first-run plays) now flag
instead of shipping.

---

## Stage 4 — Cut the right window

### Change 7 · `app/services/clip_service.py` — dynamic, play-aware bounds
Replace fixed `calculate_clip_bounds` (7/1) with: `net = flip − SCORE_FLIP_LAG`;
`start = net − (CLIP_LEAD + (transition_lead or 0))`; `end = net + CLIP_TRAIL`; clamp to video.
Fixes the 8 mis-windowed clips and Matthews: anchors on the reliable flip, applies the 5-before/
3-after spec, extends lead for transition plays.

---

## Stage 5 — One button for the frontend

### Change 8 · `app/api/clips.py` — unified `/process` + status model
`POST /api/games/{id}/process` runs fetch → moments → anchor-chain confirm → clip cut as one
background task, advancing `Game.status` (`fetching → confirming → cutting → done`) with counts.
Add `GET /api/games/{id}/status` for polling. Accepts team / players / full-team filters. The exact
backend contract Phase 7's UI sits on.

---

## Stage 6 — Prove it

### Change 9 · Tests + full-game re-run
Update `test_refinement_service.py` (flip path), `test_clip_service.py` (dynamic bounds); add
`test_score_change_detector.py`; keep `scripts/validate_score_detector_v2.py` as manual regression
gate. Re-run the full game; score output against the clip grades in `first_run.md` (the acceptance
bar). Tests pass before the phase is done.

---

## Sequencing & checkpoints
1. Changes 1–3 → run `validate_score_detector_v2.py` (detector accuracy holds). **checkpoint**
2. Changes 4–5 → recreate DB, re-fetch, confirm `transition_lead` populates on the right plays.
3. Change 6 → anchor chain on full game; inspect confidence labels + timestamps. **checkpoint**
4. Change 7 → cut clips; spot-check vs `first_run.md` grades. **checkpoint (real test)**
5. Change 8 → wire `/process`, smoke-test end to end.
6. Change 9 → tests green, documented.

## Decisions
- Watch fallback ships **wired but default-off** (flag-only); review UI catches LOW-confidence plays.
- **Recreate `app.db`** rather than migrate (dev data, nothing to preserve).
- Home/away mapping confirmed: LAL = home = left box, GSW = away = right box; score strings are
  `"LAL {home} GSW {away}"`, consistent with `_detect_scoring_side`.

## Outcome (implemented)

The pixel-only detector failed in the full-game checkpoint (free throws and other baskets flip
the same score box, so the chain anchored on the wrong flip and cascaded). The fix — and the
key implemented design — is **forward score-signature scanning** (`find_score_transition`):

- Scan FORWARD from the last confirmed second; a cheap frame-to-frame white-mask diff finds
  candidate change frames, then targeted OCR reads the score box just before/after and requires
  the value to transition `expected_before → expected_after`. This is the exact score signature
  the Phase 5A agent used — it rejects free throws, other baskets, and animation blips.
- The chain self-heals: a missed play does **not** advance the anchor, so the next play scans
  forward for its own signature; one miss can't cascade.
- Scan reach is chunked (`_SCAN_CHUNKS`, near→far) to stay fast while still covering timeouts,
  quarter/halftime breaks, and the ~4-min Q4 injury freeze.

Full-game checkpoint vs the 37 first-run labels: **37/37 confirmable**, with ~26/37 within ±2s
of the (imperfect) labels at ~14s/play. Several "off" cases are the detector being *more* correct
than the first run — e.g. Davis Q3 0:44 → 3752s where the labelled 3759s was clip 057 ("no bucket"
in the first run). Score-box OCR verified accurate at 1/2/3-digit scores (incl. "103").

Validation harness: `scripts/checkpoint_full_run.py` (full chain vs labels, throwaway DB),
`scripts/validate_detector_service.py` (centered detector vs labels).

Constants that turned out unused after the redesign were removed; scan reach lives in
`_SCAN_CHUNKS`, not a per-quarter window constant.

### v2 clip review → window calibration

First v2 clip set (`scripts/cut_v2_clips.py` → `clips_v2/`) confirmed 37/37 buckets detected,
but the ball landed at the 3s mark instead of 5s. Root cause: the scorebug flip trails the
ball through the net by **~3s**, not the 1s first assumed (measured: KCP 6:40 net ≈ 439s,
flip 442s). Fix was one constant: `SCORE_FLIP_LAG_SECONDS = 3.0` → clip `[flip−8, flip]`, ball
at the 5s mark, 3s after.

Also from review: the transition-lead extension is **not applied to clip bounds** by default —
a uniform 5-before-net window is what works; extra lead bloated transition clips and didn't
reliably capture the steal. The detection is still computed and stored on the moment for a
future "start at the steal" mode (the correct way to handle plays like Matthews 047), which
needs per-play net detection rather than a fixed lead. Two known residual edge cases have a
larger/variable flip lag (replay graphics / delayed score updates) and remain ~1–3s early;
fully fixing them needs visual net detection, deferred.
