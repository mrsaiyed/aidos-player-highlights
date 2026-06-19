"""Render per-player highlight reels by concatenating a player's clips in game order."""

import logging

from app.utils.ffmpeg import concatenate_clips

logger = logging.getLogger(__name__)


class RenderService:
    def render_reel(self, clip_paths: list[str], output_path: str) -> str | None:
        """Concatenate clip_paths (already in game order) into one reel. Returns path or None."""
        if not clip_paths:
            return None
        if len(clip_paths) == 1:
            # A single-clip reel is just the clip; still re-encode via concat for uniformity.
            pass
        ok = concatenate_clips(clip_paths, output_path)
        if ok:
            logger.info("Rendered reel: %s (%d clips)", output_path, len(clip_paths))
            return output_path
        logger.warning("Failed to render reel: %s", output_path)
        return None
