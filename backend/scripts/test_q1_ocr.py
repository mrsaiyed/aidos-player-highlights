"""Q1 Hybrid Pipeline Test

OCR pass builds clock table, resolves all events. HIGH confidence events
get a +3s offset and clip directly. MEDIUM/LOW confidence events go through
Claude Watch for precise timestamp verification on a tight ~15s window.

Usage:
    python scripts/test_q1_ocr.py
"""

import glob
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import easyocr

from app.services.nba_service import NBAService
from app.services.clock_ocr_service import ClockOCRService, ClockReading, ClockTable
from app.utils.scorebug_regions import get_profile
from app.utils.ffmpeg import cut_clip, get_video_duration
from app.utils.constants import (
    CLIP_PRE_ROLL_SECONDS,
    CLIP_POST_ROLL_SECONDS,
    OCR_HIGH_CONFIDENCE_OFFSET,
)

CLIPS_OUT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "data", "outputs", "0052000121", "ocr_q1_clips"
))

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
        result = subprocess.run(
            ["C:/Windows/system32/ffmpeg.EXE",
             "-ss", str(t),
             "-i", video_path,
             "-vframes", "1", "-q:v", "2", "-y", out],
            capture_output=True,
        )
        if result.returncode == 0 and os.path.exists(out):
            frames.append((t, out))
        if (i + 1) % 100 == 0:
            print(f"  Extracted {i+1}/{len(timestamps)} frames...")
    return frames


def ocr_frames(frames, profile_name="espn"):
    profile = get_profile(profile_name)
    cx, cy, cw, ch = profile["clock_region"]
    service = ClockOCRService(profile_name)

    print("Loading EasyOCR model...")
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    print("Model loaded.\n")

    raw_readings = []
    failed = 0

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
                video_second=float(t),
                period=1,
                clock_remaining=clock_remaining,
                raw_text=raw_text,
            ))
        else:
            failed += 1

    print(f"OCR complete: {len(raw_readings)} parseable / {len(frames)} frames "
          f"({failed} failed/empty)")
    return raw_readings


def build_table(raw_readings):
    service = ClockOCRService("espn")
    clean = service._filter_readings(raw_readings)
    gaps = service._find_gaps(clean, Q1_SCAN_END)
    table = ClockTable(readings=clean, gaps=gaps)
    print(f"Clock table: {len(clean)} clean readings, {len(gaps)} gaps\n")
    return table


def parse_game_clock(clock_str):
    parts = clock_str.split(":")
    if len(parts) != 2:
        return 0.0
    return int(parts[0]) * 60 + float(parts[1])


def resolve_events(events, table):
    results = []
    for e in events:
        clock_remaining = parse_game_clock(e["game_clock"])
        video_sec = table.lookup(period=1, clock_remaining=clock_remaining)

        if video_sec is not None and table.readings:
            nearest_gap = min(abs(r.clock_remaining - clock_remaining) for r in table.readings)
            if nearest_gap <= 5:
                confidence = "HIGH"
            elif nearest_gap <= 30:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"
        else:
            confidence = "FAILED"

        results.append({
            "player": e["player_name"],
            "clock": e["game_clock"],
            "subtype": e.get("event_subtype") or "2pt",
            "score_change": f"{e['score_before']} -> {e['score_after']}",
            "score_before": e["score_before"],
            "score_after": e["score_after"],
            "period": e["period"],
            "video_sec": video_sec,
            "confidence": confidence,
        })
    return results


def run_watch_verify(video_path, result):
    """Use Claude Watch to find exact score-change timestamp in a tight window."""
    watch_script = Path.home() / ".claude" / "skills" / "watch" / "scripts" / "watch.py"
    if not watch_script.exists():
        print(f"  Watch script not found at {watch_script}")
        return None

    # Tight window: 10s before OCR estimate to 8s after
    center = result["video_sec"]
    start_s = max(0, int(center - 10))
    end_s = int(center + 8)
    start_mmss = f"{start_s // 60}:{start_s % 60:02d}"
    end_mmss = f"{end_s // 60}:{end_s % 60:02d}"

    prompt = (
        f"Q{result['period']} {result['clock']} remaining. "
        f"{result['player']} {result['subtype']}. "
        f"Score before: {result['score_before']}. "
        f"Score after: {result['score_after']}. "
        f"Find when score changes from {result['score_before']} "
        f"to {result['score_after']}. "
        f"Reply ONLY: FOUND: <seconds> or NOT_FOUND"
    )

    try:
        proc = subprocess.run(
            [
                "python", str(watch_script),
                video_path,
                "--start", start_mmss,
                "--end", end_mmss,
                "--no-whisper",
                "--fps", "2",
                "--resolution", "1024",
                "--max-frames", "60",
                "--question", prompt,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        print(f"  Watch timed out for [{start_mmss}, {end_mmss}]")
        return None
    except Exception as exc:
        print(f"  Watch error: {exc}")
        return None

    output = proc.stdout + proc.stderr
    match = re.search(r"FOUND:\s*(\d+(?:\.\d+)?)", output, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def apply_hybrid_resolution(results, video_path):
    """Apply +3s offset to HIGH confidence, Claude Watch to MEDIUM/LOW."""
    print("\n--- Hybrid Resolution ---")

    for r in results:
        if r["video_sec"] is None:
            continue

        if r["confidence"] == "HIGH":
            r["video_sec"] += OCR_HIGH_CONFIDENCE_OFFSET
            r["method"] = "ocr+offset"
            print(f"  {r['player']:20s} {r['clock']}  HIGH  -> +{OCR_HIGH_CONFIDENCE_OFFSET}s offset -> {r['video_sec']:.1f}s")
        else:
            print(f"  {r['player']:20s} {r['clock']}  {r['confidence']:<6s} -> Claude Watch [{r['video_sec']-10:.0f}s-{r['video_sec']+8:.0f}s]...", end="", flush=True)
            watch_result = run_watch_verify(video_path, r)
            if watch_result is not None:
                r["video_sec"] = watch_result
                r["confidence"] = "VERIFIED"
                r["method"] = "ocr+watch"
                print(f" FOUND at {watch_result:.1f}s")
            else:
                # Fall back to OCR + offset
                r["video_sec"] += OCR_HIGH_CONFIDENCE_OFFSET
                r["method"] = "ocr+offset(fallback)"
                print(f" NOT_FOUND, using offset -> {r['video_sec']:.1f}s")

    print()


def print_results(results):
    method_col = any("method" in r for r in results)
    print("=" * 80)
    header = f"{'Clock':>7}  {'Player':<22} {'Type':<14} {'Video Sec':>10}  {'Conf'}"
    if method_col:
        header += f"      {'Method'}"
    print(header)
    print("-" * 80)
    for r in results:
        if r["video_sec"] is not None:
            vs = f"{r['video_sec']:.1f}s  ({int(r['video_sec'])//60}:{int(r['video_sec'])%60:02d})"
        else:
            vs = "NOT FOUND"
        line = f"{r['clock']:>7}  {r['player']:<22} {r['subtype']:<14} {vs:>16}  {r['confidence']}"
        if method_col and "method" in r:
            line += f"  {r['method']}"
        print(line)
    print("=" * 80)

    resolved = sum(1 for r in results if r["video_sec"] is not None)
    verified = sum(1 for r in results if r.get("confidence") == "VERIFIED")
    high = sum(1 for r in results if r["confidence"] == "HIGH")
    print(f"\nResolved: {resolved}/{len(results)}  |  HIGH: {high}  VERIFIED: {verified}")


def clear_old_clips():
    if os.path.exists(CLIPS_OUT_DIR):
        for f in glob.glob(os.path.join(CLIPS_OUT_DIR, "*.mp4")):
            os.remove(f)


def cut_clips(results, video_path):
    clear_old_clips()
    os.makedirs(CLIPS_OUT_DIR, exist_ok=True)
    duration = get_video_duration(video_path)
    print(f"\nCutting clips -> {CLIPS_OUT_DIR}\n")

    for i, r in enumerate(results, start=1):
        if r["video_sec"] is None:
            print(f"  [{i}] SKIP {r['player']} {r['clock']} -- no timestamp")
            continue

        start = max(0.0, r["video_sec"] - CLIP_PRE_ROLL_SECONDS)
        end = min(duration, r["video_sec"] + CLIP_POST_ROLL_SECONDS)

        clock_tag = r["clock"].replace(":", "m") + "s"
        safe_player = re.sub(r"[^\w]", "_", r["player"])
        filename = f"{i:02d}_{safe_player}_{clock_tag}_{r['subtype']}.mp4"
        out_path = os.path.join(CLIPS_OUT_DIR, filename)

        success = cut_clip(video_path, out_path, start, end)
        status = "OK" if success else "FAILED"
        print(f"  [{i}] {status}  {filename}  ({start:.1f}s - {end:.1f}s)")


def main():
    if not os.path.exists(VIDEO_PATH):
        print(f"Video not found: {VIDEO_PATH}")
        sys.exit(1)

    print(f"Video: {VIDEO_PATH}")
    print(f"Scanning 0s - {Q1_SCAN_END}s every {SAMPLE_INTERVAL}s "
          f"({Q1_SCAN_END // SAMPLE_INTERVAL} frames)\n")

    # Step 1: Fetch Q1 LAL buckets from NBA API
    print("Fetching Q1 LAL scoring plays from NBA API...")
    nba = NBAService()
    events = nba.fetch_play_by_play("0052000121")
    q1_lal = [e for e in events
               if e["period"] == 1
               and e.get("team") == "LAL"
               and e["event_type"] == "made_shot"]
    print(f"Found {len(q1_lal)} Q1 LAL scoring plays.\n")

    # Step 2: Extract frames
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Extracting frames to temp dir...")
        frames = extract_frames(VIDEO_PATH, tmpdir, Q1_SCAN_END, SAMPLE_INTERVAL)
        print(f"Extracted {len(frames)} frames.\n")

        # Step 3: OCR
        raw_readings = ocr_frames(frames, profile_name="espn")

    # Step 4: Build clock table
    table = build_table(raw_readings)

    # Step 5: Resolve events (OCR only)
    results = resolve_events(q1_lal, table)

    # Step 6: Hybrid resolution — offset HIGH, Watch verify MEDIUM/LOW
    apply_hybrid_resolution(results, VIDEO_PATH)

    # Step 7: Print final results
    print("Q1 LAL Scoring Plays - Hybrid Resolved Timestamps")
    print_results(results)

    # Step 8: Cut clips
    cut_clips(results, VIDEO_PATH)
    print(f"\nDone. Open:  {CLIPS_OUT_DIR}")


if __name__ == "__main__":
    main()
