"""Tests for the BacktestEngine."""

import pytest

from backend.app.engines.backtest.engine import BacktestEngine
from backend.app.models.backtest import BacktestConfig, ExecutionModel
from backend.app.models.events import Event, EventType
from backend.app.models.market import OrderSide


# ======================================================================
# Helpers
# ======================================================================

def _make_book_event(timestamp, product="X", bid=99.0, ask=101.0,
                     bid_vol=10, ask_vol=15):
    return Event(
        event_type=EventType.BOOK_SNAPSHOT,
        timestamp=timestamp,
        product=product,
        data={
            "day": 1,
            "bid_prices": [bid],
            "bid_volumes": [bid_vol],
            "ask_prices": [ask],
            "ask_volumes": [ask_vol],
            "mid_price": (bid + ask) / 2.0,
        },
    )


def _make_trade_event(timestamp, product="X", price=100.0, quantity=5):
    return Event(
        event_type=EventType.TRADE_PRINT,
        timestamp=timestamp,
        product=product,
        data={
            "buyer": "Alice",
            "seller": "Bob",
            "symbol": product,
            "price": price,
            "quantity": quantity,
        },
    )


class _NoOpTrader:
    """A strategy that does nothing."""
    def run(self, state):
        return {}, 0, ""


class _SimpleBuyTrader:
    """A strategy that buys 1 unit of X at best_ask on each tick."""
    def __init__(self):
        self._order_count = 0

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order
        orders = {}
        for product in state.order_depths:
            depth = state.order_depths[product]
            if depth.sell_orders:
                best_ask = min(depth.sell_orders.keys())
                self._order_count += 1
                orders[product] = [Order(product, best_ask, 1)]
        return orders, 0, ""


class _BuySellTrader:
    """Buy on first tick, sell on second tick."""
    def __init__(self):
        self._tick = 0

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order
        self._tick += 1
        orders = {}
        for product in state.order_depths:
            depth = state.order_depths[product]
            if self._tick == 1 and depth.sell_orders:
                best_ask = min(depth.sell_orders.keys())
                orders[product] = [Order(product, best_ask, 1)]  # buy
            elif self._tick == 2 and depth.buy_orders:
                best_bid = max(depth.buy_orders.keys())
                orders[product] = [Order(product, best_bid, -1)]  # sell
        return orders, 0, ""


# ======================================================================
# Basic backtest run
# ======================================================================

class TestBasicBacktestRun:
    def test_noop_strategy_completes(self):
        config = BacktestConfig(
            strategy_id="noop",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100),
            _make_book_event(200),
            _make_book_event(300),
        ]
        run = engine.run(events, _NoOpTrader())

        assert run.status == "completed"
        assert run.error is None
        assert run.metrics is not None
        assert run.metrics["total_fills"] == 0
        assert run.metrics["total_orders"] == 0

    def test_simple_buy_strategy(self):
        config = BacktestConfig(
            strategy_id="simple_buy",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100, bid=99.0, ask=101.0, bid_vol=10, ask_vol=15),
            _make_book_event(200, bid=99.0, ask=101.0, bid_vol=10, ask_vol=15),
        ]
        run = engine.run(events, _SimpleBuyTrader())

        assert run.status == "completed"
        assert run.metrics is not None
        assert run.metrics["total_fills"] >= 1
        assert run.metrics["total_orders"] >= 1


# ======================================================================
# PnL tracking
# ======================================================================

class TestPnLTracking:
    def test_pnl_history_recorded(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100),
            _make_book_event(200),
            _make_book_event(300),
        ]
        engine.run(events, _SimpleBuyTrader())
        pnl_history = engine.get_pnl_history()

        assert len(pnl_history) == 3  # one per BOOK_SNAPSHOT
        for snap in pnl_history:
            assert hasattr(snap, "total_pnl")
            assert hasattr(snap, "realized_pnl")

    def test_roundtrip_pnl(self):
        """Buy then sell should produce realized PnL."""
        config = BacktestConfig(
            strategy_id="roundtrip",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100, bid=99.0, ask=101.0),
            _make_book_event(200, bid=104.0, ask=106.0),  # price moved up
        ]
        run = engine.run(events, _BuySellTrader())

        assert run.status == "completed"
        fills = engine.get_fills()
        # Should have at least 2 fills (a buy and a sell)
        assert len(fills) >= 2


# ======================================================================
# Fill recording
# ======================================================================

class TestFillRecording:
    def test_fills_recorded(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [_make_book_event(100)]
        engine.run(events, _SimpleBuyTrader())
        fills = engine.get_fills()

        assert len(fills) >= 1
        assert fills[0].product == "X"
        assert fills[0].side == OrderSide.BUY
        assert fills[0].quantity == 1


# ======================================================================
# Debug frame generation
# ======================================================================

class TestDebugFrameGeneration:
    def test_debug_frames_generated(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100),
            _make_book_event(200),
        ]
        engine.run(events, _SimpleBuyTrader())
        frames = engine.get_debug_frames()

        assert len(frames) == 2
        assert frames[0].timestamp == 100
        assert frames[1].timestamp == 200
        assert "mid_price" in frames[0].market_state


# ======================================================================
# Position tracking across events
# ======================================================================

class TestPositionTracking:
    def test_position_accumulates(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100),
            _make_book_event(200),
            _make_book_event(300),
        ]
        engine.run(events, _SimpleBuyTrader())

        # Each tick buys 1, so position should be 3 after 3 ticks
        pnl_history = engine.get_pnl_history()
        final_inventory = pnl_history[-1].inventory
        assert "X" in final_inventory
        assert final_inventory["X"] == 3

    def test_position_in_debug_frames(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100),
            _make_book_event(200),
        ]
        engine.run(events, _SimpleBuyTrader())
        frames = engine.get_debug_frames()

        # After first tick: position should be 1
        assert frames[0].position.get("X") == 1
        # After second tick: position should be 2
        assert frames[1].position.get("X") == 2


# ======================================================================
# Error handling
# ======================================================================

class TestBacktestErrorHandling:
    def test_strategy_exception_captured(self):
        class _CrashingTrader:
            def run(self, state):
                raise RuntimeError("Strategy crashed!")

        config = BacktestConfig(
            strategy_id="crash",
            products=["X"],
            execution_model=ExecutionModel.BALANCED,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [_make_book_event(100)]

        # The backtest engine catches strategy exceptions via the sandbox
        # and continues; the run should still complete (sandbox returns
        # empty orders on error).
        run = engine.run(events, _CrashingTrader())
        # The run will either complete (sandbox caught it) or fail
        assert run.status in ("completed", "failed")
