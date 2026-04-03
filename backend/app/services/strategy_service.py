"""Strategy management service: upload, validate, list, and run strategies."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.app.engines.backtest.engine import BacktestEngine
from backend.app.engines.sandbox.runner import StrategySandbox
from backend.app.engines.strategies.registry import StrategyRegistry
from backend.app.models.backtest import BacktestConfig, BacktestRun
from backend.app.services.dataset_service import DatasetService
from backend.app.storage.database import StorageService

logger = logging.getLogger(__name__)


class StrategyService:
    """Facade for strategy lifecycle operations."""

    def __init__(
        self,
        registry: StrategyRegistry,
        sandbox: StrategySandbox,
        storage: StorageService,
        dataset_service: Optional[DatasetService] = None,
    ) -> None:
        self._registry = registry
        self._sandbox = sandbox
        self._storage = storage
        self._dataset = dataset_service

    # ------------------------------------------------------------------
    # Upload / validation
    # ------------------------------------------------------------------

    def upload_strategy(self, name: str, source_code: str) -> dict:
        """Validate and persist a user-uploaded strategy.

        Returns a dict with ``valid``, ``strategy_id``, and ``error``.
        """
        valid, error = self._sandbox.validate_strategy(source_code)
        if not valid:
            return {"valid": False, "strategy_id": None, "error": error}

        strategy_id = str(uuid.uuid4())
        strategy_def = {
            "strategy_id": strategy_id,
            "name": name,
            "category": "custom",
            "description": f"User-uploaded strategy: {name}",
            "source_code": source_code,
            "is_builtin": False,
            "parameters": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._storage.save_strategy(strategy_def)
        return {"valid": True, "strategy_id": strategy_id, "error": None}

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def get_all_strategies(self) -> list[dict]:
        """Return all strategies: built-in (from registry) + uploaded (from storage)."""
        strategies: list[dict] = []

        # Built-in strategies from the registry
        for sdef in self._registry.get_all():
            strategies.append({
                "strategy_id": sdef.strategy_id,
                "name": sdef.name,
                "category": sdef.category,
                "description": sdef.description,
                "is_builtin": True,
                "parameters": sdef.parameters if isinstance(sdef.parameters, list) else list(sdef.parameters.values()),
            })

        # Uploaded strategies from the database
        for sdef in self._storage.list_strategies():
            if not sdef.get("is_builtin"):
                strategies.append(sdef)

        return strategies

    def get_strategy(self, strategy_id: str) -> Optional[dict]:
        """Get a single strategy by ID (checks registry first, then storage)."""
        # Check built-in registry
        builtin = self._registry.get_by_id(strategy_id)
        if builtin is not None:
            return {
                "strategy_id": builtin.strategy_id,
                "name": builtin.name,
                "category": builtin.category,
                "description": builtin.description,
                "is_builtin": True,
                "parameters": builtin.parameters if isinstance(builtin.parameters, list) else list(builtin.parameters.values()),
            }

        # Check storage
        return self._storage.get_strategy(strategy_id)

    def get_strategy_source(self, strategy_id: str) -> Optional[str]:
        """Return the raw source code for a strategy."""
        # Check registry first
        builtin = self._registry.get_by_id(strategy_id)
        if builtin is not None:
            return builtin.source_code

        stored = self._storage.get_strategy(strategy_id)
        if stored is not None:
            return stored.get("source_code", "")

        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_strategy(self, strategy_id: str, config: dict) -> BacktestRun:
        """Load a strategy and run it through the backtest engine.

        Parameters
        ----------
        strategy_id : str
            The strategy to execute.
        config : dict
            Backtest configuration overrides (products, days, execution_model, etc.).
        """
        # Resolve source code
        source = self.get_strategy_source(strategy_id)
        if source is None:
            raise ValueError(f"Strategy not found: {strategy_id}")

        # Load strategy via sandbox
        trader = self._sandbox.load_strategy(source)

        # Build backtest config
        bt_config = BacktestConfig(
            strategy_id=strategy_id,
            products=config.get("products", []),
            days=config.get("days", []),
            execution_model=config.get("execution_model", "BALANCED"),
            position_limits=config.get("position_limits", {}),
            fees=config.get("fees", 0.0),
            slippage=config.get("slippage", 0.0),
            initial_cash=config.get("initial_cash", 0.0),
        )

        # Get event stream
        if self._dataset is None:
            raise RuntimeError("DatasetService not available")

        events = self._dataset.get_event_stream(bt_config.products, bt_config.days)
        if not events:
            raise ValueError("No events found for the given products and days")

        # Run backtest
        engine = BacktestEngine(bt_config)
        run = engine.run(events, trader)

        # Persist run and artifacts
        self._storage.save_run(run)
        self._storage.save_run_artifacts(run.run_id, {
            "trace": [f.model_dump() for f in engine.get_debug_frames()],
            "fills": [f.model_dump() for f in engine.get_fills()],
            "pnl_history": [p.model_dump() for p in engine.get_pnl_history()],
        })

        return run

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare_runs(self, run_ids: list[str]) -> dict:
        """Compare multiple backtest runs by their metrics."""
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
