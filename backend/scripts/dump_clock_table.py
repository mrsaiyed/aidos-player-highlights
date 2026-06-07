"""Dump the clock table readings around problem events to see what OCR captured."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import easyocr

from app.services.clock_ocr_service import ClockOCRService, ClockReading, ClockTable
from app.utils.scorebug_regions import get_profile

VIDEO_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "data", "uploads", "0052000121", "full_game.mp4"
))

Q1_SCAN_END = 1300
SAMPLE_INTERVAL = 2


def extract_frames(video_path, out_dir, end_sec, interval):
    os.makedirs(out_dir, exist_ok=True)
    timestamps = list(range(0, end_sec, interval))
    frames = []
    for i, t in enumerate(timestamps):
        out = os.path.join(out_dir, f"f_{t:05d}.jpg")
        subprocess.run(
            ["C:/Windows/system32/ffmpeg.EXE", "-ss", str(t), "-i", video_path,
             "-vframes", "1", "-q:v", "2", "-y", out],
            capture_output=True,
        )
        if os.path.exists(out):
            frames.append((t, out))
        if (i + 1) % 100 == 0:
            print(f"  Extracted {i+1}/{len(timestamps)}...")
    return frames


def ocr_frames(frames):
    profile = get_profile("espn")
    cx, cy, cw, ch = profile["clock_region"]
    service = ClockOCRService("espn")
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    raw_readings = []
    for t, fpath in frames:
        img = cv2.imread(fpath)
        if img is None:
            continue
        crop = img[cy:cy + ch, cx:cx + cw]
        big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        try:
            ocr_out = reader.readtext(big, detail=0, allowlist="0123456789:.")
            raw_text = "".join(c for c in "".join(ocr_out) if c in "0123456789:.")
        except Exception:
            raw_text = ""

        clock_remaining = service._parse_clock_text(raw_text)
        if clock_remaining is not None:
            raw_readings.append(ClockReading(
                video_second=float(t), period=1,
                clock_remaining=clock_remaining, raw_text=raw_text,
            ))

    return raw_readings


def main():
    print("Extracting 650 frames...")
    with tempfile.TemporaryDirectory() as tmpdir:
        frames = extract_frames(VIDEO_PATH, tmpdir, Q1_SCAN_END, SAMPLE_INTERVAL)
        print(f"Extracted {len(frames)} frames, running OCR...")
        raw = ocr_frames(frames)

    service = ClockOCRService("espn")
    clean = service._filter_readings(raw)

    # Problem windows: CaldwellPope 4:43 (confirmed=687s), Davis 0:55 (confirmed=1176s)
    windows = [
        ("CaldwellPope 4:43", 650, 730),
        ("Davis 0:55", 1140, 1260),
    ]

    for label, start, end in windows:
        print(f"\n{'='*60}")
        print(f"{label} — raw readings in video range {start}-{end}s:")
        print(f"{'Video':>7}  {'Raw':>8}  {'Parsed':>8}  {'Kept?'}")
        print(f"{'-'*40}")
        raw_in_window = [r for r in raw if start <= r.video_second <= end]
        clean_set = {(r.video_second, r.clock_remaining) for r in clean}
        for r in raw_in_window:
            kept = "YES" if (r.video_second, r.clock_remaining) in clean_set else "no"
            mins = int(r.clock_remaining) // 60
            secs = int(r.clock_remaining) % 60
            print(f"  {r.video_second:6.0f}s  {r.raw_text:>8}  {mins}:{secs:02d} ({r.clock_remaining:.0f}s)  {kept}")

        clean_in_window = [r for r in clean if start <= r.video_second <= end]
        print(f"\nClean readings in window: {len(clean_in_window)}")
        # Show nearest clean readings on either side
        before = [r for r in clean if r.video_second < start]
        after = [r for r in clean if r.video_second > end]
        if before:
            r = before[-1]
            print(f"Nearest before: t={r.video_second:.0f}s clock={r.clock_remaining:.0f}s ({int(r.clock_remaining)//60}:{int(r.clock_remaining)%60:02d})")
        if after:
            r = after[0]
            print(f"Nearest after:  t={r.video_second:.0f}s clock={r.clock_remaining:.0f}s ({int(r.clock_remaining)//60}:{int(r.clock_remaining)%60:02d})")


if __name__ == "__main__":
    main()
