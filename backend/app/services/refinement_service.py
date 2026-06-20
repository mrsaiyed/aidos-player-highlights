import logging
import os
import re
import subprocess
from pathlib import Path

from app.services.score_change_detector import find_score_transition
from app.utils.paths import get_game_upload_dir

logger = logging.getLogger(__name__)

Q1_TIP_OFF_SECOND = 28.0
Q1_CLOCK_START = 720.0  # 12:00 in seconds remaining


class RefinementService:
    """Sequential anchor chain (Phase 5A), driven by the deterministic score-flip detector.

    Plays are processed in game order. Each is located by scanning FORWARD from the last
    confirmed position for the frame where the scorebug score changes score_before ->
    score_after (the score signature). Confirmed timestamps re-anchor the chain, so drift
    resets at every hit and the forward scan stays short.

    This is the codification of what the Phase 5A Claude agent did per play, at ~deterministic
    cost instead of a ~2-min `watch.py` call each. A play the detector can't confirm is flagged
    (confidence="low") for review; the anchor is NOT advanced, so the next play simply scans
    forward for its own signature — one miss does not cascade. `watch.py` remains an optional
    fallback (default OFF) to recover flagged plays unattended.
    """

    def __init__(self, profile_name: str | None = "espn"):
        self.profile_name = profile_name

    def refine_moments(
        self,
        game_id: int,
        nba_game_id: str,
        moments: list,
        db,
        use_watch_fallback: bool = False,
        video_path: str | None = None,
    ) -> dict:
        if video_path is None:
            video_path = os.path.join(get_game_upload_dir(nba_game_id), "full_game.mp4")
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        # True game order: period ascending, clock descending (most remaining = earliest).
        sorted_moments = sorted(
            moments,
            key=lambda m: (m.period, -self._parse_game_clock(m.game_clock)),
        )

        last_confirmed_second = Q1_TIP_OFF_SECOND
        high = 0
        low = 0

        for moment in sorted_moments:
            logger.info(
                "Q%d %s %s — forward scan from %.0fs (%s -> %s)",
                moment.period, moment.player_name, moment.game_clock,
                last_confirmed_second, moment.score_before, moment.score_after,
            )
            result = find_score_transition(
                video_path, last_confirmed_second,
                moment.score_before or "", moment.score_after or "",
                self.profile_name,
            )

            if result.verified:
                moment.video_time_seconds = result.video_second
                moment.refinement_method = "score_change"
                moment.confidence = "high"
                moment.status = "refined"
                last_confirmed_second = result.video_second
                high += 1
                logger.info("CONFIRMED %s at %.1fs", moment.player_name, result.video_second)
            else:
                fb = None
                if use_watch_fallback:
                    fb = self._run_watch_scan(video_path, moment, last_confirmed_second)
                if fb is not None:
                    moment.video_time_seconds = fb
                    moment.refinement_method = "watch_confirmed"
                    moment.confidence = "high"
                    moment.status = "refined"
                    last_confirmed_second = fb
                    high += 1
                    logger.info("FALLBACK confirmed %s at %.1fs", moment.player_name, fb)
                else:
                    # Flag for review; do NOT advance the anchor — the next play scans
                    # forward for its own signature, so one miss does not cascade.
                    moment.video_time_seconds = None
                    moment.refinement_method = "unconfirmed"
                    moment.confidence = "low"
                    moment.status = "unconfirmed"
                    low += 1
                    logger.warning("FLAGGED %s — no signature match", moment.player_name)

            db.add(moment)
            db.commit()
            db.refresh(moment)

        return {"total": len(sorted_moments), "confirmed": high, "flagged": low}

    # --- Optional Claude watch fallback (default off) ---

    def _run_watch_scan(self, video_path: str, moment, anchor_second: float) -> float | None:
        start_s = max(0.0, anchor_second)
        end_s = anchor_second + 120
        prompt = (
            f"Q{moment.period} {moment.game_clock} remaining. "
            f"{moment.player_name} {moment.event_subtype or moment.event_type}. "
            f"Find when score changes from {moment.score_before} to {moment.score_after}. "
            f"Reply ONLY: FOUND: <seconds> or NOT_FOUND"
        )
        watch_script = Path.home() / ".claude" / "skills" / "watch" / "scripts" / "watch.py"
        if not watch_script.exists():
            logger.error("watch.py not found at %s", watch_script)
            return None
        try:
            result = subprocess.run(
                [
                    "python", str(watch_script), video_path,
                    "--start", self._seconds_to_mmss(start_s),
                    "--end", self._seconds_to_mmss(end_s),
                    "--no-whisper", "--fps", "2", "--resolution", "1024",
                    "--max-frames", "120", "--question", prompt,
                ],
                capture_output=True, text=True, timeout=180,
            )
        except (subprocess.TimeoutExpired, Exception) as exc:  # noqa: BLE001
            logger.warning("watch.py failed: %s", exc)
            return None
        match = re.search(r"FOUND:\s*(\d+(?:\.\d+)?)", result.stdout + result.stderr, re.IGNORECASE)
        return float(match.group(1)) if match else None

    def _seconds_to_mmss(self, seconds: float) -> str:
        total = int(max(0, seconds))
        return f"{total // 60}:{total % 60:02d}"

    def _parse_game_clock(self, clock: str) -> float:
        parts = clock.split(":")
        if len(parts) != 2:
            return 0.0
        try:
            return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return 0.0
