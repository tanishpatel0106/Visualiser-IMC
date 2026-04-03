"""Tests for the StrategySandbox and ProsperityAdapter."""

import pytest

from app.engines.sandbox.runner import StrategySandbox
from app.engines.sandbox.adapter import (
    ProsperityAdapter,
    TradingState,
    OrderDepth,
    Listing,
    Trade,
    Order,
)
from app.models.market import (
    BookLevel,
    OrderSide,
    TradePrint,
    VisibleOrderBook,
)


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def sandbox():
    return StrategySandbox(timeout=5.0)


@pytest.fixture
def adapter():
    return ProsperityAdapter()


# ======================================================================
# Source code samples
# ======================================================================

VALID_STRATEGY = """
class Trader:
    def run(self, state):
        return {}, 0, ""
"""

VALID_STRATEGY_WITH_MATH = """
class Trader:
    def run(self, state):
        # Use math that's pre-injected in the sandbox globals
        x = math.sqrt(4)
        return {}, 0, str(x)
"""

MISSING_TRADER_CLASS = """
class NotTrader:
    def act(self, state):
        return {}, 0, ""
"""

MISSING_RUN_METHOD = """
class Trader:
    def act(self, state):
        return {}, 0, ""
"""

FORBIDDEN_OS_IMPORT = """
import os

class Trader:
    def run(self, state):
        return {}, 0, ""
"""

FORBIDDEN_SUBPROCESS_IMPORT = """
import subprocess

class Trader:
    def run(self, state):
        return {}, 0, ""
"""

FORBIDDEN_FROM_IMPORT = """
from os.path import join

class Trader:
    def run(self, state):
        return {}, 0, ""
"""

SYNTAX_ERROR_CODE = """
class Trader:
    def run(self, state)
        return {}, 0, ""
"""

STRATEGY_RAISES_EXCEPTION = """
class Trader:
    def run(self, state):
        raise ValueError("Intentional error")
"""

STRATEGY_RETURNS_ORDERS = """
class Trader:
    def run(self, state):
        orders = {}
        for product in state.order_depths:
            depth = state.order_depths[product]
            if depth.sell_orders:
                best_ask = min(depth.sell_orders.keys())
                # Prosperity-style: import not needed since Order may not be available
                # We return a simple dict-like approach
                pass
        return {}, 0, "some_data"
"""


# ======================================================================
# validate_strategy
# ======================================================================

class TestValidateStrategy:
    def test_valid_strategy(self, sandbox):
        valid, error = sandbox.validate_strategy(VALID_STRATEGY)
        assert valid is True
        assert error == ""

    def test_valid_strategy_with_safe_import(self, sandbox):
        valid, error = sandbox.validate_strategy(VALID_STRATEGY_WITH_MATH)
        assert valid is True
        assert error == ""

    def test_rejects_missing_trader_class(self, sandbox):
        valid, error = sandbox.validate_strategy(MISSING_TRADER_CLASS)
        assert valid is False
        assert "run" in error

    def test_rejects_missing_run_method(self, sandbox):
        valid, error = sandbox.validate_strategy(MISSING_RUN_METHOD)
        assert valid is False
        assert "run" in error

    def test_rejects_os_import(self, sandbox):
        valid, error = sandbox.validate_strategy(FORBIDDEN_OS_IMPORT)
        assert valid is False
        assert "os" in error

    def test_rejects_subprocess_import(self, sandbox):
        valid, error = sandbox.validate_strategy(FORBIDDEN_SUBPROCESS_IMPORT)
        assert valid is False
        assert "subprocess" in error

    def test_rejects_from_os_import(self, sandbox):
        valid, error = sandbox.validate_strategy(FORBIDDEN_FROM_IMPORT)
        assert valid is False
        assert "os" in error

    def test_rejects_syntax_error(self, sandbox):
        valid, error = sandbox.validate_strategy(SYNTAX_ERROR_CODE)
        assert valid is False
        assert "Syntax error" in error


# ======================================================================
# load_strategy
# ======================================================================

class TestLoadStrategy:
    def test_load_valid_strategy(self, sandbox):
        strategy = sandbox.load_strategy(VALID_STRATEGY)
        assert strategy is not None
        assert hasattr(strategy, "run")

    def test_load_with_math(self, sandbox):
        strategy = sandbox.load_strategy(VALID_STRATEGY_WITH_MATH)
        assert strategy is not None

    def test_load_invalid_raises_value_error(self, sandbox):
        with pytest.raises(ValueError, match="Invalid strategy"):
            sandbox.load_strategy(MISSING_TRADER_CLASS)

    def test_load_forbidden_import_raises(self, sandbox):
        with pytest.raises(ValueError, match="Invalid strategy"):
            sandbox.load_strategy(FORBIDDEN_OS_IMPORT)


# ======================================================================
# execute_strategy
# ======================================================================

class TestExecuteStrategy:
    def test_execute_valid_strategy(self, sandbox):
        strategy = sandbox.load_strategy(VALID_STRATEGY)
        state = TradingState()
        state.timestamp = 100
        state.order_depths = {"X": OrderDepth()}

        orders, conversions, trader_data = sandbox.execute_strategy(strategy, state)
        assert orders == {}
        assert conversions == 0
        assert trader_data == ""

    def test_execute_strategy_with_return_data(self, sandbox):
        strategy = sandbox.load_strategy(VALID_STRATEGY_WITH_MATH)
        state = TradingState()

        orders, conversions, trader_data = sandbox.execute_strategy(strategy, state)
        assert trader_data == "2.0"

    def test_execute_strategy_catches_exceptions(self, sandbox):
        strategy = sandbox.load_strategy(STRATEGY_RAISES_EXCEPTION)
        state = TradingState()

        orders, conversions, trader_data = sandbox.execute_strategy(strategy, state)
        assert orders == {}
        assert conversions == 0
        assert "ERROR:" in trader_data


# ======================================================================
# ProsperityAdapter.build_state
# ======================================================================

class TestProsperityAdapterBuildState:
    def test_build_state_basic(self, adapter):
        book = VisibleOrderBook(
            product="EMERALDS",
            timestamp=100,
            bids=[BookLevel(price=99.0, volume=10, side=OrderSide.BUY)],
            asks=[BookLevel(price=101.0, volume=15, side=OrderSide.SELL)],
        )
        state = adapter.build_state(
            timestamp=100,
            products=["EMERALDS"],
            books={"EMERALDS": book},
            positions={"EMERALDS": 5},
            own_trades={"EMERALDS": []},
            market_trades={"EMERALDS": []},
            trader_data="hello",
        )

        assert isinstance(state, TradingState)
        assert state.timestamp == 100
        assert state.traderData == "hello"
        assert "EMERALDS" in state.listings
        assert "EMERALDS" in state.order_depths
        assert state.position["EMERALDS"] == 5

    def test_build_state_order_depth(self, adapter):
        book = VisibleOrderBook(
            product="X",
            timestamp=100,
            bids=[
                BookLevel(price=99.0, volume=10, side=OrderSide.BUY),
                BookLevel(price=98.0, volume=20, side=OrderSide.BUY),
            ],
            asks=[
                BookLevel(price=101.0, volume=15, side=OrderSide.SELL),
                BookLevel(price=102.0, volume=25, side=OrderSide.SELL),
            ],
        )
        state = adapter.build_state(
            timestamp=100,
            products=["X"],
            books={"X": book},
            positions={"X": 0},
            own_trades={"X": []},
            market_trades={"X": []},
        )

        depth = state.order_depths["X"]
        # Bids: positive volume
        assert depth.buy_orders[99] == 10
        assert depth.buy_orders[98] == 20
        # Asks: negative volume (Prosperity convention)
        assert depth.sell_orders[101] == -15
        assert depth.sell_orders[102] == -25

    def test_build_state_with_trades(self, adapter):
        book = VisibleOrderBook(
            product="X",
            timestamp=100,
            bids=[BookLevel(price=99.0, volume=10, side=OrderSide.BUY)],
            asks=[BookLevel(price=101.0, volume=15, side=OrderSide.SELL)],
        )
        market_trade = TradePrint(
            timestamp=90, buyer="A", seller="B", symbol="X",
            price=100.0, quantity=3,
        )
        state = adapter.build_state(
            timestamp=100,
            products=["X"],
            books={"X": book},
            positions={"X": 0},
            own_trades={"X": []},
            market_trades={"X": [market_trade]},
        )

        assert len(state.market_trades["X"]) == 1
        t = state.market_trades["X"][0]
        assert t.price == 100.0
        assert t.quantity == 3


# ======================================================================
# ProsperityAdapter.parse_orders
# ======================================================================

class TestProsperityAdapterParseOrders:
    def test_parse_buy_orders(self, adapter):
        order = Order("X", 100, 5)  # positive qty = BUY
        raw = {"X": [order]}
        strategy_orders = adapter.parse_orders(raw, timestamp=1000)

        assert len(strategy_orders) == 1
        assert strategy_orders[0].side == OrderSide.BUY
        assert strategy_orders[0].price == 100.0
        assert strategy_orders[0].quantity == 5
        assert strategy_orders[0].timestamp == 1000

    def test_parse_sell_orders(self, adapter):
        order = Order("X", 100, -3)  # negative qty = SELL
        raw = {"X": [order]}
        strategy_orders = adapter.parse_orders(raw, timestamp=1000)

        assert len(strategy_orders) == 1
        assert strategy_orders[0].side == OrderSide.SELL
        assert strategy_orders[0].quantity == 3  # absolute value

    def test_parse_zero_qty_skipped(self, adapter):
        order = Order("X", 100, 0)
        raw = {"X": [order]}
        strategy_orders = adapter.parse_orders(raw, timestamp=1000)
        assert strategy_orders == []

    def test_parse_multiple_products(self, adapter):
        raw = {
            "A": [Order("A", 50, 2)],
            "B": [Order("B", 200, -1)],
        }
        strategy_orders = adapter.parse_orders(raw, timestamp=500)
        assert len(strategy_orders) == 2
        products = {o.product for o in strategy_orders}
        assert products == {"A", "B"}
