"""Compose layer — turn a library query into a stitched reel.

"Reels are queries": filter LibraryClip on any stored dimension, gather the matching (confirmed)
clips in game order, copy them into their own folder, and concatenate into one reel. Named shot
categories (midrange, floater, paint) are derived from the raw API fields at query time, so no
re-ingest is needed to support a new filter.
"""

import json
import logging
import os
import shutil

from sqlalchemy import func

from app.models.library_clip import LibraryClip
from app.services.render_service import RenderService
from app.utils.ffmpeg import to_vertical
from app.utils.paths import sanitize_player_name

logger = logging.getLogger(__name__)


def _parse_clock(clock: str) -> float:
    parts = (clock or "").split(":")
    if len(parts) != 2:
        return 0.0
    try:
        return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return 0.0


class ComposeService:
    # Named categories derived from raw fields (subtype + distance + API sub_type_raw).
    def _apply_category(self, q, category: str):
        c = category.lower()
        if c in ("dunk", "dunks"):
            return q.filter(LibraryClip.shot_subtype == "dunk")
        if c in ("layup", "layups"):
            return q.filter(LibraryClip.shot_subtype == "layup")
        if c in ("three", "threes", "3", "3pt"):
            return q.filter(LibraryClip.shot_value == 3)
        if c in ("two", "twos", "2", "2pt"):
            return q.filter(LibraryClip.shot_value == 2)
        if c in ("floater", "floaters", "float"):
            return q.filter(LibraryClip.sub_type_raw.ilike("%float%"))
        if c in ("midrange", "middy", "middies"):
            return q.filter(LibraryClip.shot_subtype == "jump_shot",
                            LibraryClip.shot_distance >= 8, LibraryClip.shot_distance <= 22)
        if c in ("paint", "close"):
            return q.filter(LibraryClip.shot_distance <= 8)
        raise ValueError(f"unknown category '{category}'")

    def query(self, db, *, confirmed_only: bool = True, **f) -> list[LibraryClip]:
        q = db.query(LibraryClip)
        if confirmed_only:
            q = q.filter(LibraryClip.file_path.isnot(None))
        if f.get("player"):     q = q.filter(LibraryClip.player_name == f["player"])
        if f.get("team"):       q = q.filter(LibraryClip.team == f["team"])
        if f.get("opponent"):   q = q.filter(LibraryClip.opponent == f["opponent"])
        if f.get("value"):      q = q.filter(LibraryClip.shot_value == f["value"])
        if f.get("subtype"):    q = q.filter(LibraryClip.shot_subtype == f["subtype"])
        if f.get("period"):     q = q.filter(LibraryClip.period == f["period"])
        if f.get("season"):     q = q.filter(LibraryClip.season == f["season"])
        if f.get("game"):       q = q.filter(LibraryClip.nba_game_id == f["game"])
        if f.get("distance_min") is not None: q = q.filter(LibraryClip.shot_distance >= f["distance_min"])
        if f.get("distance_max") is not None: q = q.filter(LibraryClip.shot_distance <= f["distance_max"])
        if f.get("date_from"):  q = q.filter(LibraryClip.game_date >= f["date_from"])
        if f.get("date_to"):    q = q.filter(LibraryClip.game_date <= f["date_to"])
        if f.get("month"):      q = q.filter(func.substr(LibraryClip.game_date, 6, 2) == f"{int(f['month']):02d}")
        if f.get("category"):   q = self._apply_category(q, f["category"])

        clips = q.all()
        # Chronological: date, game, period, then most game-time remaining first.
        clips.sort(key=lambda c: (c.game_date or "", c.nba_game_id, c.period or 0,
                                  -_parse_clock(c.game_clock)))
        return clips

    def build_reel(self, clips: list[LibraryClip], out_dir: str, name: str,
                   filters: dict | None = None, vertical: bool = False) -> dict:
        """Copy clips into out_dir (game order), stitch into {name}.mp4, and write {name}.json
        metadata (players/teams/dates/filters) so the publish step can auto-title the reel.

        vertical=True converts the reel to a 9:16 frame (blurred-pad) for YouTube Shorts.
        """
        os.makedirs(out_dir, exist_ok=True)
        copied = []
        for i, c in enumerate(clips, 1):
            if not c.file_path or not os.path.exists(c.file_path):
                logger.warning("Missing clip file for id=%s: %s", c.id, c.file_path)
                continue
            clock_tag = (c.game_clock or "").replace(":", "m")
            dest = os.path.join(out_dir, f"{i:02d}_{sanitize_player_name(c.player_name)}_Q{c.period}_{clock_tag}s.mp4")
            shutil.copy(c.file_path, dest)
            copied.append(dest)

        reel = os.path.join(out_dir, f"{name}.mp4")
        ok = None
        if copied and vertical:
            tmp = os.path.join(out_dir, f"_{name}_h.mp4")
            if RenderService().render_reel(copied, tmp):
                ok = to_vertical(tmp, reel)
            if os.path.exists(tmp):
                os.remove(tmp)
        elif copied:
            ok = RenderService().render_reel(copied, reel)

        meta = self._reel_meta(name, clips, filters or {})
        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return {"folder": out_dir, "reel": reel if ok else None, "clips": len(copied), "meta": meta}

    @staticmethod
    def _reel_meta(name: str, clips: list[LibraryClip], filters: dict) -> dict:
        def uniq(attr):
            return sorted({getattr(c, attr) for c in clips if getattr(c, attr)})
        dates = uniq("game_date")
        return {
            "name": name,
            "filters": {k: v for k, v in filters.items() if k != "name"},
            "clip_count": len(clips),
            "players": uniq("player_name"),
            "teams": uniq("team"),
            "opponents": uniq("opponent"),
            "seasons": uniq("season"),
            "date_min": dates[0] if dates else None,
            "date_max": dates[-1] if dates else None,
            "clips": [
                {"id": c.id, "player": c.player_name, "period": c.period,
                 "clock": c.game_clock, "subtype": c.shot_subtype, "value": c.shot_value}
                for c in clips
            ],
        }
