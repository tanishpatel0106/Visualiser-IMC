"""Strategy and run management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.deps import (
    get_dataset_service,
    get_storage,
    get_strategy_registry,
)
from backend.app.engines.sandbox.runner import StrategySandbox
from backend.app.engines.strategies.registry import StrategyRegistry
from backend.app.services.dataset_service import DatasetService
from backend.app.services.strategy_service import StrategyService
from backend.app.storage.database import StorageService

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class UploadRequest(BaseModel):
    name: str
    source_code: str


class RunStrategyRequest(BaseModel):
    products: list[str] = []
    days: list[int] = []
    execution_model: str = "BALANCED"
    position_limits: dict[str, int] = {}
    fees: float = 0.0
    slippage: float = 0.0
    initial_cash: float = 0.0


class CompareRequest(BaseModel):
    run_ids: list[str]


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def _get_strategy_service(
    registry: StrategyRegistry = Depends(get_strategy_registry),
    storage: StorageService = Depends(get_storage),
    ds: DatasetService = Depends(get_dataset_service),
) -> StrategyService:
    sandbox = StrategySandbox()
    return StrategyService(
        registry=registry,
        sandbox=sandbox,
        storage=storage,
        dataset_service=ds,
    )


# ---------------------------------------------------------------------------
# Strategy endpoints
# ---------------------------------------------------------------------------

@router.get("/strategies")
def list_strategies(
    svc: StrategyService = Depends(_get_strategy_service),
):
    """List all strategies (built-in + uploaded)."""
    return {"strategies": svc.get_all_strategies()}


@router.get("/strategies/{strategy_id}")
def get_strategy(
    strategy_id: str,
    svc: StrategyService = Depends(_get_strategy_service),
):
    """Get details for a single strategy."""
    strategy = svc.get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.get("/strategies/{strategy_id}/source")
def get_strategy_source(
    strategy_id: str,
    svc: StrategyService = Depends(_get_strategy_service),
):
    """Return the raw source code for a strategy."""
    source = svc.get_strategy_source(strategy_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {"strategy_id": strategy_id, "source_code": source}


@router.post("/strategies/upload")
def upload_strategy(
    req: UploadRequest,
    svc: StrategyService = Depends(_get_strategy_service),
):
    """Upload and validate a user strategy."""
    result = svc.upload_strategy(req.name, req.source_code)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/strategies/{strategy_id}/run")
def run_strategy(
    strategy_id: str,
    req: RunStrategyRequest,
    svc: StrategyService = Depends(_get_strategy_service),
):
    """Run a strategy through the backtest engine."""
    try:
        run = svc.run_strategy(strategy_id, req.model_dump())
        return {
            "run_id": run.run_id,
            "status": run.status,
            "metrics": run.metrics,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "error": run.error,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Run management endpoints
# ---------------------------------------------------------------------------

@router.get("/runs")
def list_runs(storage: StorageService = Depends(get_storage)):
    """List all backtest runs."""
    return {"runs": storage.list_runs()}


@router.get("/runs/{run_id}/artifacts")
def get_run_artifacts(
    run_id: str,
    storage: StorageService = Depends(get_storage),
):
    """Return the full artifacts (trace, fills, pnl_history) for a run."""
    artifacts = storage.get_run_artifacts(run_id)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Run artifacts not found")
    return artifacts


@router.post("/runs/compare")
def compare_runs(
    req: CompareRequest,
    svc: StrategyService = Depends(_get_strategy_service),
):
    """Compare metrics across multiple runs."""
    return svc.compare_runs(req.run_ids)
