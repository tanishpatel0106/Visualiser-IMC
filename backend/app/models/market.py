"""Core market domain models for IMC Prosperity trading terminal."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class Product(str, Enum):
    """Tradeable products in IMC Prosperity."""

    EMERALDS = "EMERALDS"
    TOMATOES = "TOMATOES"
    UNKNOWN = "UNKNOWN"


class OrderSide(str, Enum):
    """Side of an order or trade."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Type of order submission."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    """Lifecycle status of an order."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class BookLevel(BaseModel):
    """A single price level in the order book."""

    price: float
    volume: int
    side: OrderSide

    model_config = {"frozen": False}


class VisibleOrderBook(BaseModel):
    """
    Visible order book for a single product at a point in time.

    Bids are ordered descending by price (best bid first).
    Asks are ordered ascending by price (best ask first).
    """

    product: str
    timestamp: int
    bids: list[BookLevel] = Field(default_factory=list)
    asks: list[BookLevel] = Field(default_factory=list)

    model_config = {"frozen": False}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def best_bid(self) -> Optional[float]:
        """Highest bid price, or None if no bids."""
        return self.bids[0].price if self.bids else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def best_ask(self) -> Optional[float]:
        """Lowest ask price, or None if no asks."""
        return self.asks[0].price if self.asks else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread, or None if either side is empty."""
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mid_price(self) -> Optional[float]:
        """Simple mid price = (best_bid + best_ask) / 2."""
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2.0
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def weighted_mid(self) -> Optional[float]:
        """Volume-weighted mid price using top-of-book quantities."""
        if not self.bids or not self.asks:
            return None
        bid_vol = self.bids[0].volume
        ask_vol = self.asks[0].volume
        total = bid_vol + ask_vol
        if total == 0:
            return self.mid_price
        return (self.bids[0].price * ask_vol + self.asks[0].price * bid_vol) / total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def microprice(self) -> Optional[float]:
        """Microprice (same as weighted_mid). Alias kept for clarity."""
        return self.weighted_mid

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_bid_depth(self) -> int:
        """Total volume across all bid levels."""
        return sum(level.volume for level in self.bids)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_ask_depth(self) -> int:
        """Total volume across all ask levels."""
        return sum(level.volume for level in self.asks)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def top_level_imbalance(self) -> Optional[float]:
        """
        Order imbalance at the top of book.
        Returns (bid_vol - ask_vol) / (bid_vol + ask_vol) in [-1, 1].
        Positive means bid-heavy (buying pressure).
        """
        if not self.bids or not self.asks:
            return None
        bid_vol = self.bids[0].volume
        ask_vol = self.asks[0].volume
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def top3_imbalance(self) -> Optional[float]:
        """
        Order imbalance across the top 3 levels of the book.
        Returns (bid_vol - ask_vol) / (bid_vol + ask_vol) in [-1, 1].
        """
        if not self.bids or not self.asks:
            return None
        bid_vol = sum(level.volume for level in self.bids[:3])
        ask_vol = sum(level.volume for level in self.asks[:3])
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def book_pressure(self) -> Optional[float]:
        """
        Full-book pressure ratio: total_bid_depth / (total_bid_depth + total_ask_depth).
        Values > 0.5 indicate bid-heavy book.
        """
        total = self.total_bid_depth + self.total_ask_depth
        if total == 0:
            return None
        return self.total_bid_depth / total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def depth_skew(self) -> Optional[float]:
        """
        Depth skew: log-ratio style metric.
        (total_bid_depth - total_ask_depth) / (total_bid_depth + total_ask_depth).
        """
        total = self.total_bid_depth + self.total_ask_depth
        if total == 0:
            return None
        return (self.total_bid_depth - self.total_ask_depth) / total


class TradePrint(BaseModel):
    """A single executed trade visible on the tape."""

    timestamp: int
    buyer: str
    seller: str
    symbol: str
    currency: str = "SEASHELLS"
    price: float
    quantity: int
    aggressor_side: Optional[OrderSide] = None

    model_config = {"frozen": False}


class MarketSnapshot(BaseModel):
    """
    Flat snapshot of market state at a point in time.
    Used for tabular storage and CSV-based replay data.
    """

    day: int
    timestamp: int
    product: str
    bid_prices: list[Optional[float]] = Field(default_factory=list)
    bid_volumes: list[Optional[int]] = Field(default_factory=list)
    ask_prices: list[Optional[float]] = Field(default_factory=list)
    ask_volumes: list[Optional[int]] = Field(default_factory=list)
    mid_price: Optional[float] = None
    profit_and_loss: Optional[float] = None

    model_config = {"frozen": False}
