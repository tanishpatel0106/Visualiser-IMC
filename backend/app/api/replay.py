"""Replay control API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.app.core.config import settings
from backend.app.core.deps import get_dataset_service, get_replay_engine
from backend.app.engines.replay.engine import ReplayEngine
from backend.app.services.dataset_service import DatasetService
from backend.app.services.replay_service import ReplayService

router = APIRouter(prefix="/replay")

# ---------------------------------------------------------------------------
# Per-request service construction (depends on singletons)
# ---------------------------------------------------------------------------

def _get_replay_service(
    engine: ReplayEngine = Depends(get_replay_engine),
    ds: DatasetService = Depends(get_dataset_service),
) -> ReplayService:
    # Reuse the same ReplayService wrapper across requests by storing it
    # on the engine (lightweight approach; alternatively use a global).
    if not hasattr(engine, "_service"):
        engine._service = ReplayService(engine, ds)  # type: ignore[attr-defined]
    return engine._service  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    products: list[str]
    days: list[int]
    strategy_id: Optional[str] = None


class SeekRequest(BaseModel):
    timestamp: int


class SpeedRequest(BaseModel):
    speed: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/start")
def start_replay(
    req: StartRequest,
    svc: ReplayService = Depends(_get_replay_service),
):
    """Start a new replay session for the given products and days."""
    result = svc.start_replay(req.products, req.days, req.strategy_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/pause")
def pause_replay(svc: ReplayService = Depends(_get_replay_service)):
    """Pause the running replay."""
    return svc.pause_replay()


@router.post("/step")
def step_forward(svc: ReplayService = Depends(_get_replay_service)):
    """Step one event forward and return event + state snapshot."""
    return svc.step_forward()


@router.post("/step-back")
def step_backward(svc: ReplayService = Depends(_get_replay_service)):
    """Step one event backward."""
    return svc.step_backward()


@router.post("/seek")
def seek(
    req: SeekRequest,
    svc: ReplayService = Depends(_get_replay_service),
):
    """Seek to the nearest event at the given timestamp."""
    result = svc.seek(req.timestamp)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/speed")
def set_speed(
    req: SpeedRequest,
    svc: ReplayService = Depends(_get_replay_service),
):
    """Set the replay playback speed."""
    if req.speed <= 0:
        raise HTTPException(status_code=400, detail="Speed must be positive")
    if req.speed > settings.max_replay_speed:
        raise HTTPException(
            status_code=400,
            detail=f"Speed must not exceed {settings.max_replay_speed}",
        )
    svc.set_speed(req.speed)
    return {"speed": req.speed}


@router.get("/state")
def get_state(svc: ReplayService = Depends(_get_replay_service)):
    """Return the current replay engine + world state."""
    return svc.get_state()


@router.post("/reset")
def reset_replay(svc: ReplayService = Depends(_get_replay_service)):
    """Reset the replay to its initial state."""
    svc.reset()
    return {"status": "reset"}


@router.post("/jump-next-trade")
def jump_next_trade(svc: ReplayService = Depends(_get_replay_service)):
    """Jump to the next TRADE_PRINT event."""
    return svc.jump_next_trade()


@router.post("/jump-next-fill")
def jump_next_fill(svc: ReplayService = Depends(_get_replay_service)):
    """Jump to the next FILL event."""
    return svc.jump_next_fill()
