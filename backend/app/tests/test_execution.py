"""Tests for the ExecutionEngine (Prosperity-accurate matching)."""

import pytest

from app.engines.execution.engine import ExecutionEngine, MarketTrade
from app.models.backtest import TradeMatchingMode
from app.models.market import OrderSide, TradePrint


# ======================================================================
# Helpers
# ======================================================================

class _Order:
    """Minimal Prosperity-style Order for testing."""
    def __init__(self, symbol: str, price: int, quantity: int):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity


def _make_engine(mode=TradeMatchingMode.ALL, limits=None):
    return ExecutionEngine(
        trade_matching_mode=mode,
        position_limits=limits or {"X": 20},
        default_limit=50,
    )


def _make_market_trade(symbol="X", price=100.0, quantity=5):
    tp = TradePrint(
        timestamp=100, buyer="A", seller="B",
        symbol=symbol, price=price, quantity=quantity,
    )
    return MarketTrade.from_trade_print(tp)


# ======================================================================
# Buy order matching against ask side of book
# ======================================================================

class TestBuyOrderBookMatching:
    def test_full_fill_at_ask_price(self):
        engine = _make_engine()
        # Buy at 101, ask at 101 with volume 20
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 5)],
            buy_orders={99: 10},
            sell_orders={101: -20},
            market_trades=[],
        )
        assert len(fills) == 1
        assert fills[0].price == 101.0
        assert fills[0].quantity == 5
        assert fills[0].is_aggressive is True
        assert fills[0].side == OrderSide.BUY

    def test_walks_multiple_ask_levels(self):
        engine = _make_engine()
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 103, 8)],
            buy_orders={99: 10},
            sell_orders={101: -5, 102: -10},
            market_trades=[],
        )
        assert len(fills) == 2
        assert fills[0].price == 101.0
        assert fills[0].quantity == 5
        assert fills[1].price == 102.0
        assert fills[1].quantity == 3

    def test_price_improvement(self):
        """Buy at 105 but best ask is 101 -> fills at 101."""
        engine = _make_engine()
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 105, 3)],
            buy_orders={99: 10},
            sell_orders={101: -10},
            market_trades=[],
        )
        assert fills[0].price == 101.0

    def test_no_fill_if_price_below_asks(self):
        engine = _make_engine()
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 99, 5)],
            buy_orders={98: 10},
            sell_orders={101: -20},
            market_trades=[],
        )
        assert fills == []

    def test_consumes_book_volume(self):
        engine = _make_engine()
        sell_orders = {101: -10}
        engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 7)],
            buy_orders={99: 10},
            sell_orders=sell_orders,
            market_trades=[],
        )
        # 10 - 7 = 3 remaining
        assert sell_orders[101] == -3

    def test_removes_level_when_fully_consumed(self):
        engine = _make_engine()
        sell_orders = {101: -5}
        engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 5)],
            buy_orders={99: 10},
            sell_orders=sell_orders,
            market_trades=[],
        )
        assert 101 not in sell_orders


# ======================================================================
# Sell order matching against bid side of book
# ======================================================================

class TestSellOrderBookMatching:
    def test_full_fill_at_bid_price(self):
        engine = _make_engine()
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 99, -5)],
            buy_orders={99: 20},
            sell_orders={101: -10},
            market_trades=[],
        )
        assert len(fills) == 1
        assert fills[0].price == 99.0
        assert fills[0].quantity == 5
        assert fills[0].side == OrderSide.SELL

    def test_walks_multiple_bid_levels(self):
        engine = _make_engine()
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 97, -8)],
            buy_orders={99: 3, 98: 10},
            sell_orders={101: -10},
            market_trades=[],
        )
        assert len(fills) == 2
        assert fills[0].price == 99.0
        assert fills[0].quantity == 3
        assert fills[1].price == 98.0
        assert fills[1].quantity == 5

    def test_price_improvement_for_seller(self):
        """Sell at 95 but best bid is 99 -> fills at 99."""
        engine = _make_engine()
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 95, -3)],
            buy_orders={99: 10},
            sell_orders={101: -10},
            market_trades=[],
        )
        assert fills[0].price == 99.0


# ======================================================================
# Market trade matching (Phase 2)
# ======================================================================

class TestMarketTradeMatching:
    def test_buy_matches_market_trade(self):
        """After book exhausted, match remaining against market trade."""
        engine = _make_engine(mode=TradeMatchingMode.ALL)
        mt = _make_market_trade(price=100, quantity=10)
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 100, 5)],
            buy_orders={98: 10},
            sell_orders={},  # empty book
            market_trades=[mt],
        )
        assert len(fills) == 1
        # Fills at ORDER's price, not market trade's price
        assert fills[0].price == 100.0
        assert fills[0].quantity == 5
        assert fills[0].is_aggressive is False

    def test_sell_matches_market_trade(self):
        engine = _make_engine(mode=TradeMatchingMode.ALL)
        mt = _make_market_trade(price=100, quantity=10)
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 100, -5)],
            buy_orders={},
            sell_orders={},
            market_trades=[mt],
        )
        assert len(fills) == 1
        assert fills[0].price == 100.0
        assert fills[0].side == OrderSide.SELL

    def test_worse_mode_skips_equal_price(self):
        engine = _make_engine(mode=TradeMatchingMode.WORSE)
        mt = _make_market_trade(price=100, quantity=10)
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 100, 5)],
            buy_orders={},
            sell_orders={},
            market_trades=[mt],
        )
        # WORSE mode: trade at 100 == order at 100, so no fill
        assert fills == []

    def test_worse_mode_fills_at_better_price(self):
        engine = _make_engine(mode=TradeMatchingMode.WORSE)
        mt = _make_market_trade(price=99, quantity=10)
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 100, 5)],
            buy_orders={},
            sell_orders={},
            market_trades=[mt],
        )
        # WORSE mode: trade at 99 < order at 100, so fills
        assert len(fills) == 1
        assert fills[0].price == 100.0  # at order price

    def test_none_mode_skips_market_trades(self):
        engine = _make_engine(mode=TradeMatchingMode.NONE)
        mt = _make_market_trade(price=100, quantity=10)
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 100, 5)],
            buy_orders={},
            sell_orders={},
            market_trades=[mt],
        )
        assert fills == []

    def test_market_trade_capacity_consumed(self):
        """Two orders consuming the same market trade."""
        engine = _make_engine(mode=TradeMatchingMode.ALL)
        mt = _make_market_trade(price=100, quantity=6)
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 100, 4), _Order("X", 100, 4)],
            buy_orders={},
            sell_orders={},
            market_trades=[mt],
        )
        total_filled = sum(f.quantity for f in fills)
        # Only 6 available from the market trade
        assert total_filled == 6

    def test_book_then_market_trade(self):
        """Book partially fills, then market trade fills the rest."""
        engine = _make_engine(mode=TradeMatchingMode.ALL)
        mt = _make_market_trade(price=101, quantity=10)
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 8)],
            buy_orders={99: 10},
            sell_orders={101: -3},  # only 3 in book
            market_trades=[mt],
        )
        # 3 from book + 5 from market trade
        assert len(fills) == 2
        assert fills[0].quantity == 3
        assert fills[0].price == 101.0  # book price
        assert fills[0].is_aggressive is True
        assert fills[1].quantity == 5
        assert fills[1].price == 101.0  # order price
        assert fills[1].is_aggressive is False


# ======================================================================
# Position limit enforcement
# ======================================================================

class TestPositionLimits:
    def test_per_fill_clamping_buy(self):
        engine = _make_engine(limits={"X": 5})
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 10)],
            buy_orders={99: 10},
            sell_orders={101: -20},
            market_trades=[],
        )
        total = sum(f.quantity for f in fills)
        assert total == 5  # clamped to limit

    def test_per_fill_clamping_sell(self):
        engine = _make_engine(limits={"X": 5})
        fills = engine.match_orders(
            product="X",
            orders=[_Order("X", 99, -10)],
            buy_orders={99: 20},
            sell_orders={101: -10},
            market_trades=[],
        )
        total = sum(f.quantity for f in fills)
        assert total == 5

    def test_enforce_limits_aggregate_cancel(self):
        engine = _make_engine(limits={"X": 10})
        orders = {
            "X": [_Order("X", 101, 6), _Order("X", 101, 6)],  # total 12 > 10
        }
        result = engine.enforce_limits(orders)
        assert result["X"] == []

    def test_enforce_limits_passes_within_limit(self):
        engine = _make_engine(limits={"X": 20})
        orders = {
            "X": [_Order("X", 101, 5), _Order("X", 101, 5)],  # total 10 <= 20
        }
        result = engine.enforce_limits(orders)
        assert len(result["X"]) == 2

    def test_default_limit_used_for_unknown_product(self):
        engine = _make_engine(limits={}, )
        engine._default_limit = 50
        fills = engine.match_orders(
            product="Y",
            orders=[_Order("Y", 101, 100)],
            buy_orders={99: 10},
            sell_orders={101: -200},
            market_trades=[],
        )
        total = sum(f.quantity for f in fills)
        assert total == 50


# ======================================================================
# Position tracking
# ======================================================================

class TestPositionTracking:
    def test_position_updated_after_buy(self):
        engine = _make_engine()
        engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 5)],
            buy_orders={99: 10},
            sell_orders={101: -20},
            market_trades=[],
        )
        assert engine.get_position("X") == 5

    def test_position_updated_after_sell(self):
        engine = _make_engine()
        engine.match_orders(
            product="X",
            orders=[_Order("X", 99, -5)],
            buy_orders={99: 20},
            sell_orders={101: -10},
            market_trades=[],
        )
        assert engine.get_position("X") == -5

    def test_position_accumulates(self):
        engine = _make_engine()
        engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 3)],
            buy_orders={99: 10},
            sell_orders={101: -20},
            market_trades=[],
        )
        engine.match_orders(
            product="X",
            orders=[_Order("X", 101, 2)],
            buy_orders={99: 10},
            sell_orders={101: -20},
            market_trades=[],
        )
        assert engine.get_position("X") == 5
