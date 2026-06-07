# Phase 7: Hackathon MVP Frontend

## Goal
Build a minimal Next.js frontend that lets a user go from raw game video to rapid
per-player bucket review in a single browser session.

Important implementation note: backend auth currently exists and protects most routes.
If "no login demo mode" is still required, Phase 6/7 must include a deliberate auth
strategy (guest user, seeded demo account, or temporary bypass in local mode).

## MVP User Flow (5-minute demo target)

```
1. Upload page
   → drag/drop or file-pick the full_game.mp4
   → type in the NBA game ID (e.g. 0052000121)
   → hit "Load"
   
2. Team + player selection
   → choose team: LAL, GSW, or Both
   → player list auto-populates from NBA API play-by-play
   → pick individual players OR "Full team — all scorers"
   → choose mode: Buckets (MVP)
   → hit "Start Processing"

3. Processing status
   → live polling every 2s: "Fetching moments... Scanning scoreboard... Mapping events..."
   → simple progress bar or step indicator

4. Rapid review
   → tabs across the top: one per player
   → each tab shows that player's bucket segments in a queue/grid
   → click any segment to play from source video at [start, end]
   → optional "Export MP4 clips" action runs after review
```

## Status
Not started. Depends on:
- Phase 5B (scorebug scanner prototype; OCR/template not implemented yet)
- Phase 5C (event mapping + confidence + claude-video fallback)
- Phase 6 (unified pipeline endpoint/status)

## Tech Stack
- Framework: Next.js (App Router)
- Language: TypeScript
- Styling: Tailwind CSS
- HTTP client: fetch (no extra library needed for MVP)
- Video: native HTML5 `<video>` element
- State: React useState / useEffect (no Redux)
- Backend: existing FastAPI on port 8000

## Folder Structure
```
frontend/
  app/
    page.tsx              ← Upload + game ID entry
    [gameId]/
      setup/page.tsx      ← Team + player selection
      processing/page.tsx ← Live status polling
      clips/page.tsx      ← Clips viewer by player
  components/
    PlayerTabs.tsx
    ClipGrid.tsx
    ClipPlayer.tsx
    StatusStepper.tsx
  lib/
    api.ts               ← fetch wrappers for backend endpoints
```

## Backend Endpoints Required

Current endpoint status:

| Endpoint | Used for |
|----------|----------|
| `POST /api/games/` | Exists |
| `POST /api/games/{id}/upload` | Exists |
| `POST /api/games/{id}/fetch-moments` | Exists |
| `POST /api/games/{id}/refine-moments` | Exists (claude-video anchor chain baseline) |
| `POST /api/games/{id}/generate-clips` | Exists |
| `GET /api/games/{id}` | Exists |
| `GET /api/games/{id}/moments` | Exists (team/player filters not implemented yet) |
| `GET /api/games/{id}/clips` | Exists (player filter not implemented yet) |

Phase 6 target endpoint (to add):
`POST /api/games/{id}/process?teams=LAL,GSW&players=all&mode=buckets`

## Key Decisions
- MVP mode is buckets only.
- Frontend supports one team or both teams.
- "All scorers" is the default player selection for fast demo flow.
- Rapid review opens from timestamps/segments first; clip rendering is deferred/on-demand.
- claude-video watch is fallback for low-confidence mappings, not the primary timestamping method.
- Processing runs in background; frontend polls status.
- Failure state shows which step failed and an error message.

## Acceptance Criteria
- Upload video → enter game ID → choose team/both → choose players/all scorers → review segments
- Full processing-to-review flow completes in under 5 minutes on a local machine
- Each player tab shows playable bucket segments sourced from timestamped moments
- No crashes on happy path (failure states handled gracefully)
- Works on Chrome/Edge desktop

## Tasks

### Phase 6 prerequisite: unified pipeline endpoint
- [ ] `POST /api/games/{id}/process` triggers fetch → scan_scorebug → map_events → ready_for_review
- [ ] Status model: `pending → fetching → scanning → mapping → ready_for_review | failed`
- [ ] Supports `teams` (`LAL`, `GSW`, `both`) and players filters
- [ ] Returns job ID/status payload; frontend polls `GET /api/games/{id}` for status

### Phase 7 frontend
- [ ] Scaffold Next.js app with Tailwind in `frontend/`
- [ ] Upload page: video file picker + game ID input + "Load" button
- [ ] `POST /api/games/` then `POST /api/games/{id}/upload` on submit
- [ ] Team selector: `LAL`, `GSW`, `Both`
- [ ] Player list: fetch moments and build scorer list client-side (until backend filtering lands)
- [ ] Player multi-select with "Select all" toggle
- [ ] "Start Processing" triggers `POST /api/games/{id}/process`
- [ ] Processing page: 2s polling loop, step display (Fetching / Scanning / Mapping / Ready)
- [ ] Redirect to review page on `status=ready_for_review`
- [ ] Review page: player tabs + rapid-fire segment queue
- [ ] Segment player seeks source video to [start, end] range
- [ ] Optional export action calls clip render endpoint after review
- [ ] Basic dark theme, clean typography
- [ ] Test end-to-end on game 0052000121 before demo

## Next Steps After Phase 7 (post-hackathon)
- Full approve/reject + save decisions flow
- Render concatenated highlight reel per player (Phase 5 render service)
- YouTube upload per reel
- Login + user accounts (Phase 1 auth already built)
- Multi-game support (loop over game IDs)
