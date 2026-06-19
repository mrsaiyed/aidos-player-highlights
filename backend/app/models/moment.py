from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class Moment(Base):
    __tablename__ = "moments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    player_name = Column(String, nullable=False)
    team = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    event_subtype = Column(String, nullable=True)
    period = Column(Integer, nullable=False)
    game_clock = Column(String, nullable=False)
    description = Column(String, nullable=True)
    score_before = Column(String, nullable=True)
    score_after = Column(String, nullable=True)
    video_time_seconds = Column(Float, nullable=True)
    importance_score = Column(Integer, default=0)
    status = Column(String, default="pending")
    refinement_method = Column(String, nullable=True)
    confidence = Column(String, nullable=True)  # "high" | "low" from the flip detector
    transition_lead_seconds = Column(Float, nullable=True)  # extra pre-roll for steal/transition plays
    created_at = Column(DateTime, default=func.now())
