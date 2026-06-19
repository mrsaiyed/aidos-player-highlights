import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db, SessionLocal
from app.models.clip import Clip
from app.models.game import Game
from app.models.moment import Moment
from app.models.user import User
from app.schemas.clip import ClipResponse
from app.services.clip_service import ClipService
from app.services.moment_service import MomentService
from app.services.nba_service import NBAService
from app.services.refinement_service import RefinementService
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _run_full_pipeline(
    game_id: int,
    nba_game_id: str,
    team: Optional[str],
    highlight_type: str,
    max_period: int,
    players: Optional[list[str]],
):
    """One-shot pipeline: fetch -> moments -> anchor-chain confirm -> cut clips.

    Runs in a background task with its own DB session. Advances Game.status so the frontend
    can poll. The anchor chain refines ALL of the team's scoring plays (anchors depend on the
    full ordered sequence); only the player-selected subset is cut into clips.
    """
    db = SessionLocal()
    try:
        def set_status(s: str):
            game = db.query(Game).filter(Game.id == game_id).first()
            if game:
                game.status = s
                db.commit()

        # Fresh run: clear any prior moments/clips for this game so /process is idempotent.
        db.query(Clip).filter(Clip.game_id == game_id).delete()
        db.query(Moment).filter(Moment.game_id == game_id).delete()
        db.commit()

        set_status("fetching")
        events = NBAService().fetch_play_by_play(nba_game_id)
        moments = MomentService().process_events(events, game_id, db, mode=highlight_type)

        # Team's full ordered sequence to refine (keeps the anchor chain intact).
        refine_targets = [
            m for m in moments
            if (team is None or m.team == team) and m.period <= max_period
        ]
        if not refine_targets:
            set_status("no_moments")
            return

        set_status("confirming")
        RefinementService().refine_moments(game_id, nba_game_id, refine_targets, db, use_watch_fallback=False)

        # Cut clips only for the selected players (or all scorers when players is None).
        clip_targets = refine_targets
        if players:
            wanted = {p.lower() for p in players}
            clip_targets = [m for m in refine_targets if m.player_name.lower() in wanted]

        set_status("cutting")
        ClipService().generate_clips(game_id, nba_game_id, clip_targets, db)
        set_status("done")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline failed for game %s: %s", game_id, exc)
        game = db.query(Game).filter(Game.id == game_id).first()
        if game:
            game.status = "error"
            db.commit()
    finally:
        db.close()


def _run_clip_generation(game_id: int, nba_game_id: str, moments: list, db: Session):
    clip_service = ClipService()
    clip_service.generate_clips(game_id, nba_game_id, moments, db)
    game = db.query(Game).filter(Game.id == game_id).first()
    if game:
        game.status = "cutting_clips"
        db.commit()


def _run_refinement(game_id: int, nba_game_id: str, moments: list, db: Session):
    refinement_service = RefinementService()
    refinement_service.refine_moments(game_id, nba_game_id, moments, db)
    game = db.query(Game).filter(Game.id == game_id).first()
    if game:
        game.status = "moments_refined"
        db.commit()


@router.post("/games/{game_id}/refine-moments")
def refine_moments(
    game_id: int,
    background_tasks: BackgroundTasks,
    team: Optional[str] = None,
    max_period: int = 4,
    highlight_type: str = "buckets",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(
        Game.id == game_id, Game.user_id == user.id
    ).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    query = db.query(Moment).filter(Moment.game_id == game_id)
    if team:
        query = query.filter(Moment.team == team)
    if highlight_type == "buckets":
        query = query.filter(Moment.event_type == "made_shot")
    query = query.filter(Moment.period <= max_period)
    moments = query.all()

    if not moments:
        raise HTTPException(
            status_code=400,
            detail="No matching moments found to refine.",
        )

    background_tasks.add_task(
        _run_refinement, game_id, game.nba_game_id, moments, db
    )

    return {
        "status": "processing",
        "message": "Moment refinement started in background",
        "moments_queued": len(moments),
        "filters": {
            "team": team,
            "highlight_type": highlight_type,
            "max_period": max_period,
        },
    }


@router.post("/games/{game_id}/generate-clips")
def generate_clips(
    game_id: int,
    background_tasks: BackgroundTasks,
    team: Optional[str] = None,
    highlight_type: str = "buckets",
    max_period: int = 4,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(
        Game.id == game_id, Game.user_id == user.id
    ).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    query = db.query(Moment).filter(
        Moment.game_id == game_id,
        Moment.video_time_seconds.isnot(None),
    )
    if team:
        query = query.filter(Moment.team == team)
    if highlight_type == "buckets":
        query = query.filter(Moment.event_type == "made_shot")
    query = query.filter(Moment.period <= max_period)
    moments = query.all()

    if not moments:
        raise HTTPException(
            status_code=400,
            detail="No matching moments found after applying filters.",
        )

    background_tasks.add_task(
        _run_clip_generation, game_id, game.nba_game_id, moments, db
    )

    return {
        "status": "processing",
        "message": "Clip generation started in background",
        "filters": {
            "team": team,
            "highlight_type": highlight_type,
            "max_period": max_period,
        },
    }


@router.get("/games/{game_id}/clips", response_model=list[ClipResponse])
def list_clips(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(
        Game.id == game_id, Game.user_id == user.id
    ).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    return db.query(Clip).filter(Clip.game_id == game_id).all()


@router.post("/games/{game_id}/process")
def process_game(
    game_id: int,
    background_tasks: BackgroundTasks,
    team: Optional[str] = None,
    highlight_type: str = "buckets",
    max_period: int = 4,
    players: Optional[str] = None,  # comma-separated player names; omit for full team
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Single entry point for the frontend: fetch -> moments -> confirm -> cut clips.

    Poll GET /games/{id}/status for progress. `players` is a comma-separated list of player
    names to clip; omit it to clip every scorer on the team.
    """
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    player_list = [p.strip() for p in players.split(",") if p.strip()] if players else None

    game.status = "queued"
    db.commit()

    background_tasks.add_task(
        _run_full_pipeline,
        game_id, game.nba_game_id, team, highlight_type, max_period, player_list,
    )
    return {
        "status": "queued",
        "message": "Processing started; poll /status for progress",
        "filters": {"team": team, "highlight_type": highlight_type,
                    "max_period": max_period, "players": player_list},
    }


@router.get("/games/{game_id}/status")
def game_status(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pollable status + counts for the processing pipeline."""
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    moments = db.query(Moment).filter(Moment.game_id == game_id).all()
    clips = db.query(Clip).filter(Clip.game_id == game_id).all()
    return {
        "status": game.status,
        "moments": len(moments),
        "confirmed": sum(1 for m in moments if m.confidence == "high"),
        "flagged": sum(1 for m in moments if m.confidence == "low"),
        "clips_generated": sum(1 for c in clips if c.status == "generated"),
        "clips_total": len(clips),
    }
