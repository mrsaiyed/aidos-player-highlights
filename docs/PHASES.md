# Phases

| Phase | Name | Status |
|-------|------|--------|
| 0 | Environment Setup | Complete |
| 1 | Backend + Database + Auth | Built ⚠️ — confirmation deferred to Phase 7 |
| 2 | NBA Data + Moments | Complete |
| 3 | Timeline Mapping | Complete |
| 4 | FFmpeg Clip Cutting | Complete |
| 5 | Timestamping + Clip Pipeline | In Progress |
| 5A | Claude-video Anchor Chain Baseline | Complete — full-game run validated, ~92% timestamping (34/37); too slow as-is. See [first_run.md](phases/first_run.md) |
| 5B | Deterministic Scorebug Scanner (OCR/template) | Abandoned — 0/37; wrong target (read score, not change). See [phase-5b-hsv-mask-fix.md](phases/phase-5b-hsv-mask-fix.md) |
| 5C | Clock-OCR Pipeline (`clock_ocr_service`, `event_resolver_service`) | Parked — redundant with anchor chain for scoring plays; revisit for non-scoring events post-MVP. See [phase-6-clock-ocr-pipeline.md](phases/phase-6-clock-ocr-pipeline.md) |
| 6 | **Fast Anchor Chain** — forward score-signature scan + dynamic windows + `/process` | **Implemented** — 37/37 plays confirmable; see [phase-6-implementation-plan.md](phases/phase-6-implementation-plan.md) |
| 7 | Hackathon MVP Frontend (Rapid Review) | Planned — see [phase-7-hackathon-frontend.md](phases/phase-7-hackathon-frontend.md) |
| 8 | Auto Quarter Detection | Deferred |
| 9 | Demo Polish | Not Started |

> **Active path:** Phase 6 (revised) returns to the proven 5A anchor chain but swaps the
> per-play Claude `watch.py` call for the deterministic score-flip detector, and adds
> dynamic clip windows. 5B is dead; 5C clock-OCR is parked (redundant for scoring plays).
