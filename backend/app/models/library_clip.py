from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint
from sqlalchemy.sql import func

from app.db.database import Base


class LibraryClip(Base):
    """One row per clipped made shot — the queryable clip library.

    Denormalized on purpose: every dimension a reel might filter on lives on the row, so
    composing a reel ("AD all 3s this season") is a single query with no joins and no
    reprocessing. Raw API fields are stored as-is; categories (midrange, etc.) are derived
    at query time. Dedup key is (nba_game_id, action_id).
    """

    __tablename__ = "library_clips"
    __table_args__ = (UniqueConstraint("nba_game_id", "action_id", name="uq_game_action"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    # identity / dedup
    nba_game_id = Column(String, nullable=False, index=True)
    action_id = Column(Integer, nullable=True)

    # who / where
    player_name = Column(String, nullable=False, index=True)
    team = Column(String, index=True)
    opponent = Column(String, index=True)
    home_team = Column(String)
    away_team = Column(String)
    game_date = Column(String, nullable=True, index=True)  # ISO date when known
    season = Column(String, nullable=True, index=True)

    # what
    event_type = Column(String)                       # made_shot
    shot_subtype = Column(String, index=True)         # dunk/layup/jump_shot/three_pointer/hook_shot
    sub_type_raw = Column(String)                     # API subType, e.g. "Cutting Dunk Shot"
    shot_distance = Column(Integer, nullable=True)
    shot_value = Column(Integer, nullable=True, index=True)  # 2 or 3
    loc_x = Column(Integer, nullable=True)
    loc_y = Column(Integer, nullable=True)

    # when-in-game
    period = Column(Integer)
    game_clock = Column(String)
    score_after = Column(String)

    # plumbing
    video_second = Column(Float)                      # confirmed score-flip second
    clip_start = Column(Float)
    clip_end = Column(Float)
    adjust_seconds = Column(Float, default=0.0)       # cumulative manual review nudge (− earlier / + later)
    file_path = Column(String, nullable=True)
    confidence = Column(String)                       # high | low
    broadcast_profile = Column(String)
    created_at = Column(DateTime, default=func.now())
