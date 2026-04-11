"""Backtest configuration, run tracking, and replay session models."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TradeMatchingMode(str, Enum):
    """Controls how strategy orders are matched against market trades.

    ALL   – match market trades at prices equal to or better than your quote.
    WORSE – only match market trades strictly better (worse for counterparty).
    NONE  – never match against market trades; only match against the order book.
    """

    ALL = "ALL"
    WORSE = "WORSE"
    NONE = "NONE"


# Keep ExecutionModel as an alias for backward compatibility with API/frontend.
# It maps to TradeMatchingMode internally.
class ExecutionModel(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    OPTIMISTIC = "OPTIMISTIC"


# Default position limits matching Prosperity 4
POSITION_LIMITS: dict[str, int] = {
    "RAINFOREST_RESIN": 50,
    "KELP": 50,
    "SQUID_INK": 50,
    "CROISSANTS": 250,
    "JAMS": 350,
    "DJEMBES": 60,
    "PICNIC_BASKET1": 60,
    "PICNIC_BASKET2": 100,
    "VOLCANIC_ROCK": 400,
    "VOLCANIC_ROCK_VOUCHER_9500": 200,
    "VOLCANIC_ROCK_VOUCHER_9750": 200,
    "VOLCANIC_ROCK_VOUCHER_10000": 200,
    "VOLCANIC_ROCK_VOUCHER_10250": 200,
    "VOLCANIC_ROCK_VOUCHER_10500": 200,
    "MAGNIFICENT_MACARONS": 75,
}

DEFAULT_POSITION_LIMIT = 50


def _map_execution_model(value: str) -> TradeMatchingMode:
    """Map legacy ExecutionModel strings to TradeMatchingMode."""
    mapping = {
        "CONSERVATIVE": TradeMatchingMode.WORSE,
        "BALANCED": TradeMatchingMode.ALL,
        "OPTIMISTIC": TradeMatchingMode.ALL,
    }
    # Accept TradeMatchingMode values directly
    try:
        return TradeMatchingMode(value)
    except ValueError:
        pass
    return mapping.get(value, TradeMatchingMode.ALL)


class BacktestConfig(BaseModel):
    """Configuration for a single backtest run."""

    strategy_id: str
    products: list[str] = Field(default_factory=list)
    days: list[int] = Field(default_factory=list)
    trade_matching: TradeMatchingMode = TradeMatchingMode.ALL
    position_limits: dict[str, int] = Field(default_factory=dict)
    initial_cash: float = 0.0
    parameters: dict[str, Any] = Field(default_factory=dict)

    # Legacy fields kept for API backward compatibility (ignored by engine)
    execution_model: str = "BALANCED"
    fees: float = 0.0
    slippage: float = 0.0

    model_config = {"frozen": False}

    def get_trade_matching(self) -> TradeMatchingMode:
        """Resolve the effective trade matching mode.

        If trade_matching was explicitly set to a non-default value, use it.
        Otherwise fall back to mapping execution_model for backward compat.
        """
        return self.trade_matching

    def get_position_limit(self, product: str) -> int:
        """Return position limit for a product.

        Checks user-supplied limits first, then built-in Prosperity limits,
        then falls back to DEFAULT_POSITION_LIMIT.
        """
        if product in self.position_limits:
            return self.position_limits[product]
        return POSITION_LIMITS.get(product, DEFAULT_POSITION_LIMIT)


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
