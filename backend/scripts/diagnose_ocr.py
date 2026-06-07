"""Quick diagnostic: run clock OCR on a short sample and dump crops for inspection.

Usage:
    python scripts/diagnose_ocr.py                  # first 5 minutes
    python scripts/diagnose_ocr.py --start 0 --end 300
    python scripts/diagnose_ocr.py --start 1800 --end 2100  # sample Q2

Output:
    backend/data/outputs/0052000121/ocr_diag/
        ├── frame_XXXX_crop_clock.jpg   ← what OCR sees (clock region only)
        ├── frame_XXXX_crop_period.jpg  ← what OCR sees (period region only)
        └── readings.txt                ← OCR results table
"""

import argparse
import os
import subprocess
import sys
import tempfile

# Allow running from repo root or from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import easyocr

from app.utils.scorebug_regions import get_profile

_reader = None
def get_reader():
    global _reader
    if _reader is None:
        print("Loading EasyOCR model...")
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader
from app.services.clock_ocr_service import ClockOCRService

VIDEO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "uploads", "0052000121", "full_game.mp4"
)
OUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "data", "outputs", "0052000121", "ocr_diag"
)


def extract_sample_frames(video_path, out_dir, start_sec, end_sec, interval=5):
    """Extract one frame every `interval` seconds between start and end."""
    os.makedirs(out_dir, exist_ok=True)

    duration = end_sec - start_sec
    frames_extracted = []

    for i, t in enumerate(range(start_sec, end_sec, interval)):
        out_path = os.path.join(out_dir, f"frame_{t:06d}.jpg")
        cmd = [
            "ffmpeg",
            "-ss", str(t),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(out_path):
            frames_extracted.append(f"frame_{t:06d}.jpg")
        else:
            print(f"  Warning: could not extract frame at {t}s")

        if (i + 1) % 10 == 0:
            print(f"  Extracted {i+1} frames...")

    print(f"Extracted {len(frames_extracted)} frames ({start_sec}s–{end_sec}s every {interval}s)")
    return sorted(frames_extracted)


def run_ocr_on_frames(frames, frame_dir, profile_name="tnt"):
    profile = get_profile(profile_name)
    service = ClockOCRService(profile_name)

    cx, cy, cw, ch = profile["clock_region"]
    px, py, pw, ph = profile["period_region"]

    results = []
    for fname in frames:
        fpath = os.path.join(frame_dir, fname)
        img = cv2.imread(fpath)
        if img is None:
            continue

        h, w = img.shape[:2]

        # Save full frame thumbnail
        thumb = cv2.resize(img, (640, 360))
        cv2.imwrite(os.path.join(frame_dir, f"thumb_{fname}"), thumb)

        # Save clock crop
        clock_crop = img[cy:cy+ch, cx:cx+cw]
        gray_clock = cv2.cvtColor(clock_crop, cv2.COLOR_BGR2GRAY)
        thresh_clock = cv2.adaptiveThreshold(
            gray_clock, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2,
        )
        cv2.imwrite(os.path.join(frame_dir, f"clock_{fname}"), thresh_clock)
        cv2.imwrite(os.path.join(frame_dir, f"clock_raw_{fname}"), clock_crop)

        # Save period crop
        period_crop = img[py:py+ph, px:px+pw]
        cv2.imwrite(os.path.join(frame_dir, f"period_{fname}"), period_crop)

        # OCR the clock using EasyOCR
        big = cv2.resize(clock_crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        ocr_out = get_reader().readtext(big, detail=0, allowlist="0123456789:.")
        raw_text = "".join(c for c in "".join(ocr_out) if c in "0123456789:.")

        parsed = service._parse_clock_text(raw_text)

        results.append({
            "frame": fname,
            "raw_ocr": raw_text,
            "parsed_seconds": parsed,
            "frame_size": f"{w}x{h}",
            "clock_region": f"({cx},{cy},{cw},{ch})",
        })

        status = f"OK: {parsed:.0f}s remaining" if parsed is not None else "FAILED"
        print(f"  {fname}: raw='{raw_text}' -> {status}")

    return results


def write_report(results, out_dir):
    report_path = os.path.join(out_dir, "readings.txt")
    with open(report_path, "w") as f:
        f.write(f"{'Frame':<20} {'Raw OCR':<12} {'Parsed (s)':<12} {'Status'}\n")
        f.write("-" * 60 + "\n")
        for r in results:
            parsed = r["parsed_seconds"]
            status = f"{parsed:.0f}s" if parsed is not None else "FAILED"
            f.write(f"{r['frame']:<20} {r['raw_ocr']:<12} {status:<12}\n")

    ok = sum(1 for r in results if r["parsed_seconds"] is not None)
    total = len(results)
    print(f"\nResults: {ok}/{total} frames parsed successfully")
    print(f"Report: {report_path}")
    print(f"Crops: {out_dir}")
    print("\nCheck clock_*.jpg files to see what OCR is working with.")
    print("If crops look wrong, adjust clock_region in scorebug_regions.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="Start second (default 0)")
    parser.add_argument("--end", type=int, default=300, help="End second (default 300 = 5 min)")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between frames (default 10)")
    parser.add_argument("--profile", default="tnt", help="Broadcast profile (default tnt)")
    args = parser.parse_args()

    video_path = os.path.abspath(VIDEO_PATH)
    if not os.path.exists(video_path):
        print(f"Video not found: {video_path}")
        sys.exit(1)

    out_dir = os.path.abspath(OUT_DIR)
    print(f"Video: {video_path}")
    print(f"Output: {out_dir}")
    print(f"Profile: {args.profile}")
    print(f"Sample: {args.start}s – {args.end}s, every {args.interval}s\n")

    frames = extract_sample_frames(video_path, out_dir, args.start, args.end, args.interval)
    if not frames:
        print("No frames extracted — check FFmpeg output above.")
        sys.exit(1)

    print(f"\nRunning OCR on {len(frames)} frames...")
    results = run_ocr_on_frames(frames, out_dir, args.profile)
    write_report(results, out_dir)


if __name__ == "__main__":
    main()
