from app.models.moment import Moment
from app.utils.constants import TRANSITION_MAX_LEAD_SECONDS

# A steal/turnover this many game-seconds before a made shot marks the same fast-break
# possession, so the clip needs extra lead to capture the start of the play.
TRANSITION_TRIGGER_TYPES = ("steal", "turnover")
TRANSITION_MAX_GAP_SECONDS = 8.0   # trigger must be within this of the shot to count
TRANSITION_TRIGGER_BUFFER = 2.0    # extra seconds so the trigger event itself is in frame
TRANSITION_LOOKBACK_EVENTS = 3     # how many preceding events to scan


class MomentService:
    HIGHLIGHT_RULES = {
        "three_pointer": 80,
        "dunk": 90,
        "block": 85,
        "steal": 75,
        "layup": 40,
        "jump_shot": 30,
    }

    MINIMUM_IMPORTANCE = 70

    def process_events(
        self,
        events: list[dict],
        game_id: int,
        db,
        mode: str = "buckets",
    ) -> list:
        moments = []
        for idx, event in enumerate(events):
            if not self.is_highlight_worthy(event, mode=mode):
                continue
            score = self.score_event(event)
            moment = Moment(
                game_id=game_id,
                player_name=event["player_name"],
                team=event.get("team"),
                event_type=event["event_type"],
                event_subtype=event.get("event_subtype"),
                period=event["period"],
                game_clock=event["game_clock"],
                description=event.get("description"),
                score_before=event.get("score_before"),
                score_after=event.get("score_after"),
                importance_score=score,
                transition_lead_seconds=self._transition_lead(events, idx),
                status="pending",
            )
            db.add(moment)
            moments.append(moment)
        db.commit()
        for moment in moments:
            db.refresh(moment)
        return moments

    def is_highlight_worthy(
        self,
        event: dict,
        mode: str = "highlights",
    ) -> bool:
        event_type = event.get("event_type")
        event_subtype = event.get("event_subtype")

        if mode == "buckets":
            return event_type == "made_shot"

        if event_type == "made_shot" and event_subtype in ["three_pointer", "dunk"]:
            return True
        if event_type in ["block", "steal"]:
            return True
        if self._is_clutch_score(event):
            return True
        return False

    def score_event(self, event: dict) -> int:
        event_type = event.get("event_type")
        event_subtype = event.get("event_subtype")

        if event_type in ["block", "steal"]:
            base_score = self.HIGHLIGHT_RULES.get(event_subtype or event_type, 0)
            if event_subtype is None:
                base_score = self.HIGHLIGHT_RULES.get(event_type, 0)
        else:
            base_score = self.HIGHLIGHT_RULES.get(event_subtype, 0)

        if self._is_clutch_score(event):
            base_score += 20

        return min(base_score, 100)

    def _is_clutch_score(self, event: dict) -> bool:
        if event.get("period") != 4:
            return False
        if event.get("event_type") != "made_shot":
            return False
        minutes = self._parse_clock_minutes(event.get("game_clock", "12:00"))
        return minutes <= 2

    def _parse_clock_minutes(self, game_clock: str) -> int:
        parts = game_clock.split(":")
        return int(parts[0])

    def _parse_clock_seconds(self, game_clock: str) -> float:
        parts = game_clock.split(":")
        if len(parts) != 2:
            return 0.0
        try:
            return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return 0.0

    def _transition_lead(self, events: list[dict], idx: int) -> float | None:
        """Extra clip pre-roll if this made shot came off a fast-break trigger.

        Scans the preceding events for a steal/turnover in the same period within
        TRANSITION_MAX_GAP_SECONDS of game time. A turnover/steal immediately before a
        made shot means the bucket came off that change of possession (the scoring team
        got the ball), so the clip should start early enough to show the steal and the
        break. Returns the lead in seconds (capped), or None for a normal half-court play.
        """
        shot_clock = self._parse_clock_seconds(events[idx].get("game_clock", ""))
        shot_period = events[idx].get("period")
        for j in range(idx - 1, max(-1, idx - 1 - TRANSITION_LOOKBACK_EVENTS), -1):
            prior = events[j]
            if prior.get("period") != shot_period:
                break
            if prior.get("event_type") not in TRANSITION_TRIGGER_TYPES:
                continue
            gap = self._parse_clock_seconds(prior.get("game_clock", "")) - shot_clock
            if 0.0 <= gap <= TRANSITION_MAX_GAP_SECONDS:
                return min(gap + TRANSITION_TRIGGER_BUFFER, TRANSITION_MAX_LEAD_SECONDS)
        return None
