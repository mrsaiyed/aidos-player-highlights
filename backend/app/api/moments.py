from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.game import Game
from app.models.moment import Moment
from app.models.user import User
from app.schemas.moment import (
    MomentResponse,
    FetchMomentsResponse,
    MapTimelineResponse,
    MappedMomentSample,
)
from app.services.nba_service import NBAService
from app.services.moment_service import MomentService
from app.services.timeline_service import TimelineService
from app.services.event_resolver_service import EventResolverService
from app.utils.auth import get_current_user

router = APIRouter()


@router.get("/games/{game_id}/moments", response_model=list[MomentResponse])
def list_moments(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return db.query(Moment).filter(Moment.game_id == game_id).all()


@router.post("/games/{game_id}/fetch-moments", response_model=FetchMomentsResponse)
def fetch_moments(
    game_id: int,
    mode: str = "buckets",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    nba_service = NBAService()
    moment_service = MomentService()

    events = nba_service.fetch_play_by_play(game.nba_game_id)
    moments = moment_service.process_events(events, game.id, db, mode=mode)

    game.status = "creating_moments"
    db.commit()

    return FetchMomentsResponse(count=len(moments), moments=moments)


@router.post("/games/{game_id}/map-timeline", response_model=MapTimelineResponse)
def map_timeline(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    if game.q1_start_seconds is None:
        raise HTTPException(
            status_code=400,
            detail="Quarter timestamps not set. q1_start_seconds is required.",
        )

    moments = db.query(Moment).filter(Moment.game_id == game_id).all()

    timeline_service = TimelineService()
    mapped_moments = timeline_service.map_moments_to_video(
        moments,
        game.q1_start_seconds,
        game.q2_start_seconds,
        game.q3_start_seconds,
        game.q4_start_seconds,
        db,
    )

    game.status = "mapping_timeline"
    db.commit()

    sample = [
        MappedMomentSample(
            player_name=m.player_name,
            game_clock=m.game_clock,
            video_time_seconds=m.video_time_seconds,
        )
        for m in mapped_moments[:5]
    ]

    return MapTimelineResponse(count=len(mapped_moments), sample=sample)


@router.post("/games/{game_id}/resolve-moments")
def resolve_moments(
    game_id: int,
    background_tasks: BackgroundTasks,
    profile: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resolve moment timestamps using clock OCR pipeline (Phase 6).

    This replaces the slow watch-based refinement. Runs in a background task
    because the OCR pass over a full game takes a few minutes.
    """
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    moments = db.query(Moment).filter(Moment.game_id == game_id).all()
    if not moments:
        raise HTTPException(status_code=400, detail="No moments found. Run fetch-moments first.")

    game.status = "resolving"
    db.commit()

    resolver = EventResolverService(profile_name=profile)

    def _run_resolve():
        from app.db.database import SessionLocal
        task_db = SessionLocal()
        try:
            task_moments = task_db.query(Moment).filter(Moment.game_id == game_id).all()
            result = resolver.resolve_moments(game_id, game.nba_game_id, task_moments, task_db)
            task_game = task_db.query(Game).filter(Game.id == game_id).first()
            if task_game:
                task_game.status = "resolved"
                task_db.commit()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("resolve_moments failed: %s", exc)
            task_game = task_db.query(Game).filter(Game.id == game_id).first()
            if task_game:
                task_game.status = "resolve_failed"
                task_db.commit()
        finally:
            task_db.close()

    background_tasks.add_task(_run_resolve)

    return {"status": "started", "moment_count": len(moments)}
