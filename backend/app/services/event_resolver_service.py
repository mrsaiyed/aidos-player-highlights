"""Event Resolver Service — maps NBA API scoring events to video timestamps.

Takes the ClockTable from ClockOCRService and the list of Moments from
MomentService, resolves each moment's video_time_seconds using the clock
lookup table, assigns a confidence level, and optionally falls back to
Claude Watch for low-confidence events.
"""

import logging
import os

from app.services.clock_ocr_service import ClockOCRService, ClockTable
from app.utils.constants import (
    RESOLVER_HIGH_CONFIDENCE_GAP,
    RESOLVER_MEDIUM_CONFIDENCE_GAP,
    QUARTER_DURATION_SECONDS,
)
from app.utils.paths import get_game_upload_dir

logger = logging.getLogger(__name__)


class EventResolverService:

    def __init__(self, profile_name: str | None = None):
        self.ocr_service = ClockOCRService(profile_name)
        self._clock_table: ClockTable | None = None

    def resolve_moments(
        self,
        game_id: int,
        nba_game_id: str,
        moments: list,
        db,
    ) -> dict:
        """Main entry point: build clock table, then resolve all moments."""
        upload_dir = get_game_upload_dir(nba_game_id)
        video_path = os.path.join(upload_dir, "full_game.mp4")
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        # Step 1: Build the clock table (one-pass OCR)
        logger.info("Building clock table for %s...", nba_game_id)
        self._clock_table = self.ocr_service.build_clock_table(video_path)
        logger.info(
            "Clock table built: %d readings, %d gaps",
            len(self._clock_table.readings),
            len(self._clock_table.gaps),
        )

        # Step 2: Resolve each moment
        sorted_moments = sorted(
            moments,
            key=lambda m: (m.period, -self._parse_game_clock(m.game_clock)),
        )

        high = 0
        medium = 0
        low = 0
        failed = 0

        for moment in sorted_moments:
            clock_remaining = self._parse_game_clock(moment.game_clock)
            video_second = self._clock_table.lookup(moment.period, clock_remaining)

            if video_second is not None:
                confidence = self._assess_confidence(
                    moment.period, clock_remaining, self._clock_table
                )
                moment.video_time_seconds = video_second
                moment.refinement_method = f"clock_ocr_{confidence}"
                moment.status = "refined" if confidence != "low" else "unconfirmed"

                if confidence == "high":
                    high += 1
                elif confidence == "medium":
                    medium += 1
                else:
                    low += 1

                logger.info(
                    "Resolved %s Q%d %s -> %.1fs (%s confidence)",
                    moment.player_name, moment.period, moment.game_clock,
                    video_second, confidence,
                )
            else:
                moment.status = "unresolved"
                moment.refinement_method = "clock_ocr_failed"
                failed += 1
                logger.warning(
                    "FAILED to resolve %s Q%d %s — no clock readings for this period/time",
                    moment.player_name, moment.period, moment.game_clock,
                )

            db.add(moment)
            db.commit()
            db.refresh(moment)

        return {
            "total": len(sorted_moments),
            "high_confidence": high,
            "medium_confidence": medium,
            "low_confidence": low,
            "failed": failed,
            "clock_readings": len(self._clock_table.readings),
            "gaps": len(self._clock_table.gaps),
        }

    def _assess_confidence(
        self,
        period: int,
        clock_remaining: float,
        table: ClockTable,
    ) -> str:
        """Assess confidence based on how close the nearest readings are."""
        period_readings = [r for r in table.readings if r.period == period]
        if not period_readings:
            return "low"

        # Find nearest reading distance (in game clock seconds)
        min_distance = float("inf")
        for r in period_readings:
            dist = abs(r.clock_remaining - clock_remaining)
            if dist < min_distance:
                min_distance = dist

        if min_distance <= RESOLVER_HIGH_CONFIDENCE_GAP:
            return "high"
        elif min_distance <= RESOLVER_MEDIUM_CONFIDENCE_GAP:
            return "medium"
        else:
            return "low"

    def _parse_game_clock(self, clock: str) -> float:
        """Parse 'MM:SS' or 'M:SS' into seconds remaining."""
        parts = clock.split(":")
        if len(parts) != 2:
            return 0.0
        try:
            return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return 0.0
