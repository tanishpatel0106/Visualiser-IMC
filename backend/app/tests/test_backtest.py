"""Tests for the BacktestEngine."""

import pytest

from app.engines.backtest.engine import BacktestEngine
from app.models.backtest import BacktestConfig, TradeMatchingMode
from app.models.events import Event, EventType
from app.models.market import OrderSide


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
    def run(self, state):
        from app.engines.sandbox.adapter import Order
        orders = {}
        for product in state.order_depths:
            depth = state.order_depths[product]
            if depth.sell_orders:
                best_ask = min(depth.sell_orders.keys())
                orders[product] = [Order(product, best_ask, 1)]
        return orders, 0, ""


class _BuySellTrader:
    """Buy on first tick, sell on second tick."""
    def __init__(self):
        self._tick = 0

    def run(self, state):
        from app.engines.sandbox.adapter import Order
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


class _ReadTraderDataTrader:
    """Returns the incoming traderData so tests can assert initial parameters."""
    def __init__(self):
        self.first_trader_data: str | None = None

    def run(self, state):
        if self.first_trader_data is None:
            self.first_trader_data = state.traderData
        return {}, 0, state.traderData


class _CaptureDepthTrader:
    """Captures order depth products for assertion."""
    def __init__(self):
        self.snapshots: list[dict[str, tuple[int, int]]] = []

    def run(self, state):
        snap: dict[str, tuple[int, int]] = {}
        for product, depth in state.order_depths.items():
            snap[product] = (len(depth.buy_orders), len(depth.sell_orders))
        self.snapshots.append(snap)
        return {}, 0, ""


# ======================================================================
# Basic backtest run
# ======================================================================

class TestBasicBacktestRun:
    def test_noop_strategy_completes(self):
        config = BacktestConfig(
            strategy_id="noop",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
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
            trade_matching=TradeMatchingMode.ALL,
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

    def test_initial_strategy_parameters_seed_trader_data(self):
        config = BacktestConfig(
            strategy_id="param_seed",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
            parameters={"spread": 8, "order_size": 3},
        )
        engine = BacktestEngine(config)
        trader = _ReadTraderDataTrader()
        events = [_make_book_event(100)]
        run = engine.run(events, trader)

        assert run.status == "completed"
        assert trader.first_trader_data == '{"spread": 8, "order_size": 3}'


# ======================================================================
# PnL tracking (cash-flow based)
# ======================================================================

class TestPnLTracking:
    def test_pnl_history_recorded(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
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

        assert len(pnl_history) == 3
        for snap in pnl_history:
            assert hasattr(snap, "total_pnl")
            assert hasattr(snap, "realized_pnl")

    def test_roundtrip_pnl(self):
        """Buy then sell should produce fills and PnL."""
        config = BacktestConfig(
            strategy_id="roundtrip",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100, bid=99.0, ask=101.0),
            _make_book_event(200, bid=104.0, ask=106.0),
        ]
        run = engine.run(events, _BuySellTrader())

        assert run.status == "completed"
        fills = engine.get_fills()
        assert len(fills) >= 2

    def test_cash_flow_pnl_buy(self):
        """Buying 1 at 101 with mid 100 => cash = -101, total = -101 + 1*100 = -1."""
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [_make_book_event(100, bid=99.0, ask=101.0)]
        engine.run(events, _SimpleBuyTrader())

        pnl = engine.get_pnl_history()[-1]
        # Cash PnL = -101 (bought 1 at ask 101)
        assert pnl.cash == pytest.approx(-101.0)
        # Total PnL = -101 + 1 * 100 (mid) = -1
        assert pnl.total_pnl == pytest.approx(-1.0)


# ======================================================================
# Fill recording
# ======================================================================

class TestFillRecording:
    def test_fills_recorded(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
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
# Single strategy call per timestamp
# ======================================================================

class TestSingleCallPerTimestamp:
    def test_multi_product_same_timestamp(self):
        """Two products at same timestamp should result in one strategy call."""
        config = BacktestConfig(
            strategy_id="capture",
            products=["X", "Y"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20, "Y": 20},
        )
        engine = BacktestEngine(config)
        trader = _CaptureDepthTrader()
        events = [
            _make_book_event(100, product="X", bid=99.0, ask=101.0),
            _make_book_event(100, product="Y", bid=49.0, ask=51.0),
        ]
        engine.run(events, trader)

        # Should be called once (both products at timestamp 100)
        assert len(trader.snapshots) == 1
        assert "X" in trader.snapshots[0]
        assert "Y" in trader.snapshots[0]
        assert trader.snapshots[0]["X"] == (1, 1)
        assert trader.snapshots[0]["Y"] == (1, 1)


class TestBookIsolation:
    def test_missing_product_book_is_empty(self):
        config = BacktestConfig(
            strategy_id="capture_depth",
            products=["X", "Y"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20, "Y": 20},
        )
        engine = BacktestEngine(config)
        trader = _CaptureDepthTrader()
        events = [
            _make_book_event(100, product="X", bid=99.0, ask=101.0),
        ]
        engine.run(events, trader)

        assert trader.snapshots
        first = trader.snapshots[0]
        assert first["X"] == (1, 1)
        assert first["Y"] == (0, 0)


# ======================================================================
# Debug frame generation
# ======================================================================

class TestDebugFrameGeneration:
    def test_debug_frames_generated(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
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
# Position tracking
# ======================================================================

class TestPositionTracking:
    def test_position_accumulates(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
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
        final_inventory = pnl_history[-1].inventory
        assert "X" in final_inventory
        assert final_inventory["X"] == 3

    def test_position_in_debug_frames(self):
        config = BacktestConfig(
            strategy_id="buy",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [
            _make_book_event(100),
            _make_book_event(200),
        ]
        engine.run(events, _SimpleBuyTrader())
        frames = engine.get_debug_frames()

        assert frames[0].position.get("X") == 1
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
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [_make_book_event(100)]

        run = engine.run(events, _CrashingTrader())
        assert run.status in ("completed", "failed")


# ======================================================================
# Fix #3: Per-tick market trades (not rolling buffer)
# ======================================================================

class _CaptureMarketTradesTrader:
    """Captures state.market_trades on each call for assertion."""
    def __init__(self):
        self.seen_market_trades: list[dict[str, int]] = []

    def run(self, state):
        snap = {}
        for product, trades in state.market_trades.items():
            snap[product] = len(trades)
        self.seen_market_trades.append(snap)
        return {}, 0, ""


class TestPerTickMarketTrades:
    def test_first_tick_sees_no_market_trades(self):
        """On the very first timestamp, state.market_trades should be empty."""
        config = BacktestConfig(
            strategy_id="capture",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        trader = _CaptureMarketTradesTrader()

        events = [
            _make_trade_event(100, product="X", price=100.0, quantity=5),
            _make_book_event(100),
        ]
        engine.run(events, trader)

        # Strategy at t=100 sees previous tick's leftovers (none on first tick)
        assert trader.seen_market_trades[0].get("X", 0) == 0

    def test_leftovers_visible_on_next_tick(self):
        """Unconsumed market trades from tick N appear as market_trades at tick N+1."""
        config = BacktestConfig(
            strategy_id="capture",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        trader = _CaptureMarketTradesTrader()

        events = [
            # Tick 100: a trade occurs, but strategy places no orders so trade is unconsumed
            _make_trade_event(100, product="X", price=100.0, quantity=5),
            _make_book_event(100),
            # Tick 200: no new trades
            _make_book_event(200),
        ]
        engine.run(events, trader)

        # Tick 100: no leftovers from previous tick (first tick)
        assert trader.seen_market_trades[0].get("X", 0) == 0
        # Tick 200: sees leftover from tick 100 (5 units unconsumed)
        assert trader.seen_market_trades[1].get("X", 0) == 1  # 1 trade with quantity 5

    def test_consumed_trades_not_visible_next_tick(self):
        """If a market trade is fully consumed by matching, it shouldn't appear next tick."""
        config = BacktestConfig(
            strategy_id="capture_after_buy",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )

        class _BuyThenCapture:
            """Buy on tick 1, capture market trades on tick 2."""
            def __init__(self):
                self._tick = 0
                self.seen_market_trades: list[dict[str, int]] = []

            def run(self, state):
                from app.engines.sandbox.adapter import Order
                self._tick += 1
                snap = {p: len(t) for p, t in state.market_trades.items()}
                self.seen_market_trades.append(snap)

                orders = {}
                if self._tick == 1:
                    # Buy 5 at 100 — should consume the market trade (qty 5 at 100)
                    for product in state.order_depths:
                        orders[product] = [Order(product, 100, 5)]
                return orders, 0, ""

        engine = BacktestEngine(config)
        trader = _BuyThenCapture()

        events = [
            _make_trade_event(100, product="X", price=100.0, quantity=5),
            _make_book_event(100, bid=99, ask=101),
            _make_book_event(200, bid=99, ask=101),
        ]
        engine.run(events, trader)

        # Tick 200: trade at tick 100 was consumed by buy order, so no leftovers
        assert trader.seen_market_trades[1].get("X", 0) == 0


# ======================================================================
# Fix #4: Conversions affect position and cash
# ======================================================================

class TestConversions:
    def test_positive_conversion_increases_position(self):
        """conversions > 0 should increase position and cost askPrice + fees."""
        from app.engines.sandbox.adapter import ConversionObservation, Observation

        config = BacktestConfig(
            strategy_id="converter",
            products=["ORCHIDS"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"ORCHIDS": 100},
        )

        class _ConvertTrader:
            def __init__(self):
                self._called = False

            def run(self, state):
                if not self._called:
                    self._called = True
                    # Set up conversion observations on the state
                    state.observations.conversionObservations["ORCHIDS"] = (
                        ConversionObservation(
                            bidPrice=1000.0,
                            askPrice=1005.0,
                            transportFees=2.0,
                            exportTariff=1.0,
                            importTariff=1.5,
                        )
                    )
                    return {}, 3, ""  # 3 conversions (import)
                return {}, 0, ""

        engine = BacktestEngine(config)
        trader = _ConvertTrader()
        events = [_make_book_event(100, product="ORCHIDS", bid=999, ask=1001)]
        engine.run(events, trader)

        # Position should be +3
        pnl = engine.get_pnl_history()[-1]
        assert pnl.inventory.get("ORCHIDS", 0) == 3

        # Cash cost = (1005 + 2 + 1.5) * 3 = 1008.5 * 3 = 3025.5
        # Total PnL = -3025.5 + 3 * mid_price(1000) = -3025.5 + 3000 = -25.5
        assert pnl.cash == pytest.approx(-3025.5)

    def test_negative_conversion_decreases_position(self):
        """conversions < 0 should decrease position and earn bidPrice - fees."""
        from app.engines.sandbox.adapter import ConversionObservation

        config = BacktestConfig(
            strategy_id="exporter",
            products=["ORCHIDS"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"ORCHIDS": 100},
        )

        class _ExportTrader:
            def __init__(self):
                self._called = False

            def run(self, state):
                if not self._called:
                    self._called = True
                    state.observations.conversionObservations["ORCHIDS"] = (
                        ConversionObservation(
                            bidPrice=1000.0,
                            askPrice=1005.0,
                            transportFees=2.0,
                            exportTariff=1.0,
                            importTariff=1.5,
                        )
                    )
                    return {}, -2, ""  # -2 conversions (export)
                return {}, 0, ""

        engine = BacktestEngine(config)
        trader = _ExportTrader()
        events = [_make_book_event(100, product="ORCHIDS", bid=999, ask=1001)]
        engine.run(events, trader)

        pnl = engine.get_pnl_history()[-1]
        # Position should be -2
        assert pnl.inventory.get("ORCHIDS", 0) == -2

        # Revenue per unit = 1000 - 2 - 1 = 997
        # Cash = 997 * 2 = 1994
        assert pnl.cash == pytest.approx(1994.0)

    def test_zero_conversions_noop(self):
        """conversions == 0 should not change anything."""
        config = BacktestConfig(
            strategy_id="noop",
            products=["X"],
            trade_matching=TradeMatchingMode.ALL,
            position_limits={"X": 20},
        )
        engine = BacktestEngine(config)
        events = [_make_book_event(100)]
        engine.run(events, _NoOpTrader())

        pnl = engine.get_pnl_history()[-1]
        assert pnl.cash == 0.0
        assert pnl.inventory.get("X", 0) == 0
