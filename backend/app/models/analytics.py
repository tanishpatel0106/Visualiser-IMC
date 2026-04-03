"""Analytics result models for performance, execution, and microstructure."""

from pydantic import BaseModel, Field


class PerformanceMetrics(BaseModel):
    """Aggregate performance metrics for a backtest or live run."""

    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    pnl_by_product: dict[str, float] = Field(default_factory=dict)
    return_per_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    num_trades: int = 0
    turnover: float = 0.0
    max_drawdown: float = 0.0
    drawdown_duration: int = 0
    sharpe_ratio: float = 0.0
    pnl_volatility: float = 0.0
    avg_inventory: float = 0.0
    max_inventory: float = 0.0
    profit_factor: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_holding_period: float = 0.0
    pnl_per_unit_risk: float = 0.0

    model_config = {"frozen": False}


class ExecutionMetrics(BaseModel):
    """Metrics related to order execution quality."""

    num_orders: int = 0
    fill_count: int = 0
    full_fill_rate: float = 0.0
    partial_fill_rate: float = 0.0
    cancel_count: int = 0
    reject_count: int = 0
    avg_fill_delay: float = 0.0
    effective_spread_captured: float = 0.0
    passive_aggressive_ratio: float = 0.0
    estimated_slippage: float = 0.0
    avg_fill_size: float = 0.0
    total_volume_traded: int = 0
    maker_volume: int = 0
    taker_volume: int = 0

    model_config = {"frozen": False}


class MicrostructureMetrics(BaseModel):
    """Microstructure statistics for a product over a time window."""

    avg_spread: float = 0.0
    spread_std: float = 0.0
    avg_imbalance: float = 0.0
    avg_depth_bid: float = 0.0
    avg_depth_ask: float = 0.0
    trade_count: int = 0
    avg_trade_size: float = 0.0
    buy_volume: int = 0
    sell_volume: int = 0
    vwap: float = 0.0
    price_volatility: float = 0.0
    kyle_lambda: float = 0.0
    roll_spread: float = 0.0
    arrival_rate: float = 0.0

    model_config = {"frozen": False}
