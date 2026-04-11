"""Tests for all Pydantic domain models."""

import pytest

from app.models.market import (
    BookLevel,
    MarketSnapshot,
    OrderSide,
    OrderStatus,
    OrderType,
    TradePrint,
    VisibleOrderBook,
)
from app.models.events import Event, EventType
from app.models.trading import (
    FillEvent,
    InventoryState,
    PnLState,
    PositionState,
    StrategyOrder,
)
from app.models.backtest import BacktestConfig, BacktestRun, ExecutionModel, TradeMatchingMode
from app.models.strategy import DebugFrame, StrategyDefinition, StrategyParameter


# ======================================================================
# MarketSnapshot
# ======================================================================

class TestMarketSnapshot:
    def test_creation_minimal(self):
        snap = MarketSnapshot(day=1, timestamp=100, product="EMERALDS")
        assert snap.day == 1
        assert snap.timestamp == 100
        assert snap.product == "EMERALDS"
        assert snap.bid_prices == []
        assert snap.ask_prices == []
        assert snap.mid_price is None
        assert snap.profit_and_loss is None

    def test_creation_full(self):
        snap = MarketSnapshot(
            day=2,
            timestamp=200,
            product="TOMATOES",
            bid_prices=[99.0, 98.0, 97.0],
            bid_volumes=[10, 20, 30],
            ask_prices=[101.0, 102.0, 103.0],
            ask_volumes=[15, 25, 35],
            mid_price=100.0,
            profit_and_loss=50.5,
        )
        assert snap.mid_price == 100.0
        assert snap.profit_and_loss == 50.5
        assert len(snap.bid_prices) == 3
        assert len(snap.ask_volumes) == 3

    def test_none_levels(self):
        snap = MarketSnapshot(
            day=1,
            timestamp=100,
            product="EMERALDS",
            bid_prices=[99.0, None, None],
            bid_volumes=[10, None, None],
            ask_prices=[101.0, None, None],
            ask_volumes=[15, None, None],
        )
        assert snap.bid_prices[1] is None
        assert snap.ask_volumes[2] is None

    def test_serialization_roundtrip(self):
        snap = MarketSnapshot(
            day=1, timestamp=100, product="EMERALDS",
            bid_prices=[99.0], bid_volumes=[10],
            ask_prices=[101.0], ask_volumes=[15],
            mid_price=100.0,
        )
        data = snap.model_dump()
        restored = MarketSnapshot(**data)
        assert restored.day == snap.day
        assert restored.product == snap.product
        assert restored.mid_price == snap.mid_price


# ======================================================================
# VisibleOrderBook
# ======================================================================

class TestVisibleOrderBook:
    def _make_book(self, bids, asks):
        """Helper: bids/asks are lists of (price, volume)."""
        return VisibleOrderBook(
            product="EMERALDS",
            timestamp=100,
            bids=[BookLevel(price=p, volume=v, side=OrderSide.BUY) for p, v in bids],
            asks=[BookLevel(price=p, volume=v, side=OrderSide.SELL) for p, v in asks],
        )

    def test_best_bid_ask(self):
        book = self._make_book(
            bids=[(99.0, 10), (98.0, 20)],
            asks=[(101.0, 15), (102.0, 25)],
        )
        assert book.best_bid == 99.0
        assert book.best_ask == 101.0

    def test_spread(self):
        book = self._make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 15)],
        )
        assert book.spread == pytest.approx(2.0)

    def test_mid_price(self):
        book = self._make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 15)],
        )
        assert book.mid_price == pytest.approx(100.0)

    def test_microprice_weighted_mid(self):
        # microprice = (bid_price * ask_vol + ask_price * bid_vol) / (bid_vol + ask_vol)
        book = self._make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 30)],
        )
        expected = (99.0 * 30 + 101.0 * 10) / (10 + 30)
        assert book.microprice == pytest.approx(expected)
        assert book.weighted_mid == pytest.approx(expected)

    def test_top_level_imbalance(self):
        book = self._make_book(
            bids=[(99.0, 30)],
            asks=[(101.0, 10)],
        )
        # (30 - 10) / (30 + 10) = 0.5
        assert book.top_level_imbalance == pytest.approx(0.5)

    def test_top3_imbalance(self):
        book = self._make_book(
            bids=[(99.0, 10), (98.0, 20), (97.0, 30)],
            asks=[(101.0, 15), (102.0, 25), (103.0, 35)],
        )
        bid_vol = 10 + 20 + 30  # 60
        ask_vol = 15 + 25 + 35  # 75
        expected = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        assert book.top3_imbalance == pytest.approx(expected)

    def test_total_bid_ask_depth(self):
        book = self._make_book(
            bids=[(99.0, 10), (98.0, 20)],
            asks=[(101.0, 15), (102.0, 25)],
        )
        assert book.total_bid_depth == 30
        assert book.total_ask_depth == 40

    def test_book_pressure(self):
        book = self._make_book(
            bids=[(99.0, 60)],
            asks=[(101.0, 40)],
        )
        # 60 / (60 + 40) = 0.6
        assert book.book_pressure == pytest.approx(0.6)

    def test_depth_skew(self):
        book = self._make_book(
            bids=[(99.0, 60)],
            asks=[(101.0, 40)],
        )
        # (60 - 40) / (60 + 40) = 0.2
        assert book.depth_skew == pytest.approx(0.2)

    def test_empty_book_returns_none(self):
        book = self._make_book(bids=[], asks=[])
        assert book.best_bid is None
        assert book.best_ask is None
        assert book.spread is None
        assert book.mid_price is None
        assert book.microprice is None
        assert book.top_level_imbalance is None
        assert book.book_pressure is None

    def test_one_sided_book(self):
        book = self._make_book(bids=[(99.0, 10)], asks=[])
        assert book.best_bid == 99.0
        assert book.best_ask is None
        assert book.spread is None
        assert book.mid_price is None


# ======================================================================
# TradePrint
# ======================================================================

class TestTradePrint:
    def test_creation(self):
        trade = TradePrint(
            timestamp=1000,
            buyer="Alice",
            seller="Bob",
            symbol="EMERALDS",
            currency="SEASHELLS",
            price=100.0,
            quantity=5,
        )
        assert trade.timestamp == 1000
        assert trade.buyer == "Alice"
        assert trade.quantity == 5
        assert trade.aggressor_side is None

    def test_with_aggressor(self):
        trade = TradePrint(
            timestamp=1000,
            buyer="Alice",
            seller="Bob",
            symbol="EMERALDS",
            price=100.0,
            quantity=5,
            aggressor_side=OrderSide.BUY,
        )
        assert trade.aggressor_side == OrderSide.BUY

    def test_default_currency(self):
        trade = TradePrint(
            timestamp=1, buyer="A", seller="B", symbol="X", price=1.0, quantity=1,
        )
        assert trade.currency == "SEASHELLS"


# ======================================================================
# Event
# ======================================================================

class TestEvent:
    def test_creation(self):
        event = Event(
            event_type=EventType.BOOK_SNAPSHOT,
            timestamp=100,
            product="EMERALDS",
            data={"mid_price": 100.0},
            sequence_num=1,
        )
        assert event.event_type == EventType.BOOK_SNAPSHOT
        assert event.timestamp == 100
        assert event.data["mid_price"] == 100.0

    def test_defaults(self):
        event = Event(event_type=EventType.TIMER_TICK, timestamp=0)
        assert event.product is None
        assert event.data == {}
        assert event.sequence_num == 0

    def test_serialization_roundtrip(self):
        event = Event(
            event_type=EventType.TRADE_PRINT,
            timestamp=500,
            product="TOMATOES",
            data={"price": 55.0, "quantity": 3},
            sequence_num=42,
        )
        data = event.model_dump()
        restored = Event(**data)
        assert restored.event_type == EventType.TRADE_PRINT
        assert restored.timestamp == 500
        assert restored.sequence_num == 42
        assert restored.data["price"] == 55.0


# ======================================================================
# StrategyOrder
# ======================================================================

class TestStrategyOrder:
    def test_remaining_quantity(self):
        order = StrategyOrder(
            order_id="o1",
            product="EMERALDS",
            side=OrderSide.BUY,
            quantity=10,
            filled_quantity=3,
        )
        assert order.remaining_quantity == 7

    def test_is_complete_filled(self):
        order = StrategyOrder(
            order_id="o1",
            product="EMERALDS",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
        )
        assert order.is_complete is True

    def test_is_complete_cancelled(self):
        order = StrategyOrder(
            order_id="o1",
            product="EMERALDS",
            side=OrderSide.BUY,
            status=OrderStatus.CANCELLED,
        )
        assert order.is_complete is True

    def test_is_complete_rejected(self):
        order = StrategyOrder(
            order_id="o1",
            product="EMERALDS",
            side=OrderSide.BUY,
            status=OrderStatus.REJECTED,
        )
        assert order.is_complete is True

    def test_is_not_complete_active(self):
        order = StrategyOrder(
            order_id="o1",
            product="EMERALDS",
            side=OrderSide.BUY,
            status=OrderStatus.ACTIVE,
        )
        assert order.is_complete is False

    def test_is_not_complete_pending(self):
        order = StrategyOrder(
            order_id="o1",
            product="EMERALDS",
            side=OrderSide.BUY,
            status=OrderStatus.PENDING,
        )
        assert order.is_complete is False

    def test_defaults(self):
        order = StrategyOrder(
            order_id="o1", product="X", side=OrderSide.BUY,
        )
        assert order.order_type == OrderType.LIMIT
        assert order.price == 0.0
        assert order.quantity == 0
        assert order.status == OrderStatus.PENDING


# ======================================================================
# PositionState
# ======================================================================

class TestPositionState:
    def test_net_exposure(self):
        pos = PositionState(product="EMERALDS", quantity=10, mark_price=100.0)
        assert pos.net_exposure == pytest.approx(1000.0)

    def test_net_exposure_short(self):
        pos = PositionState(product="EMERALDS", quantity=-5, mark_price=100.0)
        assert pos.net_exposure == pytest.approx(500.0)

    def test_total_pnl(self):
        pos = PositionState(
            product="EMERALDS",
            realized_pnl=50.0,
            unrealized_pnl=30.0,
        )
        assert pos.total_pnl == pytest.approx(80.0)

    def test_zero_position(self):
        pos = PositionState(product="X")
        assert pos.quantity == 0
        assert pos.net_exposure == 0.0
        assert pos.total_pnl == 0.0


# ======================================================================
# BacktestConfig
# ======================================================================

class TestBacktestConfig:
    def test_defaults(self):
        config = BacktestConfig(strategy_id="test")
        assert config.trade_matching == TradeMatchingMode.ALL
        assert config.products == []
        assert config.days == []
        assert config.initial_cash == 0.0
        assert config.position_limits == {}

    def test_custom_values(self):
        config = BacktestConfig(
            strategy_id="mm",
            products=["EMERALDS", "TOMATOES"],
            days=[1, 2],
            trade_matching=TradeMatchingMode.WORSE,
            position_limits={"EMERALDS": 20},
            initial_cash=10000.0,
        )
        assert config.trade_matching == TradeMatchingMode.WORSE
        assert config.position_limits["EMERALDS"] == 20

    def test_get_position_limit_builtin(self):
        config = BacktestConfig(strategy_id="test")
        # RAINFOREST_RESIN has a built-in limit of 50
        assert config.get_position_limit("RAINFOREST_RESIN") == 50
        # Unknown product falls back to DEFAULT_POSITION_LIMIT (50)
        assert config.get_position_limit("UNKNOWN_PRODUCT") == 50

    def test_get_position_limit_custom_override(self):
        config = BacktestConfig(
            strategy_id="test",
            position_limits={"RAINFOREST_RESIN": 100},
        )
        assert config.get_position_limit("RAINFOREST_RESIN") == 100


# ======================================================================
# DebugFrame
# ======================================================================

class TestDebugFrame:
    def test_defaults(self):
        frame = DebugFrame()
        assert frame.timestamp == 0
        assert frame.product == ""
        assert frame.market_state == {}
        assert frame.fills == []
        assert frame.warnings == []

    def test_populated(self):
        frame = DebugFrame(
            timestamp=1000,
            product="EMERALDS",
            market_state={"mid_price": 100.0},
            orders_submitted=[{"order_id": "o1"}],
            fills=[{"price": 100.0}],
            warnings=["Position limit near"],
        )
        assert frame.timestamp == 1000
        assert len(frame.orders_submitted) == 1
        assert len(frame.warnings) == 1
