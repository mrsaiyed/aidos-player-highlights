import logging
import os

from app.utils.ffmpeg import cut_clip, get_video_duration
from app.utils.paths import (
    get_game_upload_dir,
    get_clips_dir,
)
from app.utils.constants import (
    SCORE_FLIP_LAG_SECONDS,
    CLIP_LEAD_SECONDS,
    CLIP_TRAIL_SECONDS,
    MAX_CLIPS_PER_PLAYER,
)
from app.models.clip import Clip

logger = logging.getLogger(__name__)


class ClipService:

    def calculate_clip_bounds(
        self,
        video_time_seconds: float,
        video_duration: float,
        transition_lead: float | None = None,
    ) -> tuple[float, float]:
        """Dynamic bounds anchored on the score flip.

        video_time_seconds is the scorebug score-flip second; the ball goes through the net
        ~SCORE_FLIP_LAG_SECONDS earlier, so we anchor on `net` and pad CLIP_LEAD before /
        CLIP_TRAIL after — the ball lands CLIP_LEAD seconds into the clip.

        transition_lead is accepted for a future "start at the steal" mode but is NOT used by
        the default pipeline: v2 review showed a uniform 5-before-net window is what works, and
        extra lead bloated transition clips. The detection is still stored on the moment for
        when that smart mode is built.
        """
        net = video_time_seconds - SCORE_FLIP_LAG_SECONDS
        lead = CLIP_LEAD_SECONDS
        if transition_lead:
            lead = max(lead, transition_lead)
        start = max(0.0, net - lead)
        end = min(video_duration, net + CLIP_TRAIL_SECONDS)
        return start, end

    def get_top_moments_per_player(
        self,
        moments: list,
        max_per_player: int = MAX_CLIPS_PER_PLAYER,
    ) -> list:
        by_player: dict[str, list] = {}
        for moment in moments:
            by_player.setdefault(moment.player_name, []).append(moment)

        selected = []
        for player_moments in by_player.values():
            sorted_moments = sorted(
                player_moments,
                key=lambda m: m.importance_score,
                reverse=True,
            )
            selected.extend(sorted_moments[:max_per_player])
        return selected

    def generate_clips(
        self,
        game_id: int,
        nba_game_id: str,
        moments: list,
        db,
    ) -> list[Clip]:
        upload_dir = get_game_upload_dir(nba_game_id)
        video_path = os.path.join(upload_dir, "full_game.mp4")
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        video_duration = get_video_duration(video_path)
        selected_moments = self.get_top_moments_per_player(moments)
        total = len(selected_moments)
        clips = []

        for i, moment in enumerate(selected_moments, start=1):
            logger.info(
                "Cutting clip %d of %d for player %s",
                i, total, moment.player_name,
            )

            # Guard: no video timestamp
            if moment.video_time_seconds is None:
                clip = Clip(
                    game_id=game_id,
                    moment_id=moment.id,
                    player_name=moment.player_name,
                    start_seconds=0.0,
                    end_seconds=0.0,
                    duration_seconds=0.0,
                    file_path=None,
                    status="skipped",
                    error_message="no video timestamp",
                )
                db.add(clip)
                db.commit()
                db.refresh(clip)
                clips.append(clip)
                continue

            # Uniform 5-before-net window (validated in v2 review). Transition lead is detected
            # and stored on the moment but not applied here yet — see calculate_clip_bounds.
            start, end = self.calculate_clip_bounds(
                moment.video_time_seconds, video_duration
            )

            # Guard: invalid bounds
            if start >= end:
                clip = Clip(
                    game_id=game_id,
                    moment_id=moment.id,
                    player_name=moment.player_name,
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=0.0,
                    file_path=None,
                    status="skipped",
                    error_message="invalid clip bounds",
                )
                db.add(clip)
                db.commit()
                db.refresh(clip)
                clips.append(clip)
                continue

            clips_dir = get_clips_dir(nba_game_id, moment.player_name)
            filename = f"clip_{moment.id:03d}.mp4"
            output_path = os.path.join(clips_dir, filename)

            success = cut_clip(video_path, output_path, start, end)

            clip = Clip(
                game_id=game_id,
                moment_id=moment.id,
                player_name=moment.player_name,
                start_seconds=start,
                end_seconds=end,
                duration_seconds=end - start,
                file_path=output_path if success else None,
                status="generated" if success else "failed",
                error_message=None if success else "FFmpeg cut failed",
            )
            db.add(clip)
            db.commit()
            db.refresh(clip)
            clips.append(clip)

        return clips
