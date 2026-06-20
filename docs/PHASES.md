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
| 7 | Clip Library — durable ingest (all players/both teams, broadcast-profile param, rich metadata) — **Track A1** | **Done** — 74 clips ingested from the demo game into `data/library.db` |
| 8 | Compose — filter query → stitched reel — **Track A2** | **Done** — `compose_service`; player/category/season/month/distance/etc. filters |
| 9 | Review nudge + YouTube publish — **Track A3** | **Done & validated** — `nudge_clip`, `youtube_publisher`; a reel was uploaded to YouTube end-to-end |
| 10 | Broadcast generalization / auto-calibration — **Track B** (gate to real, varied games) | Planned — needs sample scoreboard frames |

> **Direction (June 2026):** product is a CLI + clip library, **no web frontend**, no auth.
> Track A (ingest → library → compose → review → YouTube) is **built and validated end-to-end on
> the demo game**. Track B (broadcast generalization) is the remaining gate to arbitrary League
> Pass games. See [STRATEGY.md](STRATEGY.md). 5B dead; 5C clock-OCR parked (future non-scoring
> events); auto quarter detection superseded by the anchor chain.
