"""Backtest API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.core.deps import get_dataset_service, get_storage
from app.models.backtest import BacktestConfig
from app.services.backtest_service import BacktestService
from app.services.dataset_service import DatasetService
from app.storage.database import StorageService

router = APIRouter(prefix="/backtest")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    strategy_id: str
    source_code: str
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

def _get_backtest_service(
    ds: DatasetService = Depends(get_dataset_service),
    storage: StorageService = Depends(get_storage),
) -> BacktestService:
    return BacktestService(dataset_service=ds, storage=storage)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/run")
def run_backtest(
    req: RunRequest,
    svc: BacktestService = Depends(_get_backtest_service),
):
    """Execute a backtest and return the run summary."""
    config = BacktestConfig(
        strategy_id=req.strategy_id,
        products=req.products,
        days=req.days,
        execution_model=req.execution_model,
        position_limits=req.position_limits,
        fees=req.fees,
        slippage=req.slippage,
        initial_cash=req.initial_cash,
    )
    try:
        run = svc.run_backtest(config, source_code=req.source_code)
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


@router.get("/{run_id}")
def get_run(
    run_id: str,
    svc: BacktestService = Depends(_get_backtest_service),
):
    """Return the summary for a backtest run."""
    run = svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/metrics")
def get_run_metrics(
    run_id: str,
    svc: BacktestService = Depends(_get_backtest_service),
):
    """Return just the metrics for a run."""
    metrics = svc.get_run_metrics(run_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="Run not found or has no metrics")
    return metrics


@router.get("/{run_id}/trace")
def get_run_trace(
    run_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    svc: BacktestService = Depends(_get_backtest_service),
):
    """Return paginated debug trace frames for a run."""
    frames = svc.get_run_trace(run_id, offset=offset, limit=limit)
    return {"run_id": run_id, "offset": offset, "limit": limit, "frames": frames}


@router.get("/{run_id}/fills")
def get_run_fills(
    run_id: str,
    svc: BacktestService = Depends(_get_backtest_service),
):
    """Return all fills for a run."""
    fills = svc.get_run_fills(run_id)
    return {"run_id": run_id, "count": len(fills), "fills": fills}


@router.get("/{run_id}/pnl")
def get_run_pnl(
    run_id: str,
    svc: BacktestService = Depends(_get_backtest_service),
):
    """Return the PnL history for a run."""
    pnl = svc.get_run_pnl(run_id)
    return {"run_id": run_id, "count": len(pnl), "pnl_history": pnl}


@router.get("/{run_id}/export")
def export_run(
    run_id: str,
    format: str = Query("json", description="Export format"),
    svc: BacktestService = Depends(_get_backtest_service),
):
    """Export full run data."""
    data = svc.export_run(run_id, fmt=format)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return data
