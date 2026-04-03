"""Backtest configuration, run tracking, and replay session models."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ExecutionModel(str, Enum):
    """Execution assumption level for backtesting."""

    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    OPTIMISTIC = "OPTIMISTIC"


class BacktestConfig(BaseModel):
    """Configuration for a single backtest run."""

    strategy_id: str
    products: list[str] = Field(default_factory=list)
    days: list[int] = Field(default_factory=list)
    execution_model: ExecutionModel = ExecutionModel.BALANCED
    position_limits: dict[str, int] = Field(default_factory=dict)
    fees: float = 0.0
    slippage: float = 0.0
    initial_cash: float = 0.0

    model_config = {"frozen": False}


class BacktestRun(BaseModel):
    """Tracks the state and results of a backtest execution."""

    run_id: str
    config: BacktestConfig
    status: str = "pending"
    started_at: str = ""
    completed_at: Optional[str] = None
    metrics: Optional[dict] = None
    error: Optional[str] = None

    model_config = {"frozen": False}


class ReplaySession(BaseModel):
    """State of an interactive market replay session."""

    session_id: str
    products: list[str] = Field(default_factory=list)
    days: list[int] = Field(default_factory=list)
    current_timestamp: int = 0
    is_playing: bool = False
    speed: float = 1.0
    strategy_id: Optional[str] = None

    model_config = {"frozen": False}


class RunArtifact(BaseModel):
    """An artifact produced by a backtest run (e.g. PnL curve, trade log)."""

    run_id: str
    artifact_type: str = ""
    data: Any = None

    model_config = {"frozen": False}
