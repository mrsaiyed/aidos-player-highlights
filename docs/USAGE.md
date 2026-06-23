# Usage — Running the Program

A step-by-step runbook: full game in → per-player highlight reels → YouTube.

**Where to run:** all commands are run from the `backend/` folder. On Windows use
`.venv\Scripts\python.exe scripts\<name>.py`. If `uv` is on your PATH you can instead use
`uv run python scripts/<name>.py`. (From the repo root, prefix paths with `backend\`.)

The pipeline has four moves:

```
ingest (once per game)  →  compose reels (queries)  →  review / nudge  →  publish
```

---

## 0. One-time setup

```bash
cd backend
uv sync                                  # installs deps; needs FFmpeg + ffprobe on PATH
.venv\Scripts\python.exe scripts\youtube_auth.py   # connect YouTube once (see "Publishing" below)
```

Put the game video somewhere you can point at (e.g. `data\uploads\<game_id>\full_game.mp4`) and
note the **NBA game ID** (e.g. `0052000121`).

---

## 1. Your example — every Lakers player gets their own "buckets" reel

### Step 1 — Ingest the game (do this once per game)

```bash
.venv\Scripts\python.exe scripts\ingest_game.py 0052000121 data\uploads\0052000121\full_game.mp4 espn
```

Arguments: `<game_id> <video_path> <broadcast_profile>`. This runs the detector over **every made
shot for both teams**, cuts a clip for each, and stores them — tagged with player, shot type,
distance, period, date, season — in the clip library (`data\library.db`). You only ingest a game
once; everything after is a query.

### Step 2 — Make one reel per Lakers player, with your chosen name

```bash
.venv\Scripts\python.exe scripts\make_player_reels.py --team LAL --game 0052000121 --prefix lakers_buckets
```

This produces one reel per Lakers player, each named with your prefix:

```
data\outputs\composed\lakers_buckets_James\lakers_buckets_James.mp4
data\outputs\composed\lakers_buckets_Davis\lakers_buckets_Davis.mp4
data\outputs\composed\lakers_buckets_Caruso\lakers_buckets_Caruso.mp4
... (one per player)
```

Change `--prefix` to whatever you want the reels called.

### Step 3 — Watch them, fix any stray clip (rare)

Open the reels in `data\outputs\composed\`. If a clip is a couple seconds early or late, nudge it
(the clip's `id` is printed when you compose). `--earlier`/`--later` shift it; the fix is permanent
in the library:

```bash
.venv\Scripts\python.exe scripts\nudge_clip.py --id 49 --earlier 5
```

Then re-run Step 2 to rebuild the affected reel.

### Step 4 — Publish

Publish them all in one go — reels shorter than `--short-under` seconds go up tagged `#Shorts`,
longer ones as regular videos:

```bash
.venv\Scripts\python.exe scripts\publish_player_reels.py --prefix lakers_buckets --short-under 90 --privacy unlisted
```

…or publish a single reel:

```bash
.venv\Scripts\python.exe scripts\publish_reel.py --name lakers_buckets_Davis --privacy unlisted
```

Title and description are auto-generated from the reel (e.g. *"James — Buckets vs GSW
(2021-05-19)"*). Override with `--title "..."`. Privacy: `unlisted` (view by link), `private`, or
`public`.

---

## 2. Other use cases (every reel is just a query)

After ingesting, compose any single reel with `compose_reel.py --name <name> <filters>`:

| Goal | Command |
|------|---------|
| One player's buckets | `compose_reel.py --player Davis --game 0052000121 --name ad_buckets` |
| One player's dunks | `compose_reel.py --player Davis --category dunk --name ad_dunks` |
| Everyone's 3-pointers | `compose_reel.py --category three --name all_threes` |
| A player's floaters | `compose_reel.py --player Curry --category floater --name curry_floaters` |
| A player's midrange | `compose_reel.py --player Davis --category midrange --name ad_middies` |
| Q4 buckets (anyone) | `compose_reel.py --period 4 --name q4_buckets` |
| A whole team's buckets (one reel) | `compose_reel.py --team LAL --name lal_all_buckets` |

And the **per-player batch** (`make_player_reels.py --prefix <name>`) takes the same filters — e.g.
every Laker's 3s as separate reels: `make_player_reels.py --team LAL --category three --prefix lal_threes`.

### Across multiple games (after you've ingested more)

The same filters span every game in the library:

| Goal | Command |
|------|---------|
| AD's 3s this season | `compose_reel.py --player Davis --category three --season 2024-25 --name ad_season_3s` |
| AD's December 3s | `compose_reel.py --player Davis --category three --month 12 --name ad_dec_3s` |
| Curry dunks vs the Suns | `compose_reel.py --player Curry --category dunk --opponent PHX --name curry_vs_phx_dunks` |
| A date range | `compose_reel.py --player Davis --from 2025-01-01 --to 2025-01-31 --name ad_jan` |

### Filter reference (shared by `compose_reel` and `make_player_reels`)

`--player` `--team` `--opponent` `--value` (2 or 3) `--subtype` `--category` `--period`
`--season` `--month` (1-12) `--from`/`--to` (ISO dates) `--distance-min`/`--distance-max` `--game`

**Categories:** `dunk`, `layup`, `three`, `two`, `floater`, `midrange` (jump shot 8–22 ft), `paint`.

---

## Clip length

Clips are 8s by default (`[flip-8, flip]`: the bucket lands at the 5s mark, 3s after). To make a
set longer, extend the end without changing anything else, then rebuild the reels:

```bash
.venv\Scripts\python.exe scripts\extend_clips.py --team LAL --game 0052000121 --seconds 2   # 8s -> 10s
.venv\Scripts\python.exe scripts\make_player_reels.py --team LAL --game 0052000121 --prefix lakers_buckets
```

(`extend_clips` takes the same filters as compose, and updates the library so all future reels use
the longer clips.)

## 3. Review & fix details

- `compose_reel.py` prints each clip's library `id`.
- `nudge_clip.py --id <id> --earlier <s>` (or `--later <s>`) re-cuts that clip **in the library**,
  in place. The fix is permanent and flows into every future reel that uses the clip.
- Re-run the compose / `make_player_reels` command to rebuild reels after nudging.

## 4. Publishing to YouTube

- **Connect once:** `youtube_auth.py`. It opens a browser — pick the account, pass *"Google hasn't
  verified this app"* (**Advanced → Go to app → Allow**), then your browser lands on a `localhost`
  page that **fails to load** (expected) — copy that full address-bar URL and paste it back at the
  prompt. A token is saved; future uploads need no browser.
- **Publish one:** `publish_reel.py --name <reel> --privacy unlisted|private|public [--title "..."]`.
  Running it is the approval — review the reel first.
- **Publish a whole set:** `publish_player_reels.py --prefix <prefix> --short-under 90 --privacy unlisted`
  uploads every `{prefix}_*` reel; reels under `--short-under` seconds go up tagged `#Shorts`, the
  rest as regular videos. Quota errors are caught per reel so one failure doesn't stop the batch.
- **Quota:** the documented default is ~6 uploads/day (10,000 units, 1,600/upload) — but in
  practice a full 10-reel batch uploaded fine, so quota is project-dependent; just run it and the
  batch reports any failures.
- **For true Shorts, build vertical reels:** YouTube only files **vertical/square** videos as
  Shorts. Add `--vertical` to `compose_reel.py` or `make_player_reels.py` to produce 9:16 reels
  (the 16:9 play centered with a blurred fill top/bottom — nothing cropped), e.g.
  `make_player_reels.py --team LAL --game 0052000121 --prefix lakers_shorts --vertical`. Then
  `publish_player_reels.py --prefix lakers_shorts --short-under 90` uploads them tagged `#Shorts`.

## 5. Adding more games

Repeat Step 1 (`ingest_game.py`) for each game — each is clipped once into the library, and
season/career reels then come from a single query spanning everything ingested.

> **Note:** ingest currently works on the calibrated **`espn`** broadcast profile. A game from a
> different broadcast needs its scoreboard located first (a per-broadcast profile in
> `scorebug_regions.py`) — that's Track B, the next build. See [STRATEGY.md](STRATEGY.md).
