# Phases

| Phase | Name | Status |
|-------|------|--------|
| 0 | Environment Setup | Complete |
| 1 | Backend + Database (+ Auth, now unused) | Built — auth dropped; single-operator tool, no accounts |
| 2 | NBA Data + Moments | Complete |
| 3 | Timeline Mapping | Complete |
| 4 | FFmpeg Clip Cutting | Complete |
| 5 | Timestamping + Clip Pipeline | In Progress |
| 5A | Claude-video Anchor Chain Baseline | Complete — full-game run validated, ~92% timestamping (34/37); too slow as-is. See [first_run.md](phases/first_run.md) |
| 5B | Deterministic Scorebug Scanner (OCR/template) | Abandoned — 0/37; wrong target (read score, not change). See [phase-5b-hsv-mask-fix.md](phases/phase-5b-hsv-mask-fix.md) |
| 5C | Clock-OCR Pipeline (`clock_ocr_service`, `event_resolver_service`) | Parked — redundant with anchor chain for scoring plays; revisit for non-scoring events post-MVP. See [phase-6-clock-ocr-pipeline.md](phases/phase-6-clock-ocr-pipeline.md) |
| 6 | **Fast Anchor Chain** — forward score-signature scan + dynamic windows + `/process` | **Implemented** — 37/37 plays confirmable; see [phase-6-implementation-plan.md](phases/phase-6-implementation-plan.md) |
| 7 | Clip Library — durable ingest (all players/both teams, broadcast-profile param, rich metadata) — **Track A1** | Planned — see [STRATEGY.md](STRATEGY.md) |
| 8 | Compose — filter query → stitched reel — **Track A2** | Planned |
| 9 | Review gate + YouTube publish (Publisher interface) — **Track A3** | Planned |
| 10 | Broadcast generalization / auto-calibration — **Track B** (gate to real, varied games) | Planned — needs sample frames |

> **Direction (June 2026):** product is a CLI + clip library, **no web frontend** (Phase 7
> frontend dropped). Build is two parallel tracks — **A** (library → compose → YouTube, on the
> demo game) and **B** (broadcast generalization, the gate to arbitrary League Pass games). See
> [STRATEGY.md](STRATEGY.md). 5B dead; 5C clock-OCR parked; auto quarter detection superseded by
> the anchor chain.
