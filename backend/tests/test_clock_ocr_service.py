"""Tests for the ClockOCRService — clock parsing, filtering, and table lookup."""

from app.services.clock_ocr_service import ClockOCRService, ClockReading, ClockTable


class TestClockTextParsing:

    def setup_method(self):
        self.service = ClockOCRService()

    def test_parse_standard_clock(self):
        assert self.service._parse_clock_text("8:14") == 494.0

    def test_parse_double_digit_minutes(self):
        assert self.service._parse_clock_text("11:02") == 662.0

    def test_parse_twelve_minutes(self):
        assert self.service._parse_clock_text("12:00") == 720.0

    def test_parse_zero_clock(self):
        assert self.service._parse_clock_text("0:00") == 0.0

    def test_parse_single_digit_minute(self):
        assert self.service._parse_clock_text("1:30") == 90.0

    def test_reject_invalid_minutes(self):
        assert self.service._parse_clock_text("13:00") is None

    def test_reject_invalid_seconds(self):
        assert self.service._parse_clock_text("5:62") is None

    def test_reject_garbage(self):
        assert self.service._parse_clock_text("abc") is None

    def test_reject_empty(self):
        assert self.service._parse_clock_text("") is None

    def test_reject_single_number(self):
        assert self.service._parse_clock_text("42") is None

    def test_strips_whitespace(self):
        assert self.service._parse_clock_text("  8:14  ") == 494.0


class TestReadingFilter:

    def setup_method(self):
        self.service = ClockOCRService()

    def _reading(self, video_sec, period, clock_remaining):
        return ClockReading(
            video_second=video_sec,
            period=period,
            clock_remaining=clock_remaining,
        )

    def test_keeps_normal_sequence(self):
        readings = [
            self._reading(0, 1, 720),
            self._reading(2, 1, 718),
            self._reading(4, 1, 716),
        ]
        result = self.service._filter_readings(readings)
        assert len(result) == 3

    def test_removes_impossible_forward_jump(self):
        """Clock can't go from 500 to 520 (clock went forward = time reversed)."""
        readings = [
            self._reading(0, 1, 720),
            self._reading(2, 1, 718),
            self._reading(4, 1, 740),  # jumped forward by 22 — garbage
            self._reading(6, 1, 714),
        ]
        result = self.service._filter_readings(readings)
        assert len(result) == 3
        assert result[-1].video_second == 6

    def test_removes_huge_backward_jump(self):
        """Clock dropping 200s in one frame is OCR garbage."""
        readings = [
            self._reading(0, 1, 720),
            self._reading(2, 1, 718),
            self._reading(4, 1, 500),  # dropped 218 — garbage
            self._reading(6, 1, 714),
        ]
        result = self.service._filter_readings(readings)
        assert len(result) == 3

    def test_allows_moderate_backward_jump(self):
        """A timeout can freeze clock for ~60 real seconds, then resume normally."""
        readings = [
            self._reading(0, 1, 400),
            self._reading(2, 1, 398),
            self._reading(60, 1, 396),  # 60s gap in video time but only 2s clock — fine
        ]
        result = self.service._filter_readings(readings)
        assert len(result) == 3

    def test_removes_period_regression(self):
        """Q3 -> Q1 is always garbage."""
        readings = [
            self._reading(0, 1, 720),
            self._reading(2000, 3, 400),
            self._reading(2002, 1, 718),  # regression to Q1 — garbage
            self._reading(2004, 3, 398),
        ]
        result = self.service._filter_readings(readings)
        assert len(result) == 3
        assert all(r.period != 1 or r.video_second == 0 for r in result)


class TestClockTableLookup:

    def _reading(self, video_sec, period, clock_remaining):
        return ClockReading(
            video_second=video_sec,
            period=period,
            clock_remaining=clock_remaining,
        )

    def test_exact_match(self):
        table = ClockTable(readings=[
            self._reading(100, 1, 500),
            self._reading(200, 1, 400),
            self._reading(300, 1, 300),
        ])
        result = table.lookup(1, 400)
        assert result == 200

    def test_interpolation(self):
        table = ClockTable(readings=[
            self._reading(100, 1, 500),
            self._reading(200, 1, 400),
        ])
        # 450 is halfway between 500 and 400 → video should be ~150
        result = table.lookup(1, 450)
        assert result is not None
        assert abs(result - 150) < 1.0

    def test_wrong_period_returns_none(self):
        table = ClockTable(readings=[
            self._reading(100, 1, 500),
            self._reading(200, 1, 400),
        ])
        result = table.lookup(3, 500)
        assert result is None

    def test_empty_table_returns_none(self):
        table = ClockTable()
        assert table.lookup(1, 500) is None

    def test_single_reading_uses_offset(self):
        table = ClockTable(readings=[
            self._reading(100, 2, 500),
        ])
        # With 1:1 offset: video_second + (clock_reading - clock_target) = 100 + 20 = 120
        result = table.lookup(2, 480)
        assert result == 120


class TestGapDetection:

    def setup_method(self):
        self.service = ClockOCRService()

    def _reading(self, video_sec, period=1, clock_remaining=500):
        return ClockReading(
            video_second=video_sec,
            period=period,
            clock_remaining=clock_remaining,
        )

    def test_finds_gap_at_start(self):
        readings = [self._reading(100), self._reading(102)]
        gaps = self.service._find_gaps(readings, 200)
        # Should find gap from 0 to 100
        assert any(g[0] == 0 and g[1] == 100 for g in gaps)

    def test_finds_gap_between_readings(self):
        readings = [self._reading(10), self._reading(100)]
        gaps = self.service._find_gaps(readings, 110)
        assert any(g[0] == 10 and g[1] == 100 for g in gaps)

    def test_no_gaps_in_tight_sequence(self):
        readings = [self._reading(i * 2) for i in range(50)]
        gaps = self.service._find_gaps(readings, 100)
        # Only gap should be at the end (100 - 98 = 2, under threshold)
        assert all(g[1] - g[0] >= 10 for g in gaps)

    def test_empty_readings_one_big_gap(self):
        gaps = self.service._find_gaps([], 5000)
        assert gaps == [(0.0, 5000)]
