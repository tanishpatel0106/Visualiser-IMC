"""Backtest orchestration service."""

import json
import logging
from typing import Optional

from backend.app.engines.backtest.engine import BacktestEngine
from backend.app.engines.sandbox.runner import StrategySandbox
from backend.app.models.backtest import BacktestConfig, BacktestRun
from backend.app.services.dataset_service import DatasetService
from backend.app.storage.database import StorageService

logger = logging.getLogger(__name__)


class BacktestService:
    """Manages backtest execution, storage, and retrieval."""

    def __init__(
        self,
        dataset_service: DatasetService,
        storage: StorageService,
        sandbox: Optional[StrategySandbox] = None,
    ) -> None:
        self._dataset = dataset_service
        self._storage = storage
        self._sandbox = sandbox or StrategySandbox()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_backtest(self, config: BacktestConfig, source_code: str) -> BacktestRun:
        """Execute a full backtest run.

        Parameters
        ----------
        config : BacktestConfig
            The backtest parameters.
        source_code : str
            The strategy source code to execute.

        Returns
        -------
        BacktestRun with status, metrics, and timing.
        """
        # Load strategy
        trader = self._sandbox.load_strategy(source_code)

        # Build event stream
        events = self._dataset.get_event_stream(config.products, config.days)
        if not events:
            raise ValueError("No events found for the given products and days")

        # Run the engine
        engine = BacktestEngine(config)
        run = engine.run(events, trader)

        # Persist
        self._storage.save_run(run)
        self._storage.save_run_artifacts(run.run_id, {
            "trace": [f.model_dump() for f in engine.get_debug_frames()],
            "fills": [f.model_dump() for f in engine.get_fills()],
            "pnl_history": [p.model_dump() for p in engine.get_pnl_history()],
        })

        return run

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> Optional[dict]:
        """Retrieve a run summary."""
        return self._storage.get_run(run_id)

    def get_run_metrics(self, run_id: str) -> Optional[dict]:
        """Return just the metrics block for a run."""
        run = self._storage.get_run(run_id)
        if run is None:
            return None
        return run.get("metrics")

    def get_run_trace(self, run_id: str, offset: int = 0, limit: int = 100) -> list[dict]:
        """Return paginated debug trace frames for a run."""
        artifacts = self._storage.get_run_artifacts(run_id)
        if artifacts is None:
            return []
        trace = artifacts.get("trace", [])
        return trace[offset : offset + limit]

    def get_run_fills(self, run_id: str) -> list[dict]:
        """Return all fills for a run."""
        artifacts = self._storage.get_run_artifacts(run_id)
        if artifacts is None:
            return []
        return artifacts.get("fills", [])

    def get_run_pnl(self, run_id: str) -> list[dict]:
        """Return the PnL history for a run."""
        artifacts = self._storage.get_run_artifacts(run_id)
        if artifacts is None:
            return []
        return artifacts.get("pnl_history", [])

    def list_runs(self) -> list[dict]:
        """List all backtest runs."""
        return self._storage.list_runs()

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare_runs(self, run_ids: list[str]) -> dict:
        """Compare multiple runs side-by-side by metrics."""
        results: list[dict] = []
        for run_id in run_ids:
            run = self._storage.get_run(run_id)
            if run is not None:
                results.append({
                    "run_id": run["run_id"],
                    "config": run["config"],
                    "status": run["status"],
                    "metrics": run.get("metrics"),
                })
        return {"runs": results, "count": len(results)}

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_run(self, run_id: str, fmt: str = "json") -> Optional[dict]:
        """Export full run data in the requested format.

        Currently only JSON is supported. Returns a dict with run summary
        plus all artifacts.
        """
        run = self._storage.get_run(run_id)
        if run is None:
            return None

        artifacts = self._storage.get_run_artifacts(run_id) or {}

        return {
            "run": run,
            "trace": artifacts.get("trace", []),
            "fills": artifacts.get("fills", []),
            "pnl_history": artifacts.get("pnl_history", []),
            "format": fmt,
        }
