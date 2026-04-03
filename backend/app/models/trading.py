"""Trading domain models: orders, fills, positions, and PnL tracking."""

from pydantic import BaseModel, Field

from backend.app.models.market import OrderSide, OrderStatus, OrderType


class StrategyOrder(BaseModel):
    """An order submitted by a strategy to the matching engine."""

    order_id: str
    product: str
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    price: float = 0.0
    quantity: int = 0
    timestamp: int = 0
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    created_at: int = 0
    updated_at: int = 0

    model_config = {"frozen": False}

    @property
    def remaining_quantity(self) -> int:
        """Quantity still open on this order."""
        return self.quantity - self.filled_quantity

    @property
    def is_complete(self) -> bool:
        """Whether the order has reached a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        )


class FillEvent(BaseModel):
    """A fill (execution) against an order."""

    order_id: str
    product: str
    side: OrderSide
    price: float
    quantity: int
    timestamp: int = 0
    is_aggressive: bool = False

    model_config = {"frozen": False}


class PositionState(BaseModel):
    """Current position for a single product."""

    product: str
    quantity: int = 0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    mark_price: float = 0.0

    model_config = {"frozen": False}

    @property
    def net_exposure(self) -> float:
        """Absolute notional exposure = |quantity * mark_price|."""
        return abs(self.quantity * self.mark_price)

    @property
    def total_pnl(self) -> float:
        """Realized + unrealized PnL for this product."""
        return self.realized_pnl + self.unrealized_pnl


class InventoryState(BaseModel):
    """Aggregate inventory state across all products."""

    positions: dict[str, PositionState] = Field(default_factory=dict)
    cash: float = 0.0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_pnl: float = 0.0

    model_config = {"frozen": False}


class PnLState(BaseModel):
    """Point-in-time PnL snapshot for time-series tracking."""

    timestamp: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    inventory: dict[str, int] = Field(default_factory=dict)
    cash: float = 0.0

    model_config = {"frozen": False}
