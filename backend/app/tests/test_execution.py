"""Tests for the ExecutionEngine."""

import pytest

from app.engines.execution.engine import ExecutionEngine
from app.models.backtest import ExecutionModel
from app.models.market import (
    BookLevel,
    OrderSide,
    OrderStatus,
    OrderType,
    TradePrint,
    VisibleOrderBook,
)
from app.models.trading import StrategyOrder


# ======================================================================
# Fixtures / helpers
# ======================================================================

def _make_book(bids, asks, product="X", timestamp=100):
    return VisibleOrderBook(
        product=product,
        timestamp=timestamp,
        bids=[BookLevel(price=p, volume=v, side=OrderSide.BUY) for p, v in bids],
        asks=[BookLevel(price=p, volume=v, side=OrderSide.SELL) for p, v in asks],
    )


def _make_order(
    order_id="o1",
    product="X",
    side=OrderSide.BUY,
    price=0.0,
    quantity=10,
    order_type=OrderType.LIMIT,
    timestamp=100,
):
    return StrategyOrder(
        order_id=order_id,
        product=product,
        side=side,
        order_type=order_type,
        price=price,
        quantity=quantity,
        timestamp=timestamp,
    )


@pytest.fixture
def balanced_engine():
    return ExecutionEngine(
        execution_model=ExecutionModel.BALANCED,
        position_limits={"X": 20},
        fees=0.0,
        slippage=0.0,
    )


@pytest.fixture
def conservative_engine():
    return ExecutionEngine(
        execution_model=ExecutionModel.CONSERVATIVE,
        position_limits={"X": 20},
        fees=0.0,
        slippage=0.0,
    )


@pytest.fixture
def optimistic_engine():
    return ExecutionEngine(
        execution_model=ExecutionModel.OPTIMISTIC,
        position_limits={"X": 20},
        fees=0.0,
        slippage=0.0,
    )


# ======================================================================
# Aggressive buy fills against the ask side
# ======================================================================

class TestAggressiveBuyFill:
    def test_full_fill_against_single_ask(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 20)],
        )
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=5)
        fills = balanced_engine.process_order(order, book)

        assert len(fills) == 1
        assert fills[0].price == pytest.approx(101.0)
        assert fills[0].quantity == 5
        assert fills[0].is_aggressive is True
        assert order.status == OrderStatus.FILLED

    def test_fill_walks_multiple_ask_levels(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 5), (102.0, 10)],
        )
        order = _make_order(side=OrderSide.BUY, price=102.0, quantity=8)
        fills = balanced_engine.process_order(order, book)

        assert len(fills) == 2
        assert fills[0].price == pytest.approx(101.0)
        assert fills[0].quantity == 5
        assert fills[1].price == pytest.approx(102.0)
        assert fills[1].quantity == 3
        assert order.status == OrderStatus.FILLED


# ======================================================================
# Aggressive sell fills against the bid side
# ======================================================================

class TestAggressiveSellFill:
    def test_full_fill_against_single_bid(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 20)],
            asks=[(101.0, 10)],
        )
        order = _make_order(side=OrderSide.SELL, price=99.0, quantity=5)
        fills = balanced_engine.process_order(order, book)

        assert len(fills) == 1
        assert fills[0].price == pytest.approx(99.0)
        assert fills[0].quantity == 5
        assert fills[0].is_aggressive is True

    def test_fill_walks_multiple_bid_levels(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 3), (98.0, 10)],
            asks=[(101.0, 10)],
        )
        order = _make_order(side=OrderSide.SELL, price=98.0, quantity=7)
        fills = balanced_engine.process_order(order, book)

        assert len(fills) == 2
        assert fills[0].quantity == 3  # consume 99.0 level
        assert fills[1].quantity == 4  # 4 from 98.0 level


# ======================================================================
# Partial fill when order exceeds book depth
# ======================================================================

class TestPartialFill:
    def test_partial_fill_excess_quantity(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 5)],
            asks=[(101.0, 3)],
        )
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=10)
        fills = balanced_engine.process_order(order, book)

        assert len(fills) == 1
        assert fills[0].quantity == 3
        assert order.filled_quantity == 3
        assert order.remaining_quantity == 7
        # Remaining should rest passively
        assert order.status == OrderStatus.PARTIAL_FILL


# ======================================================================
# Position limit rejection
# ======================================================================

class TestPositionLimitRejection:
    def test_buy_exceeds_limit_rejected(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 50)],
        )
        # Limit for X is 20; buying 25 from position 0 would give pos=25 > 20
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=25)
        fills = balanced_engine.process_order(order, book)

        assert fills == []
        assert order.status == OrderStatus.REJECTED

    def test_sell_exceeds_limit_rejected(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 50)],
            asks=[(101.0, 10)],
        )
        order = _make_order(side=OrderSide.SELL, price=99.0, quantity=25)
        fills = balanced_engine.process_order(order, book)

        assert fills == []
        assert order.status == OrderStatus.REJECTED

    def test_within_limit_accepted(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 50)],
        )
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=15)
        fills = balanced_engine.process_order(order, book)

        assert len(fills) > 0

    def test_no_limit_allows_any_size(self):
        engine = ExecutionEngine(
            execution_model=ExecutionModel.BALANCED,
            position_limits={},  # no limits
            fees=0.0,
            slippage=0.0,
        )
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 1000)],
        )
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=500)
        fills = engine.process_order(order, book)
        assert sum(f.quantity for f in fills) == 500


# ======================================================================
# Passive fill in CONSERVATIVE mode
# ======================================================================

class TestPassiveFillConservative:
    def test_passive_fill_with_matching_trade(self, conservative_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 15)],
        )
        # Place a passive buy at 98.0 (below best ask, so rests)
        order = _make_order(side=OrderSide.BUY, price=98.0, quantity=5)
        fills = conservative_engine.process_order(order, book)
        assert fills == []  # rests passively
        assert order.status == OrderStatus.ACTIVE

        # Now a trade comes in at 98.0 -- conservative requires actual trade at/through price
        trade = TradePrint(
            timestamp=200, buyer="A", seller="B", symbol="X",
            price=98.0, quantity=3,
        )
        passive_fills = conservative_engine.check_passive_fills(book, [trade])
        assert len(passive_fills) == 1
        assert passive_fills[0].quantity == 3
        assert passive_fills[0].is_aggressive is False

    def test_no_passive_fill_without_trade(self, conservative_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 15)],
        )
        order = _make_order(side=OrderSide.BUY, price=98.0, quantity=5)
        conservative_engine.process_order(order, book)

        # No trades -- no fills in conservative mode
        passive_fills = conservative_engine.check_passive_fills(book, [])
        assert passive_fills == []


# ======================================================================
# Passive allocation realism checks
# ======================================================================

class TestPassiveAllocation:
    def test_global_trade_quantity_consumption(self, conservative_engine):
        book = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        o1 = _make_order(order_id="o1", side=OrderSide.BUY, price=98.0, quantity=5, timestamp=100)
        o2 = _make_order(order_id="o2", side=OrderSide.BUY, price=97.0, quantity=5, timestamp=101)
        conservative_engine.process_order(o1, book)
        conservative_engine.process_order(o2, book)

        trade = TradePrint(
            timestamp=200, buyer="A", seller="B", symbol="X",
            price=97.0, quantity=6, aggressor_side=OrderSide.SELL,
        )
        fills = conservative_engine.check_passive_fills(book, [trade])

        assert sum(f.quantity for f in fills) == 6
        assert len(fills) == 2
        assert fills[0].order_id == "o1"
        assert fills[0].quantity == 5
        assert fills[1].order_id == "o2"
        assert fills[1].quantity == 1

    def test_price_time_priority(self, conservative_engine):
        book = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        best_price = _make_order(order_id="best", side=OrderSide.BUY, price=99.0, quantity=4, timestamp=101)
        older = _make_order(order_id="older", side=OrderSide.BUY, price=98.0, quantity=2, timestamp=100)
        newer = _make_order(order_id="newer", side=OrderSide.BUY, price=98.0, quantity=2, timestamp=200)
        conservative_engine.process_order(older, book)
        conservative_engine.process_order(newer, book)
        conservative_engine.process_order(best_price, book)

        trade = TradePrint(
            timestamp=300, buyer="A", seller="B", symbol="X",
            price=98.0, quantity=7, aggressor_side=OrderSide.SELL,
        )
        fills = conservative_engine.check_passive_fills(book, [trade])

        assert [f.order_id for f in fills] == ["best", "older", "newer"]
        assert [f.quantity for f in fills] == [4, 2, 1]

    def test_aggressor_side_enforcement(self, conservative_engine):
        book = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        buy_order = _make_order(order_id="buy", side=OrderSide.BUY, price=100.0, quantity=5)
        sell_order = _make_order(order_id="sell", side=OrderSide.SELL, price=100.0, quantity=5)
        conservative_engine.process_order(buy_order, book)
        conservative_engine.process_order(sell_order, book)

        buy_aggr_trade = TradePrint(
            timestamp=200, buyer="A", seller="B", symbol="X",
            price=100.0, quantity=3, aggressor_side=OrderSide.BUY,
        )
        fills = conservative_engine.check_passive_fills(book, [buy_aggr_trade])
        assert [f.order_id for f in fills] == ["sell"]

        sell_aggr_trade = TradePrint(
            timestamp=201, buyer="A", seller="B", symbol="X",
            price=100.0, quantity=3, aggressor_side=OrderSide.SELL,
        )
        fills = conservative_engine.check_passive_fills(book, [sell_aggr_trade])
        assert [f.order_id for f in fills] == ["buy"]

    def test_missing_aggressor_side_fallback_conservative(self, conservative_engine):
        book = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        buy_order = _make_order(order_id="buy", side=OrderSide.BUY, price=100.0, quantity=5)
        sell_order = _make_order(order_id="sell", side=OrderSide.SELL, price=102.0, quantity=5)
        conservative_engine.process_order(buy_order, book)
        conservative_engine.process_order(sell_order, book)

        low_trade = TradePrint(
            timestamp=200, buyer="A", seller="B", symbol="X",
            price=100.0, quantity=2, aggressor_side=None,
        )
        high_trade = TradePrint(
            timestamp=201, buyer="A", seller="B", symbol="X",
            price=102.0, quantity=2, aggressor_side=None,
        )

        fills_low = conservative_engine.check_passive_fills(book, [low_trade])
        assert [f.order_id for f in fills_low] == ["buy"]

        fills_high = conservative_engine.check_passive_fills(book, [high_trade])
        assert [f.order_id for f in fills_high] == ["sell"]


# ======================================================================
# Order cancellation
# ======================================================================

class TestCancelOrder:
    def test_cancel_resting_order(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 15)],
        )
        order = _make_order(order_id="cancel_me", side=OrderSide.BUY, price=98.0, quantity=5)
        balanced_engine.process_order(order, book)
        assert order.status == OrderStatus.ACTIVE

        result = balanced_engine.cancel_order("cancel_me")
        assert result is True
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_nonexistent_order(self, balanced_engine):
        result = balanced_engine.cancel_order("does_not_exist")
        assert result is False

    def test_cancelled_order_not_filled(self, balanced_engine):
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 15)],
        )
        order = _make_order(order_id="c1", side=OrderSide.BUY, price=98.0, quantity=5)
        balanced_engine.process_order(order, book)
        balanced_engine.cancel_order("c1")

        # After cancellation, passive fill check should not fill it
        trade = TradePrint(
            timestamp=200, buyer="A", seller="B", symbol="X",
            price=97.0, quantity=10,
        )
        passive_fills = balanced_engine.check_passive_fills(book, [trade])
        assert passive_fills == []


# ======================================================================
# Fee application
# ======================================================================

class TestFeeApplication:
    def test_fees_applied_to_buy(self):
        engine = ExecutionEngine(
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 100},
            fees=0.5,
            slippage=0.0,
        )
        book = _make_book(
            bids=[(99.0, 10)],
            asks=[(101.0, 20)],
        )
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=5)
        fills = engine.process_order(order, book)

        # Fee makes buy price worse: 101.0 + 0.5 = 101.5
        assert fills[0].price == pytest.approx(101.5)

    def test_fees_applied_to_sell(self):
        engine = ExecutionEngine(
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 100},
            fees=0.5,
            slippage=0.0,
        )
        book = _make_book(
            bids=[(99.0, 20)],
            asks=[(101.0, 10)],
        )
        order = _make_order(side=OrderSide.SELL, price=99.0, quantity=5)
        fills = engine.process_order(order, book)

        # Fee makes sell price worse: 99.0 - 0.5 = 98.5
        assert fills[0].price == pytest.approx(98.5)

    def test_slippage_applied(self):
        engine = ExecutionEngine(
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 100},
            fees=0.0,
            slippage=0.1,
        )
        book = _make_book(
            bids=[(99.0, 20)],
            asks=[(101.0, 20)],
        )
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=5)
        fills = engine.process_order(order, book)

        # Slippage on aggressive buy: 101.0 + 0.1 = 101.1
        assert fills[0].price == pytest.approx(101.1)

    def test_fees_and_slippage_combined(self):
        engine = ExecutionEngine(
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 100},
            fees=0.5,
            slippage=0.1,
        )
        book = _make_book(
            bids=[(99.0, 20)],
            asks=[(101.0, 20)],
        )
        order = _make_order(side=OrderSide.BUY, price=101.0, quantity=5)
        fills = engine.process_order(order, book)

        # Slippage first: 101.0 + 0.1 = 101.1, then fee: 101.1 + 0.5 = 101.6
        assert fills[0].price == pytest.approx(101.6)
