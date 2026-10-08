"""Dependency injection for FastAPI endpoints."""

import os
from typing import Optional

from fastapi import HTTPException
from pathlib import Path

from app.core.config import settings
from app.engines.replay.engine import ReplayEngine
from app.engines.strategies.registry import StrategyRegistry
from app.services.dataset_service import DatasetService
from app.storage.database import StorageService

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_dataset_service: Optional[DatasetService] = None
_replay_engine: Optional[ReplayEngine] = None
_strategy_registry: Optional[StrategyRegistry] = None
_storage_service: Optional[StorageService] = None


def get_dataset_service(window: int = -1) -> DatasetService:
    """Return the global DatasetService singleton."""
    global _dataset_service
    if settings.dataset_manifest and Path(settings.dataset_manifest).is_file():
        from app.services.nvda_dataset import nvda_dataset
        try:
            return nvda_dataset.load(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="NVDA dataset storage is unavailable.") from exc
    if os.environ.get("BLOB_READ_WRITE_TOKEN"):
        from app.services.shared_dataset import shared_dataset
        try:
            return shared_dataset.load()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Shared dataset storage is unavailable.") from exc
    if _dataset_service is None:
        _dataset_service = DatasetService()
    return _dataset_service


def get_replay_engine() -> ReplayEngine:
    """Return the global ReplayEngine singleton."""
    global _replay_engine
    if _replay_engine is None:
        _replay_engine = ReplayEngine()
    return _replay_engine


def get_strategy_registry() -> StrategyRegistry:
    """Return the global StrategyRegistry singleton with builtins loaded."""
    global _strategy_registry
    if _strategy_registry is None:
        _strategy_registry = StrategyRegistry()
        _strategy_registry.load_builtins()
    return _strategy_registry


def get_storage() -> StorageService:
    """Return the global StorageService singleton."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService(db_path=settings.storage_path)
    return _storage_service
