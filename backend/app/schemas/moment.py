from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class MomentResponse(BaseModel):
    id: int
    game_id: int
    player_name: str
    team: Optional[str] = None
    event_type: str
    event_subtype: Optional[str] = None
    period: int
    game_clock: str
    description: Optional[str] = None
    score_before: Optional[str] = None
    score_after: Optional[str] = None
    video_time_seconds: Optional[float] = None
    importance_score: int
    status: str
    refinement_method: Optional[str] = None
    confidence: Optional[str] = None
    transition_lead_seconds: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FetchMomentsResponse(BaseModel):
    count: int
    moments: list[MomentResponse]


class MappedMomentSample(BaseModel):
    player_name: str
    game_clock: str
    video_time_seconds: float


class MapTimelineResponse(BaseModel):
    count: int
    sample: list[MappedMomentSample]
