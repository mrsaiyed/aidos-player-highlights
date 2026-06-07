"""Clock OCR Service — single-pass game clock extraction from video frames.

Samples frames at regular intervals, crops the scorebug clock region,
runs Tesseract OCR, filters junk readings, and builds a lookup table
mapping video seconds to (period, clock_remaining_seconds).
"""

import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field

import cv2

from app.utils.constants import (
    CLOCK_OCR_SAMPLE_INTERVAL,
    CLOCK_OCR_MAX_JUMP_FORWARD,
    QUARTER_DURATION_SECONDS,
)
from app.utils.ffmpeg import get_video_duration, _resolve_tool
from app.utils.scorebug_regions import get_profile

# EasyOCR reader is expensive to initialize — create once at module level
_easyocr_reader = None

def _get_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        logger.info("Initializing EasyOCR reader (one-time download if first run)...")
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        logger.info("EasyOCR reader ready.")
    return _easyocr_reader

logger = logging.getLogger(__name__)


@dataclass
class ClockReading:
    video_second: float
    period: int
    clock_remaining: float  # seconds remaining in the period
    raw_text: str = ""
    confidence: float = 0.0


@dataclass
class ClockTable:
    readings: list[ClockReading] = field(default_factory=list)
    gaps: list[tuple[float, float]] = field(default_factory=list)  # (start, end) of no-scorebug stretches

    def lookup(self, period: int, clock_remaining: float) -> float | None:
        """Find the video second for a given game clock time.

        Uses 1:1 offset from the nearest reading rather than linear interpolation
        when the bracketing readings span a dead-ball gap. During dead ball
        (timeouts, commercials, replays), video time advances but game clock
        doesn't — so linear interpolation places events in the middle of dead
        ball, producing large errors. The 1:1 offset assumes the event happened
        during live play near the closest reading, which is almost always correct
        because scoring events only happen during live play when the scorebug is
        visible.
        """
        period_readings = [r for r in self.readings if r.period == period]
        if not period_readings:
            return None

        # Readings are sorted by video_second ascending.
        # clock_remaining decreases as video_second increases.
        # Find the two readings that bracket the target clock_remaining.
        before = None
        after = None
        for r in period_readings:
            if r.clock_remaining >= clock_remaining:
                before = r
            if r.clock_remaining <= clock_remaining and after is None:
                after = r

        # Exact-ish match
        if before and abs(before.clock_remaining - clock_remaining) < 1.0:
            return before.video_second
        if after and abs(after.clock_remaining - clock_remaining) < 1.0:
            return after.video_second

        # Two bracketing readings available
        if before and after and before is not after:
            clock_range = before.clock_remaining - after.clock_remaining
            if clock_range <= 0:
                return before.video_second
            video_range = after.video_second - before.video_second

            # Dead-ball ratio: how much faster video time advances vs game clock.
            # Ratio ~1.0 means continuous live play; >1.3 means dead ball in the gap.
            dead_ball_ratio = video_range / clock_range if clock_range > 0 else 999

            if dead_ball_ratio <= 1.3:
                # Continuous play — linear interpolation is accurate
                fraction = (before.clock_remaining - clock_remaining) / clock_range
                return before.video_second + fraction * video_range
            else:
                # Dead-ball gap — always offset from the "before" reading.
                # Scoring events happen during live play. The "before" reading
                # marks the end of a live-play stretch; after the event, dead
                # ball starts (timeout, commercial). So the event is always
                # near "before", not near "after".
                offset = before.clock_remaining - clock_remaining
                return before.video_second + offset

        # Only one side — use 1:1 offset from closest
        if before:
            return before.video_second + (before.clock_remaining - clock_remaining)
        if after:
            return after.video_second - (clock_remaining - after.clock_remaining)
        return None


class ClockOCRService:

    def __init__(self, profile_name: str | None = None):
        self.profile = get_profile(profile_name)

    def build_clock_table(self, video_path: str) -> ClockTable:
        """Run the full OCR pipeline on a video and return the clock table."""
        duration = get_video_duration(video_path)
        logger.info("Video duration: %.1fs, sampling every %.1fs", duration, CLOCK_OCR_SAMPLE_INTERVAL)

        raw_readings = self._sample_and_ocr(video_path, duration)
        logger.info("Raw OCR readings: %d", len(raw_readings))

        clean_readings = self._filter_readings(raw_readings)
        logger.info("Clean readings after filtering: %d", len(clean_readings))

        gaps = self._find_gaps(clean_readings, duration)
        logger.info("Detected %d gaps (commercial/halftime stretches)", len(gaps))

        table = ClockTable(readings=clean_readings, gaps=gaps)
        return table

    def _sample_and_ocr(self, video_path: str, duration: float) -> list[ClockReading]:
        """Extract frames and run OCR on the clock region."""
        readings = []
        interval = CLOCK_OCR_SAMPLE_INTERVAL
        num_samples = int(duration / interval)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Extract all frames in one FFmpeg call for efficiency
            frame_pattern = os.path.join(tmpdir, "frame_%06d.jpg")
            self._extract_frames(video_path, frame_pattern, interval)

            for i in range(num_samples):
                video_second = i * interval
                frame_path = os.path.join(tmpdir, f"frame_{i + 1:06d}.jpg")
                if not os.path.exists(frame_path):
                    continue

                reading = self._ocr_frame(frame_path, video_second)
                if reading:
                    readings.append(reading)

                if (i + 1) % 500 == 0:
                    logger.info("Processed %d / %d frames", i + 1, num_samples)

        return readings

    def _extract_frames(self, video_path: str, output_pattern: str, interval: float):
        """Extract one frame every `interval` seconds using FFmpeg."""
        ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"
        cmd = [
            ffmpeg,
            "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-q:v", "2",
            "-y",
            output_pattern,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error("FFmpeg frame extraction failed: %s", result.stderr[-500:])
            raise RuntimeError("Frame extraction failed")

    def _ocr_frame(self, frame_path: str, video_second: float) -> ClockReading | None:
        """Crop the clock region from a frame and OCR it using EasyOCR.

        EasyOCR's CRAFT+CRNN pipeline handles the heavy ESPN scorebug font
        reliably. Tesseract LSTM misidentifies ~88% of frames on this font.
        """
        img = cv2.imread(frame_path)
        if img is None:
            return None

        x, y, w, h = self.profile["clock_region"]
        clock_crop = img[y:y + h, x:x + w]

        # Upscale 4x — EasyOCR accuracy improves on larger images
        big = cv2.resize(clock_crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

        try:
            reader = _get_reader()
            results = reader.readtext(big, detail=0, allowlist="0123456789:.")
            raw_text = "".join(results)
        except Exception:
            return None

        digits_only = "".join(c for c in raw_text if c in "0123456789:.")
        if not digits_only:
            return None

        clock_remaining = self._parse_clock_text(digits_only)
        if clock_remaining is None:
            return None

        period = self._ocr_period(img)

        return ClockReading(
            video_second=video_second,
            period=period,
            clock_remaining=clock_remaining,
            raw_text=digits_only,
            confidence=1.0,
        )

    def _ocr_period(self, img) -> int:
        """Try to OCR the period/quarter number. Returns 0 if unreadable."""
        x, y, w, h = self.profile["period_region"]
        crop = img[y:y + h, x:x + w]
        big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        try:
            reader = _get_reader()
            results = reader.readtext(big, detail=0, allowlist="1234")
            text = "".join(results).strip()
        except Exception:
            return 0
        # Period text is like "1st", "2nd", "3rd", "4th" — grab the leading digit
        if text and text[0] in "1234":
            return int(text[0])
        return 0

    def _parse_clock_text(self, text: str) -> float | None:
        """Parse OCR output into seconds remaining.

        Accepts several formats produced by LSTM on ESPN scorebugs:
          '11:30'  '11.30'  '1130'  '130'  '8:14'  '814'
        The ESPN scorebug uses a center-dot separator that LSTM renders
        as a non-ASCII char; we strip non-digits/separators before calling this.
        """
        text = text.strip().replace(" ", "")
        if not text:
            return None

        # Replace dot separator with colon
        text = text.replace(".", ":")

        # MM:SS format
        match = re.match(r"^(\d{1,2}):(\d{2})$", text)
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            if minutes <= 12 and seconds <= 59:
                return minutes * 60 + seconds
            return None

        # 4-digit MMSS (no separator): "1130" -> 11:30
        match = re.match(r"^(\d{2})(\d{2})$", text)
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            if minutes <= 12 and seconds <= 59:
                return minutes * 60 + seconds
            return None

        # 3-digit MSS: "814" -> 8:14
        match = re.match(r"^(\d{1})(\d{2})$", text)
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            if seconds <= 59:
                return minutes * 60 + seconds
            return None

        return None

    def _filter_readings(self, readings: list[ClockReading]) -> list[ClockReading]:
        """Remove readings that fail sanity checks.

        Two-pass filter:
        1. Proportional gate: the max allowed clock decrease between two readings
           is proportional to their video-time gap (game clock can't run faster than
           real time). This catches garbage OCR from replay/overlay graphics that
           show plausible-looking but wrong digits.
        2. Outlier sweep: remove readings whose clock value deviates sharply from
           the local trend (median of neighbors).
        """
        if not readings:
            return []

        # Sort by video second
        readings.sort(key=lambda r: r.video_second)

        # --- Pass 1: proportional gate ---
        clean = [readings[0]]
        for i in range(1, len(readings)):
            prev = clean[-1]
            curr = readings[i]

            # Same period: clock should be decreasing (or steady during dead ball)
            if curr.period == prev.period and curr.period > 0:
                video_gap = curr.video_second - prev.video_second
                clock_diff = prev.clock_remaining - curr.clock_remaining

                # Clock went forward (impossible) by too much — small tolerance for OCR jitter
                if clock_diff < -CLOCK_OCR_MAX_JUMP_FORWARD:
                    continue

                # Clock decreased more than the video time gap allows.
                # Game clock runs at most 1:1 with real time, so in N video-seconds
                # the clock can decrease by at most N seconds. Add tolerance for
                # OCR jitter and the sample landing between ticks.
                max_decrease = video_gap + 10.0
                if clock_diff > max_decrease:
                    continue

            # Period regression (Q3 -> Q1) is always garbage
            if curr.period > 0 and prev.period > 0 and curr.period < prev.period:
                continue

            clean.append(curr)

        # --- Pass 2: outlier sweep ---
        # For each reading, compare to median of its ±3 neighbors.
        # If it deviates by more than 30s from the local median, drop it.
        if len(clean) < 7:
            return clean

        final = []
        WINDOW = 3
        OUTLIER_THRESHOLD = 30.0
        for i, r in enumerate(clean):
            neighbors = []
            for j in range(max(0, i - WINDOW), min(len(clean), i + WINDOW + 1)):
                if j != i:
                    neighbors.append(clean[j].clock_remaining)
            if not neighbors:
                final.append(r)
                continue
            neighbors.sort()
            median = neighbors[len(neighbors) // 2]
            if abs(r.clock_remaining - median) <= OUTLIER_THRESHOLD:
                final.append(r)

        return final

    def _infer_periods(self, readings: list[ClockReading]):
        """For readings where period OCR failed (period=0), infer from context.

        Called after initial filtering. Walks forward and assigns period based on
        clock resets (clock jumps from low back to ~720).
        """
        if not readings:
            return

        current_period = 1
        for i, r in enumerate(readings):
            if r.period > 0:
                current_period = r.period
                continue

            # Detect period boundary: clock resets to near 12:00
            if i > 0 and readings[i - 1].clock_remaining < 60 and r.clock_remaining > 600:
                current_period += 1

            r.period = current_period

    def _find_gaps(
        self,
        readings: list[ClockReading],
        duration: float,
        min_gap_seconds: float = 10.0,
    ) -> list[tuple[float, float]]:
        """Find stretches of video where OCR produced no readings (commercials, halftime)."""
        gaps = []
        if not readings:
            return [(0.0, duration)]

        # Gap at the start
        if readings[0].video_second > min_gap_seconds:
            gaps.append((0.0, readings[0].video_second))

        # Gaps between consecutive readings
        for i in range(1, len(readings)):
            gap = readings[i].video_second - readings[i - 1].video_second
            if gap > min_gap_seconds:
                gaps.append((readings[i - 1].video_second, readings[i].video_second))

        # Gap at the end
        if duration - readings[-1].video_second > min_gap_seconds:
            gaps.append((readings[-1].video_second, duration))

        return gaps
