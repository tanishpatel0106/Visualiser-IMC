"""Tests for analytics: PerformanceAnalyzer and TechnicalIndicators."""

import math

import numpy as np
import pytest

from backend.app.engines.analytics.performance import PerformanceAnalyzer
from backend.app.engines.analytics.indicators import TechnicalIndicators
from backend.app.models.market import OrderSide
from backend.app.models.trading import FillEvent, PnLState, PositionState


# ======================================================================
# PerformanceAnalyzer
# ======================================================================

class TestPerformanceAnalyzer:
    def test_empty_inputs(self):
        metrics = PerformanceAnalyzer.compute_metrics(
            fills=[], pnl_history=[], positions={},
        )
        assert metrics.total_pnl == 0.0
        assert metrics.num_trades == 0
        assert metrics.sharpe_ratio == 0.0

    def test_with_known_fills_and_positions(self):
        fills = [
            FillEvent(order_id="o1", product="X", side=OrderSide.BUY,
                      price=100.0, quantity=10, timestamp=100),
            FillEvent(order_id="o2", product="X", side=OrderSide.SELL,
                      price=105.0, quantity=10, timestamp=200),
        ]
        pnl_history = [
            PnLState(timestamp=100, total_pnl=0.0, inventory={"X": 10}),
            PnLState(timestamp=200, total_pnl=50.0, inventory={"X": 0}),
        ]
        positions = {
            "X": PositionState(product="X", realized_pnl=50.0, unrealized_pnl=0.0),
        }
        metrics = PerformanceAnalyzer.compute_metrics(fills, pnl_history, positions)

        assert metrics.total_pnl == pytest.approx(50.0)
        assert metrics.realized_pnl == pytest.approx(50.0)
        assert metrics.unrealized_pnl == pytest.approx(0.0)
        assert metrics.num_trades == 2

    def test_pnl_by_product(self):
        fills = [
            FillEvent(order_id="o1", product="A", side=OrderSide.BUY,
                      price=10.0, quantity=1, timestamp=1),
        ]
        positions = {
            "A": PositionState(product="A", realized_pnl=20.0, unrealized_pnl=5.0),
            "B": PositionState(product="B", realized_pnl=-10.0, unrealized_pnl=2.0),
        }
        pnl_history = [
            PnLState(timestamp=1, total_pnl=0.0, inventory={"A": 1}),
        ]
        metrics = PerformanceAnalyzer.compute_metrics(fills, pnl_history, positions)

        assert metrics.pnl_by_product["A"] == pytest.approx(25.0)
        assert metrics.pnl_by_product["B"] == pytest.approx(-8.0)

    def test_win_rate_and_profit_factor(self):
        fills = [
            FillEvent(order_id="o1", product="X", side=OrderSide.BUY,
                      price=100.0, quantity=1, timestamp=100),
            FillEvent(order_id="o2", product="X", side=OrderSide.SELL,
                      price=110.0, quantity=1, timestamp=200),
            FillEvent(order_id="o3", product="X", side=OrderSide.BUY,
                      price=110.0, quantity=1, timestamp=300),
            FillEvent(order_id="o4", product="X", side=OrderSide.SELL,
                      price=105.0, quantity=1, timestamp=400),
        ]
        pnl_history = [
            PnLState(timestamp=100, total_pnl=0.0, inventory={"X": 1}),
            PnLState(timestamp=200, total_pnl=10.0, inventory={"X": 0}),
            PnLState(timestamp=300, total_pnl=10.0, inventory={"X": 1}),
            PnLState(timestamp=400, total_pnl=5.0, inventory={"X": 0}),
        ]
        positions = {
            "X": PositionState(product="X", realized_pnl=5.0, unrealized_pnl=0.0),
        }
        metrics = PerformanceAnalyzer.compute_metrics(fills, pnl_history, positions)

        # Two round trips: +10 (win), -5 (loss)
        assert metrics.win_rate == pytest.approx(0.5)
        assert metrics.profit_factor == pytest.approx(10.0 / 5.0)

    def test_max_drawdown(self):
        pnl_history = [
            PnLState(timestamp=i * 100, total_pnl=v, inventory={})
            for i, v in enumerate([0, 10, 20, 15, 5, 25])
        ]
        positions = {}
        fills = []
        metrics = PerformanceAnalyzer.compute_metrics(fills, pnl_history, positions)

        # Peak was 20, trough was 5, drawdown = 15
        assert metrics.max_drawdown == pytest.approx(15.0)

    def test_sharpe_nonzero(self):
        pnl_values = [0, 1, 3, 6, 10, 15]
        pnl_history = [
            PnLState(timestamp=i * 100, total_pnl=v, inventory={})
            for i, v in enumerate(pnl_values)
        ]
        metrics = PerformanceAnalyzer.compute_metrics([], pnl_history, {})

        # Increments: [1, 2, 3, 4, 5], mean=3, std>0 => sharpe > 0
        assert metrics.sharpe_ratio > 0

    def test_inventory_stats(self):
        pnl_history = [
            PnLState(timestamp=100, total_pnl=0, inventory={"X": 5}),
            PnLState(timestamp=200, total_pnl=0, inventory={"X": 10}),
            PnLState(timestamp=300, total_pnl=0, inventory={"X": 3}),
        ]
        metrics = PerformanceAnalyzer.compute_metrics([], pnl_history, {})
        assert metrics.avg_inventory == pytest.approx((5 + 10 + 3) / 3)
        assert metrics.max_inventory == pytest.approx(10.0)


# ======================================================================
# TechnicalIndicators.sma
# ======================================================================

class TestSMA:
    def test_basic_sma(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = TechnicalIndicators.sma(values, period=3)

        assert result[0] is None
        assert result[1] is None
        assert result[2] == pytest.approx(2.0)  # (1+2+3)/3
        assert result[3] == pytest.approx(3.0)  # (2+3+4)/3
        assert result[4] == pytest.approx(4.0)  # (3+4+5)/3

    def test_sma_period_1(self):
        values = [10.0, 20.0, 30.0]
        result = TechnicalIndicators.sma(values, period=1)
        assert result == [pytest.approx(10.0), pytest.approx(20.0), pytest.approx(30.0)]

    def test_sma_period_exceeds_length(self):
        values = [1.0, 2.0]
        result = TechnicalIndicators.sma(values, period=5)
        assert result == [None, None]

    def test_sma_empty_input(self):
        assert TechnicalIndicators.sma([], period=3) == []

    def test_sma_zero_period(self):
        values = [1.0, 2.0]
        result = TechnicalIndicators.sma(values, period=0)
        assert result == [None, None]


# ======================================================================
# TechnicalIndicators.ema
# ======================================================================

class TestEMA:
    def test_basic_ema(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = TechnicalIndicators.ema(values, period=3)

        assert result[0] is None
        assert result[1] is None
        # Seed = SMA of first 3 = 2.0
        assert result[2] == pytest.approx(2.0)
        # alpha = 2/(3+1) = 0.5
        # ema[3] = 0.5 * 4 + 0.5 * 2.0 = 3.0
        assert result[3] == pytest.approx(3.0)
        # ema[4] = 0.5 * 5 + 0.5 * 3.0 = 4.0
        assert result[4] == pytest.approx(4.0)

    def test_ema_period_exceeds_length(self):
        values = [1.0, 2.0]
        result = TechnicalIndicators.ema(values, period=5)
        assert result == [None, None]


# ======================================================================
# TechnicalIndicators.rsi
# ======================================================================

class TestRSI:
    def test_rsi_basic(self):
        # Monotonically increasing: all gains, no losses => RSI = 100
        values = list(range(20))
        result = TechnicalIndicators.rsi(values, period=14)

        # First 14+1=15 values (indices 0-14) should be None
        for i in range(14):
            assert result[i] is None
        # From index 14 onward, RSI should be 100 (all gains)
        assert result[14] == pytest.approx(100.0)

    def test_rsi_monotonically_decreasing(self):
        # All losses => RSI = 0
        values = list(range(20, 0, -1))
        result = TechnicalIndicators.rsi(values, period=14)

        assert result[14] == pytest.approx(0.0)

    def test_rsi_too_few_values(self):
        values = [1.0, 2.0, 3.0]
        result = TechnicalIndicators.rsi(values, period=14)
        assert all(v is None for v in result)

    def test_rsi_range(self):
        # RSI should be between 0 and 100
        np.random.seed(42)
        values = list(np.cumsum(np.random.randn(100)) + 100)
        result = TechnicalIndicators.rsi(values, period=14)
        for v in result:
            if v is not None:
                assert 0.0 <= v <= 100.0


# ======================================================================
# TechnicalIndicators.bollinger_bands
# ======================================================================

class TestBollingerBands:
    def test_basic_bollinger(self):
        values = [10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 12.0, 13.0, 12.0, 11.0]
        upper, mid, lower = TechnicalIndicators.bollinger_bands(values, period=5)

        # First 4 values should be None
        for i in range(4):
            assert upper[i] is None
            assert mid[i] is None
            assert lower[i] is None

        # From index 4 onward, bands should be computed
        assert mid[4] is not None
        assert upper[4] is not None
        assert lower[4] is not None

        # Upper > mid > lower
        for i in range(4, len(values)):
            if upper[i] is not None:
                assert upper[i] >= mid[i]
                assert mid[i] >= lower[i]

    def test_constant_series(self):
        values = [5.0] * 10
        upper, mid, lower = TechnicalIndicators.bollinger_bands(values, period=3)

        # Constant series: std = 0, so upper == mid == lower == 5
        for i in range(2, 10):
            assert mid[i] == pytest.approx(5.0)
            assert upper[i] == pytest.approx(5.0)
            assert lower[i] == pytest.approx(5.0)


# ======================================================================
# TechnicalIndicators.macd
# ======================================================================

class TestMACD:
    def test_basic_macd(self):
        # Need enough data for slow EMA (26)
        np.random.seed(42)
        values = list(np.cumsum(np.random.randn(50)) + 100)

        macd_line, signal_line, histogram = TechnicalIndicators.macd(values)

        assert len(macd_line) == 50
        assert len(signal_line) == 50
        assert len(histogram) == 50

        # MACD line should have values starting from index 25 (slow-1)
        assert macd_line[24] is None  # not yet computed
        assert macd_line[25] is not None  # slow EMA kicks in

    def test_macd_short_series(self):
        values = [1.0, 2.0, 3.0]
        macd_line, signal_line, histogram = TechnicalIndicators.macd(values)
        assert all(v is None for v in macd_line)

    def test_macd_histogram_is_diff(self):
        np.random.seed(42)
        values = list(np.cumsum(np.random.randn(60)) + 100)
        macd_line, signal_line, histogram = TechnicalIndicators.macd(values)

        for i in range(len(values)):
            if histogram[i] is not None and macd_line[i] is not None and signal_line[i] is not None:
                assert histogram[i] == pytest.approx(macd_line[i] - signal_line[i], abs=1e-10)

    def test_empty_input(self):
        macd_line, signal_line, histogram = TechnicalIndicators.macd([])
        assert macd_line == []
        assert signal_line == []
        assert histogram == []
