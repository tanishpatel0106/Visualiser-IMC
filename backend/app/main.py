"""FastAPI application entry point for the IMC Prosperity trading terminal."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import backtest, datasets, replay, strategies, websocket
from app.core.config import settings
from app.core.deps import get_dataset_service, get_storage, get_strategy_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    # Startup
    logger.info("Initialising IMC Prosperity trading terminal backend...")

    # 1. Initialise storage (create tables if needed)
    storage = get_storage()
    storage.init_db()
    logger.info("Storage initialised at %s", settings.storage_path)

    # 2. Load built-in strategies into the registry
    registry = get_strategy_registry()
    logger.info("Strategy registry loaded with %d built-in strategies", len(registry.get_all()))

    # 3. Auto-load sample data if the directory exists
    data_dir = settings.data_directory
    if os.path.isdir(data_dir):
        ds = get_dataset_service()
        try:
            summary = ds.load_dataset(data_dir)
            logger.info(
                "Auto-loaded dataset: %d files, %d products, %d days",
                summary.get("files", 0),
                len(summary.get("products", [])),
                len(summary.get("days", [])),
            )
        except Exception as exc:
            logger.warning("Failed to auto-load sample data from %s: %s", data_dir, exc)
    else:
        logger.info("No sample data directory found at '%s'; skipping auto-load", data_dir)

    logger.info("Backend ready.")
    yield
    # Shutdown
    logger.info("Shutting down...")


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="IMC Prosperity Trading Terminal",
    description="Backend API for the IMC Prosperity market visualiser and backtester",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------

# Dataset and market data endpoints (mounted at /api)
app.include_router(datasets.router, prefix="/api", tags=["datasets"])

# Replay control (mounted at /api/replay)
app.include_router(replay.router, prefix="/api", tags=["replay"])

# Backtest endpoints (mounted at /api/backtest)
app.include_router(backtest.router, prefix="/api", tags=["backtest"])

# Strategy and run management (mounted at /api)
app.include_router(strategies.router, prefix="/api", tags=["strategies"])

# WebSocket (mounted at /api)
app.include_router(websocket.router, prefix="/api", tags=["websocket"])
