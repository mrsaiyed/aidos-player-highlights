"""Ingest a game into the clip library.

Runs the sealed clip engine over ALL made shots for BOTH teams, cuts a clip per shot, and
writes a denormalized LibraryClip row per shot (dedup on game_id + action_id). The library is
the durable store; reels are queries over it. Takes a broadcast profile per game.
"""

import logging
import os
from types import SimpleNamespace

from app.models.library_clip import LibraryClip
from app.services.nba_service import NBAService
from app.services.refinement_service import RefinementService
from app.services.clip_service import ClipService
from app.utils.ffmpeg import cut_clip, get_video_duration
from app.utils.paths import get_game_output_dir, sanitize_player_name

logger = logging.getLogger(__name__)


class _NoopDB:
    """The detection chain commits its working moments; the library write is separate, so
    we hand the chain a no-op session and keep the moment objects in memory."""

    def add(self, *_):
        pass

    def commit(self):
        pass

    def refresh(self, *_):
        pass


class IngestService:
    def __init__(self, profile_name: str = "espn"):
        self.profile_name = profile_name

    def ingest(self, nba_game_id: str, video_path: str, db, cut_clips: bool = True) -> dict:
        # profile="auto" -> discover the scoreboard for this broadcast from the API scores
        if self.profile_name == "auto":
            from app.services.autocalibrate_service import auto_calibrate
            from app.utils.scorebug_regions import register_profile
            logger.info("Auto-calibrating broadcast for %s ...", nba_game_id)
            prof = auto_calibrate(video_path, nba_game_id)
            if not prof:
                raise RuntimeError("Auto-calibration could not locate the scoreboard")
            self.profile_name = f"auto_{nba_game_id}"
            register_profile(self.profile_name, prof)

        nba = NBAService()
        events = nba.fetch_play_by_play(nba_game_id)
        home, away = nba.home_tricode, nba.away_tricode
        season = nba.season_from_game_id(nba_game_id)
        game_date = nba.fetch_game_date(nba_game_id)

        made = [e for e in events if e.get("event_type") == "made_shot"]
        moments = [self._event_to_moment(e) for e in made]
        logger.info(
            "Ingest %s — %d made shots (%s vs %s, %s, %s)",
            nba_game_id, len(made), home, away, season, game_date or "date n/a",
        )

        summary = RefinementService(self.profile_name).refine_moments(
            0, nba_game_id, moments, _NoopDB(), use_watch_fallback=False, video_path=video_path
        )

        duration = get_video_duration(video_path)
        clipper = ClipService()
        lib_root = os.path.join(get_game_output_dir(nba_game_id), "library")

        clipped = 0
        for m in moments:
            opponent = away if m.team == home else home
            row = self._upsert(db, nba_game_id, m, opponent, home, away, season, game_date)
            if cut_clips and m.video_time_seconds is not None:
                start, end = clipper.calculate_clip_bounds(m.video_time_seconds, duration)
                # group by team so players are separated by team in the library
                player_dir = os.path.join(lib_root, m.team or "UNK", sanitize_player_name(m.player_name))
                os.makedirs(player_dir, exist_ok=True)
                clock_tag = (m.game_clock or "").replace(":", "m") + "s"
                fname = f"a{m.action_id}_{clock_tag}_{m.event_subtype or 'shot'}.mp4"
                out_path = os.path.join(player_dir, fname)
                ok = cut_clip(video_path, out_path, start, end)
                row.clip_start, row.clip_end = start, end
                row.file_path = out_path if ok else None
                clipped += 1 if ok else 0
            db.commit()

        return {
            "game": nba_game_id, "home": home, "away": away, "season": season,
            "game_date": game_date, "made_shots": len(made),
            "confirmed": summary["confirmed"], "flagged": summary["flagged"],
            "clipped": clipped,
        }

    def _event_to_moment(self, e: dict) -> SimpleNamespace:
        return SimpleNamespace(
            player_name=e.get("player_name"), team=e.get("team"),
            event_type=e.get("event_type"), event_subtype=e.get("event_subtype"),
            period=e.get("period"), game_clock=e.get("game_clock"),
            score_before=e.get("score_before"), score_after=e.get("score_after"),
            description=e.get("description"),
            action_id=e.get("action_id"), shot_distance=e.get("shot_distance"),
            shot_value=e.get("shot_value"), sub_type=e.get("sub_type"),
            loc_x=e.get("loc_x"), loc_y=e.get("loc_y"),
            video_time_seconds=None, refinement_method=None, confidence=None, status="pending",
        )

    def _upsert(self, db, game_id, m, opponent, home, away, season, game_date) -> LibraryClip:
        row = None
        if m.action_id is not None:
            row = db.query(LibraryClip).filter_by(nba_game_id=game_id, action_id=m.action_id).first()
        if row is None:
            row = LibraryClip(nba_game_id=game_id, action_id=m.action_id)
            db.add(row)
        row.player_name = m.player_name
        row.team = m.team
        row.opponent = opponent
        row.home_team = home
        row.away_team = away
        row.game_date = game_date
        row.season = season
        row.event_type = m.event_type
        row.shot_subtype = m.event_subtype
        row.sub_type_raw = m.sub_type
        row.shot_distance = m.shot_distance
        row.shot_value = m.shot_value
        row.loc_x = m.loc_x
        row.loc_y = m.loc_y
        row.period = m.period
        row.game_clock = m.game_clock
        row.score_after = m.score_after
        row.video_second = m.video_time_seconds
        row.confidence = m.confidence
        row.broadcast_profile = self.profile_name
        return row
