# Phase 5B: HSV White-Mask Digit Reader Fix

## Related docs

- [PHASES.md](../PHASES.md) — phase index (5B status)
- [phase-5a-full-game-pipeline.md](phase-5a-full-game-pipeline.md) — claude-video anchor chain baseline (slow but validated)
- [first_run.md](first_run.md) — ground-truth table for game `0052000121` (37 LAL buckets)
- [ARCHITECTURE.md](../ARCHITECTURE.md) — scorebug scanner as primary timestamp path
- [PROJECT.md](../PROJECT.md) — MVP goals and scanner-first strategy

## Problem

The Phase 5B scanner prototype ran end-to-end but returned **0/37** ground-truth matches. Root cause: `_to_binary()` in `digit_reader.py` used **Otsu global thresholding**, which assumes a stable two-tone histogram. TNT scorebugs are **translucent** — court and players bleed through the overlay and change every frame, so Otsu thresholds drift and court shapes become fake digit contours.

ROI placement was verified correct via interactive calibration; the binarization method was wrong, not the crop boxes.

## Fix

Replace Otsu with **HSV white-text masking**:

1. Resize ROI 2×
2. Convert BGR → HSV
3. `cv2.inRange` for near-white pixels (`low saturation`, `high value`)
4. Morphological open/close to remove specks and connect digit strokes
5. Existing template matcher unchanged
6. Grayscale Otsu fallback when HSV mask finds no contours (synthetic tests + edge cases)

## Config

`ScorebugConfig` now includes optional `white_mask`:

```json
{
  "white_mask": {
    "v_min": 180,
    "s_max": 70,
    "morph_kernel": 2
  }
}
```

Defaults live in `backend/app/utils/constants.py`:

| Constant | Default | Meaning |
|----------|---------|---------|
| `SCOREBUG_WHITE_V_MIN` | 180 | Min brightness (HSV V channel) |
| `SCOREBUG_WHITE_S_MAX` | 70 | Max saturation (lower = stricter white) |
| `SCOREBUG_MORPH_KERNEL` | 2 | Morph open/close kernel size |

Existing calibrated ROIs do **not** need re-selection — only add `white_mask` to `scorebug_config.json` if missing.

## Code changes

| File | Change |
|------|--------|
| `backend/app/utils/digit_reader.py` | `_to_digit_mask()`, HSV mask + morph; Otsu fallback |
| `backend/app/utils/scorebug_config.py` | `WhiteMaskConfig`, `resolve_white_mask()` |
| `backend/app/utils/constants.py` | White-mask default constants |
| `backend/app/services/scoreboard_scan_service.py` | Pass mask config to digit readers |
| `backend/app/utils/digit_templates.py` | **New** — load/save/extract broadcast digit templates |
| `backend/scripts/build_digit_templates.py` | **New** — build templates from labeled samples |
| `backend/scripts/calibrate_scorebug.py` | Default interactive second=258; save `white_mask`; post-calibration preview |
| `backend/tests/test_digit_reader.py` | Noisy-background + mask tests |

## Validation workflow

Run from `backend/` with `PYTHONPATH=.` (or equivalent).

### 1. Visual mask check (~5 seconds)

```powershell
python scripts/debug_digit_mask.py --game-id 0052000121 --second 258
```

Inspect `backend/data/outputs/0052000121/scan/debug/`:

- `258s_left_raw.jpg` / `258s_right_raw.jpg` — ROI crops
- `258s_left_mask.jpg` / `258s_right_mask.jpg` — HSV masks (should show clean digit silhouettes)
- `258s_*_read.txt` — parsed score + confidence

### 2. Tune thresholds if needed

```powershell
python scripts/debug_digit_mask.py --game-id 0052000121 --second 258 --v-min 170 --s-max 80
python scripts/debug_digit_mask.py --game-id 0052000121 --tune
```

Update `white_mask` in `scorebug_config.json` with values that produce clean masks.

### 3. Inspect scan vs NBA API (recommended 5B gate)

```powershell
python scripts/inspect_scan.py --game-id 0052000121
```

Prints LAL transition summary, API bucket count, signature match rate, spot reads, and a `ready_for_5c` checklist. Writes `inspect_report.json`.

### 4. Full scan + legacy ground-truth diff (optional)

Only after step 1 passes:

```powershell
python scripts/validate_scorebug_scan.py --game-id 0052000121 --run-scan
```

Targets:

| Metric | Before fix | Target |
|--------|------------|--------|
| `transitions.json` length | 0 | > 0 |
| `match_rate` | 0.0 | > 0.5 (iterate thresholds) |
| `median_error_seconds` | N/A | < 5s ideally |

Ground truth: LAL score transitions parsed from [first_run.md](first_run.md).

### 5. Unit tests

```powershell
python -m pytest tests/test_digit_reader.py tests/test_scoreboard_scan_service.py -v
```

## Out of scope (this change)

- Clock/period ROI reading (score-only sufficient for 5B)
- Auto-tuning thresholds across full game
- Re-running interactive ROI calibration (unless debug masks show ROI problem)

## Broadcast digit templates (follow-up)

HSV masking alone caps template-match confidence around ~0.3–0.5 on TNT italic digits. Build profile templates from labeled scorebug samples:

```powershell
python scripts/build_digit_templates.py --game-id 0052000121 --use-default-samples
python scripts/debug_digit_mask.py --game-id 0052000121 --second 258
python scripts/validate_scorebug_scan.py --game-id 0052000121 --run-scan
```

Templates are saved to `backend/data/outputs/{game_id}/scan/digit_templates/{profile_name}/`. The scan service loads them automatically when `profile_name` matches (e.g. `tnt_2021`).

Per-side confidence threshold: `SCOREBUG_MIN_SIDE_CONFIDENCE = 0.35` (each team score must pass independently).

## Next steps (5C+)

- Map scanner transitions to NBA API play events
- Route low-confidence plays to claude-video `watch.py` fallback
- Unified pipeline endpoint (Phase 6) and hackathon frontend (Phase 7)
