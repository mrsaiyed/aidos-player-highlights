# Product Strategy

The canonical "where this is going and why" doc. Architecture, locked decisions, and the build
plan. For *how the pipeline works today* see [PROJECT.md](PROJECT.md#how-it-works); for phase
status see [PHASES.md](PHASES.md).

## Goal

Input an NBA game (full-game video + game ID) → automatically produce and upload **per-player
highlight reels**. Long term: compile **any** reel from any NBA-API-derivable stat over any time
range (game / week / month / season / career) — e.g. "AD all 3s this season" — as a *query* over
an accumulated clip library, with no reprocessing.

## Locked decisions (the principles)

1. **Sealed clip engine.** The engine that finds a basket in the video and cuts it is a black
   box. Its only output is *a tagged clip in the library*. Everything downstream depends on that
   contract, never on detection internals — so detection can be refined later without touching
   anything else. We don't touch it unless we explicitly mean to.
2. **Clip everything once, query forever.** Each game is ingested **one time**; every made shot
   for **every player on both teams** becomes a clip tagged with full API metadata. Reels are
   *selected*, never *made*.
3. **Buckets only (for now).** Made shots change the score, which is exactly what detection locks
   onto. Non-scoring stats (blocks, steals, misses, rebounds) are deferred — they have no
   scoreboard anchor and need a different, harder method.
4. **Single operator, no auth.** Config file, not accounts. Sharing the tool = handing someone
   the program.
5. **Broadcast is a per-game parameter.** Ingested games are a *different broadcast every time*
   (League Pass carries varied regional feeds). The engine takes a **broadcast profile** per game
   — never assumes one broadcast. Manual/named profile now; auto-detected later (Track B). The
   library records which profile each game used.

## Architecture — five layers

```
[1] INGEST / CLIP ENGINE   video + game ID + broadcast profile → all made-shot clips, tagged   (SEALED)
        | writes
[2] CLIP LIBRARY           clip files + metadata DB — the queryable store
        | query
[3] COMPOSE                filter spec → matching clips in order → one stitched reel
        |
[4] REVIEW GATE            reels land locally → you eyeball → approve
        |
[5] PUBLISH                YouTube first (Publisher interface; other platforms later)
```

The decisive seam is **[2] → [3]**: "tonight's Lakers reel" and "AD all 3s this season" are the
*same operation* — a different filter over the same library.

### [1] Ingest / Clip Engine (sealed)
- Input: game video, NBA game ID, **broadcast profile**.
- Fetch play-by-play → all made shots (both teams) → forward score-signature detection (current
  `score_change_detector.py` + `refinement_service.py`) → cut a clip per made shot → write a
  tagged library record.
- The profile (scoreboard regions + read method) is the only broadcast-specific input. Today one
  named `espn` profile; Track B automates producing a profile per video.

### [2] Clip Library
- Clip files on disk + a metadata DB row per clip. Stable identity key `(game_id, action_id)` so
  re-ingesting a game never duplicates. A processed-games registry tracks what's in the library.

### [3] Compose
- A filter spec (player(s), shot type, distance band, value, date/season range, opponent,
  period…) → ordered clip list → concatenate (`render_service.py`) → one reel.

### [4] Review gate
- Reels + a manifest land locally; you eyeball; approve. Only approved reels publish. Lightweight
  (a command / flag), no UI.

### [5] Publish
- A `Publisher` interface; `YouTubePublisher` first. Per-reel auto-generated title/description.
  Other platforms (TikTok, etc.) implement the same interface later.

## Precision & the review loop

**How accurate it is, and why.** Detection anchors on the **scoreboard score flip**, which is a
rock-solid *play locator* (signature-confirmed, always just after the basket) — that's why
~all baskets are found. The clip is then placed a **fixed 3s** before the flip to hit the net.
The catch: the gap between ball-through-net and scoreboard-update is **variable** (usually ~3s,
but 8–10s on replays / slow operators). So ~95%+ of clips land the ball at the 5s mark, and the
rare long-lag outlier is a few seconds off.

**The review loop (built).** This is the everyday safety net, and it's a 2-second fix:
1. `compose_reel` → clips + reel in a folder, each line tagged with its library `id`.
2. Watch. If a clip is a touch early/late, `nudge_clip --id N --earlier/--later S`.
3. Nudge re-cuts the **library** clip in place and records `adjust_seconds` — so the correction
   is **permanent** and flows into *every* future reel using that clip, not just this one.
4. Re-run `compose_reel` to rebuild. Approve → publish.

**Precision pass (future, optional).** To shrink even the rare nudge:
- *Option 1 (cheap):* widen the lead so the net is **always** in frame — review then only ever
  *centers*, never *re-finds* (the one hard requirement for fast review).
- *Option 2 (the real fix, deterministic, no AI):* anchor the net on the **on-screen game clock**
  instead of a fixed offset. The shot's game-clock time is exact and lag-free; read it from the
  video (reusing the parked clock-OCR, pointed at the net moment) while the flip still locates
  the play. Near-perfect centering.
- *Option 3:* visual ball-through-hoop detection — true 100% but hard CV / AI-ish; skip, the
  review loop already covers it.

## Metadata model — get this right now

This is what makes "any reel, retroactively" possible without reprocessing. Store the **raw API
fields** per clip; derive categories at *query* time so a future filter needs no re-ingest:

- **Who / where:** player, team, opponent, game_id, **game_date**, **season**
- **What:** shot subtype, **shot_distance**, **shot_value (2/3)**, points, court location (x/y)
- **When-in-game:** period, game clock, score_after
- **Plumbing:** clip file path, stable key `(game_id, action_id)`, broadcast profile used

Then: 3s = `shot_value=3`; dunks = `subtype=dunk`; midrange = `jump_shot AND distance 10–22ft`;
"vs PHX in December" = `opponent=PHX AND month=12`. All queries, zero reprocessing.

## Two tracks

These run in parallel and converge at the **broadcast-profile seam**.

**Track A — Library + Compose + Publish.** Buildable now, validated on the demo game; needs only
your YouTube credentials. Proves the full loop: ingest → tagged library → per-player reel →
eyeball → YouTube.
- A1: durable ingest (all players, both teams, profile parameter) → tagged library.
- A2: compose layer (filter → reel).
- A3: review gate + YouTube publisher.

**Track B — Broadcast generalization / auto-calibration.** The gate to *arbitrary* League Pass
games. Find the scoreboard on an unfamiliar broadcast using the API score sequence as the
reference (match OCR'd numbers to the known score progression → locate clock + score boxes, fix
home/away). Produces a broadcast profile that Track A consumes. **Needs sample frames.**

**Honest sequencing:** Track A yields a working product *on the demo game*; Track B is required
before it works on anything you download. Independent, so neither waits on the other.

## Default loop

Everyday: **ingest tonight's game → auto per-player reels → eyeball → approve → upload.**
Power feature (on-demand): **compose** any cross-game reel ("AD December 3s", "Steph season
floaters") as a query over the accumulated library. Season/career reels require having ingested
those games — the library grows as you feed it games.

## Status

- **Built & validated (one broadcast):**
  - Detection (forward score-signature scan), dynamic clip windows. 37/37 on the demo game.
  - **A1 — clip library** (`ingest_service.py`, `library_clip.py`): ingest all made shots both
    teams → tagged rows in `data/library.db`, dedup on (game_id, action_id), broadcast-profile
    param. 74 clips ingested from the demo game.
  - **A2 — compose** (`compose_service.py`): query the library on any dimension → folder + reel.
    Filters: player, team, opponent, value, subtype, **category** (dunk/layup/three/two/floater/
    midrange/paint), period, season, game, distance band, month, date range. e.g. "AD season 3s",
    "Steph floaters", "December 3s" are all one query.
  - **Review loop** (`nudge_clip.py`): nudge a library clip earlier/later, re-cut in place,
    `adjust_seconds` persists so the fix flows into every future reel.
  - **A3 — publish** (`youtube_publisher.py`, `youtube_auth.py`, `publish_reel.py`): one-time
    YouTube connect (manual loopback OAuth), then `videos.insert` with auto-generated
    title/description from the reel's metadata sidecar. **A reel was uploaded end-to-end.**
- **Whole Track A loop is proven on the demo game:** ingest → library → compose → review → YouTube.
- **Track B core proven** (`scripts/autocalibrate_poc.py`): the auto-calibrator rediscovers the
  full ESPN scoreboard from scratch — both score boxes, the clock, and home/away — using only the
  API score sequence (no hardcoded regions). Validated by reproducing the hardcoded `espn` profile.
  **Remaining:** (1) productionize into a profile output (+ small padding) and confirm an
  auto-profile detection run matches the hardcoded one end-to-end; (2) the real test — a **second
  broadcast** (a non-ESPN game video + its NBA game ID), which is what proves it generalizes.
- **Optional polish:** a one-command "ingest → auto per-player review reels" wrapper; vertical 9:16
  reels for true YouTube Shorts (current reels are 16:9 landscape).
