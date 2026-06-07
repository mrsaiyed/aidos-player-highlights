import json
import os
import re

from app.utils.paths import MOCK_DIR

EVENT_TYPE_MAP = {
    1: "made_shot",
    2: "missed_shot",
    3: "free_throw",
    4: "rebound",
    5: "turnover",
    6: "foul",
    10: "jump_ball",
    12: "start_period",
    13: "end_period",
}


class NBAService:
    def fetch_play_by_play(self, nba_game_id: str) -> list[dict]:
        try:
            from nba_api.stats.endpoints import playbyplayv3

            pbp = playbyplayv3.PlayByPlayV3(game_id=nba_game_id)
            df = pbp.get_data_frames()[0]
            raw_events = df.to_dict(orient="records")
        except Exception:
            raw_events = self.load_mock_play_by_play()

        return self._build_score_context(raw_events)

    def _build_score_context(self, raw_events: list[dict]) -> list[dict]:
        prev_home, prev_away = "0", "0"
        normalized = []
        for raw in raw_events:
            event = self.normalize_event(raw)
            curr_home = str(raw.get("scoreHome") or prev_home)
            curr_away = str(raw.get("scoreAway") or prev_away)
            # scoreHome = LAL score, scoreAway = GSW score for game 0052000121
            event["score_before"] = f"LAL {prev_home} GSW {prev_away}"
            event["score_after"] = f"LAL {curr_home} GSW {curr_away}"
            prev_home, prev_away = curr_home, curr_away
            normalized.append(event)
        return normalized

    def load_mock_play_by_play(self) -> list[dict]:
        real_path = os.path.join(MOCK_DIR, "real_play_by_play.json")
        sample_path = os.path.join(MOCK_DIR, "play_by_play_sample.json")
        path = real_path if os.path.exists(real_path) else sample_path
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def normalize_event(self, raw_event: dict) -> dict:
        clock = raw_event.get("clock", "")
        if clock and str(clock).startswith("PT"):
            return self._normalize_real_api_event(raw_event)
        if "EVENTMSGTYPE" in raw_event:
            return self._normalize_nba_api_event(raw_event)
        return self._normalize_mock_event(raw_event)

    def _parse_pt_clock(self, clock: str) -> str:
        match = re.match(r"PT(\d+)M([\d.]+)S", clock)
        if not match:
            return "12:00"
        minutes = int(match.group(1))
        seconds = int(float(match.group(2)))
        return f"{minutes}:{seconds:02d}"

    def _normalize_real_api_event(self, raw_event: dict) -> dict:
        description = raw_event.get("description") or ""
        is_field_goal = raw_event.get("isFieldGoal") == 1
        shot_result = raw_event.get("shotResult")

        if is_field_goal and shot_result == "Made":
            event_type = "made_shot"
        elif is_field_goal:
            event_type = "missed_shot"
        else:
            event_type = (raw_event.get("actionType") or "other").lower()

        if event_type == "turnover" and "STEAL" in description.upper():
            event_type = "steal"
        elif event_type == "missed_shot" and "BLOCK" in description.upper():
            event_type = "block"

        event_subtype = None
        if event_type == "made_shot":
            event_subtype = self._detect_shot_subtype(description)

        return {
            "player_name": raw_event.get("playerName") or "",
            "team": raw_event.get("teamTricode") or None,
            "event_type": event_type,
            "event_subtype": event_subtype,
            "period": int(raw_event.get("period", 0)),
            "game_clock": self._parse_pt_clock(raw_event.get("clock", "")),
            "description": description,
        }

    def _normalize_nba_api_event(self, raw_event: dict) -> dict:
        event_type_num = raw_event.get("EVENTMSGTYPE")
        event_type = EVENT_TYPE_MAP.get(event_type_num, "other")

        home_desc = raw_event.get("HOMEDESCRIPTION") or ""
        visitor_desc = raw_event.get("VISITORDESCRIPTION") or ""
        description = home_desc or visitor_desc

        if event_type == "turnover" and "STEAL" in description.upper():
            event_type = "steal"
        elif event_type == "missed_shot" and "BLOCK" in description.upper():
            event_type = "block"

        event_subtype = None
        if event_type == "made_shot":
            event_subtype = self._detect_shot_subtype(description)

        player_name = raw_event.get("PLAYER1_NAME") or ""
        team = self._detect_team(home_desc, visitor_desc)

        period = int(raw_event.get("PERIOD", 0))
        game_clock = raw_event.get("PCTIMESTRING") or "12:00"

        return {
            "player_name": player_name,
            "team": team,
            "event_type": event_type,
            "event_subtype": event_subtype,
            "period": period,
            "game_clock": game_clock,
            "description": description,
        }

    def _normalize_mock_event(self, raw_event: dict) -> dict:
        event_type = raw_event.get("event_type", "other")
        description = raw_event.get("description", "")

        event_subtype = None
        if event_type == "made_shot":
            event_subtype = self._detect_shot_subtype(description)

        return {
            "player_name": raw_event.get("player_name", ""),
            "team": raw_event.get("team"),
            "event_type": event_type,
            "event_subtype": event_subtype,
            "period": int(raw_event.get("period", 0)),
            "game_clock": raw_event.get("clock", "12:00"),
            "description": description,
        }

    def _detect_shot_subtype(self, description: str) -> str | None:
        desc_upper = description.upper()
        if "3PT" in desc_upper or "THREE" in desc_upper:
            return "three_pointer"
        if "DUNK" in desc_upper:
            return "dunk"
        if "LAYUP" in desc_upper:
            return "layup"
        if "JUMP SHOT" in desc_upper:
            return "jump_shot"
        if "FLOATING" in desc_upper:
            return "jump_shot"
        if "HOOK" in desc_upper:
            return "hook_shot"
        return None

    def _detect_team(self, home_desc: str, visitor_desc: str) -> str | None:
        if home_desc:
            return "LAL"
        if visitor_desc:
            return "GSW"
        return None
