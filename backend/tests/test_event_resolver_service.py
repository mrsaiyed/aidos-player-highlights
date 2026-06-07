"""Tests for EventResolverService — confidence assessment and clock parsing."""

from app.services.event_resolver_service import EventResolverService
from app.services.clock_ocr_service import ClockReading, ClockTable


class TestConfidenceAssessment:

    def setup_method(self):
        self.service = EventResolverService()

    def _reading(self, video_sec, period, clock_remaining):
        return ClockReading(
            video_second=video_sec,
            period=period,
            clock_remaining=clock_remaining,
        )

    def test_high_confidence_when_reading_nearby(self):
        table = ClockTable(readings=[
            self._reading(100, 1, 502),
            self._reading(102, 1, 500),
            self._reading(104, 1, 498),
        ])
        assert self.service._assess_confidence(1, 500, table) == "high"

    def test_medium_confidence_when_reading_within_30s(self):
        table = ClockTable(readings=[
            self._reading(100, 1, 520),  # 20s away from target
        ])
        assert self.service._assess_confidence(1, 500, table) == "medium"

    def test_low_confidence_when_readings_far_away(self):
        table = ClockTable(readings=[
            self._reading(100, 1, 600),  # 100s away
        ])
        assert self.service._assess_confidence(1, 500, table) == "low"

    def test_low_confidence_when_no_readings_for_period(self):
        table = ClockTable(readings=[
            self._reading(100, 1, 500),
        ])
        assert self.service._assess_confidence(3, 400, table) == "low"


class TestGameClockParsing:

    def setup_method(self):
        self.service = EventResolverService()

    def test_parse_standard(self):
        assert self.service._parse_game_clock("8:14") == 494.0

    def test_parse_zero(self):
        assert self.service._parse_game_clock("0:00") == 0.0

    def test_parse_twelve(self):
        assert self.service._parse_game_clock("12:00") == 720.0

    def test_parse_with_decimal(self):
        assert self.service._parse_game_clock("0:58") == 58.0

    def test_parse_garbage(self):
        assert self.service._parse_game_clock("invalid") == 0.0

    def test_parse_empty(self):
        assert self.service._parse_game_clock("") == 0.0
