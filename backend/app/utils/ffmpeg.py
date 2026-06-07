import re
import shutil
import subprocess
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_tool(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        sibling = Path(ffmpeg).parent / f"{name}.exe"
        if sibling.exists():
            return str(sibling)
    return None


def _duration_from_ffmpeg(video_path: str) -> float:
    ffmpeg = _resolve_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    probe = subprocess.run(
        [ffmpeg, "-i", video_path],
        capture_output=True,
        text=True,
    )
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        probe.stderr,
    )
    if not match:
        raise RuntimeError(
            f"Could not parse duration for {video_path}: {probe.stderr}"
        )
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def cut_clip(
    input_path: str,
    output_path: str,
    start_seconds: float,
    end_seconds: float,
) -> bool:
    """Cut a clip from input_path between start and end seconds."""
    ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"
    duration = end_seconds - start_seconds
    cmd = [
        ffmpeg,
        "-ss", str(start_seconds),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        "-y",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stderr:
        logger.debug("FFmpeg stderr: %s", result.stderr)
    if result.returncode == 0:
        logger.info("Successfully cut clip: %s", output_path)
        return True
    logger.info("Failed to cut clip: %s", output_path)
    return False


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    ffprobe = _resolve_tool("ffprobe")
    if ffprobe:
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        raise RuntimeError(
            f"ffprobe failed for {video_path}: {result.stderr}"
        )
    return _duration_from_ffmpeg(video_path)


def concatenate_clips(
    clip_paths: list[str],
    output_path: str,
) -> bool:
    """Concatenate multiple clips into one video."""
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            temp_file = f.name
            for clip_path in clip_paths:
                f.write(f"file '{clip_path}'\n")

        ffmpeg = _resolve_tool("ffmpeg") or "ffmpeg"
        cmd = [
            ffmpeg,
            "-f", "concat",
            "-safe", "0",
            "-i", temp_file,
            "-c", "copy",
            "-y",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stderr:
            logger.debug("FFmpeg stderr: %s", result.stderr)
        if result.returncode == 0:
            logger.info("Successfully concatenated clips to: %s", output_path)
            return True
        logger.info("Failed to concatenate clips to: %s", output_path)
        return False
    finally:
        if temp_file:
            Path(temp_file).unlink(missing_ok=True)
