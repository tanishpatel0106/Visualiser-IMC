"""Technical indicators for the IMC Prosperity trading terminal."""

from __future__ import annotations

from typing import Optional

import numpy as np


class TechnicalIndicators:
    """Collection of static technical-indicator methods.

    Every method returns a list the same length as the input.  Positions
    where the indicator cannot yet be computed (insufficient lookback) are
    filled with ``None``.
    """

    # ------------------------------------------------------------------ #
    #  Moving averages                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def sma(values: list[float], period: int) -> list[Optional[float]]:
        """Simple Moving Average."""
        n = len(values)
        if period <= 0 or n == 0:
            return [None] * n
        result: list[Optional[float]] = [None] * n
        arr = np.array(values, dtype=np.float64)
        cumsum = np.cumsum(arr)
        for i in range(period - 1, n):
            if i == period - 1:
                result[i] = float(cumsum[i] / period)
            else:
                result[i] = float((cumsum[i] - cumsum[i - period]) / period)
        return result

    @staticmethod
    def ema(values: list[float], period: int) -> list[Optional[float]]:
        """Exponential Moving Average."""
        n = len(values)
        if period <= 0 or n == 0:
            return [None] * n
        result: list[Optional[float]] = [None] * n
        if n < period:
            return result
        # Seed with SMA of first *period* values
        alpha = 2.0 / (period + 1)
        seed = float(np.mean(values[:period]))
        result[period - 1] = seed
        prev = seed
        for i in range(period, n):
            prev = alpha * values[i] + (1 - alpha) * prev
            result[i] = prev
        return result

    @staticmethod
    def wma(values: list[float], period: int) -> list[Optional[float]]:
        """Weighted Moving Average (linearly weighted)."""
        n = len(values)
        if period <= 0 or n == 0:
            return [None] * n
        result: list[Optional[float]] = [None] * n
        weights = np.arange(1, period + 1, dtype=np.float64)
        weight_sum = weights.sum()
        for i in range(period - 1, n):
            window = np.array(values[i - period + 1 : i + 1], dtype=np.float64)
            result[i] = float(np.dot(window, weights) / weight_sum)
        return result

    @staticmethod
    def hma(values: list[float], period: int) -> list[Optional[float]]:
        """Hull Moving Average.

        HMA = WMA( 2*WMA(n/2) - WMA(n) , sqrt(n) )
        """
        n = len(values)
        if period <= 1 or n == 0:
            return [None] * n

        half = max(1, period // 2)
        sqrt_p = max(1, int(np.sqrt(period)))

        wma_half = TechnicalIndicators.wma(values, half)
        wma_full = TechnicalIndicators.wma(values, period)

        # Compute 2 * WMA(half) - WMA(full)
        diff: list[float] = []
        diff_start: Optional[int] = None
        for i in range(n):
            if wma_half[i] is not None and wma_full[i] is not None:
                diff.append(2.0 * wma_half[i] - wma_full[i])
                if diff_start is None:
                    diff_start = i
            elif diff_start is not None:
                # Should not happen with well-formed data but be safe
                diff.append(0.0)

        if not diff:
            return [None] * n

        hull_raw = TechnicalIndicators.wma(diff, sqrt_p)

        result: list[Optional[float]] = [None] * n
        for j, val in enumerate(hull_raw):
            if val is not None:
                result[diff_start + j] = val  # type: ignore[operator]
        return result

    # ------------------------------------------------------------------ #
    #  VWAP                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def vwap(prices: list[float], volumes: list[float]) -> list[float]:
        """Cumulative Volume-Weighted Average Price."""
        n = len(prices)
        if n == 0:
            return []
        p = np.array(prices, dtype=np.float64)
        v = np.array(volumes, dtype=np.float64)
        cum_pv = np.cumsum(p * v)
        cum_v = np.cumsum(v)
        result: list[float] = []
        for i in range(n):
            if cum_v[i] > 0:
                result.append(float(cum_pv[i] / cum_v[i]))
            else:
                result.append(0.0)
        return result

    # ------------------------------------------------------------------ #
    #  Bollinger Bands                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def bollinger_bands(
        values: list[float],
        period: int,
        std_mult: float = 2.0,
    ) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
        """Bollinger Bands: (upper, mid, lower)."""
        n = len(values)
        upper: list[Optional[float]] = [None] * n
        mid: list[Optional[float]] = [None] * n
        lower: list[Optional[float]] = [None] * n

        if period <= 0 or n == 0:
            return upper, mid, lower

        arr = np.array(values, dtype=np.float64)
        for i in range(period - 1, n):
            window = arr[i - period + 1 : i + 1]
            m = float(np.mean(window))
            s = float(np.std(window, ddof=1)) if period > 1 else 0.0
            mid[i] = m
            upper[i] = m + std_mult * s
            lower[i] = m - std_mult * s

        return upper, mid, lower

    # ------------------------------------------------------------------ #
    #  RSI                                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def rsi(values: list[float], period: int = 14) -> list[Optional[float]]:
        """Relative Strength Index using Wilder's smoothing."""
        n = len(values)
        if period <= 0 or n < period + 1:
            return [None] * n

        result: list[Optional[float]] = [None] * n
        arr = np.array(values, dtype=np.float64)
        deltas = np.diff(arr)

        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))

        if avg_loss == 0:
            result[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[period] = 100.0 - 100.0 / (1.0 + rs)

        for i in range(period + 1, n):
            idx = i - 1  # index into deltas
            avg_gain = (avg_gain * (period - 1) + gains[idx]) / period
            avg_loss = (avg_loss * (period - 1) + losses[idx]) / period
            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - 100.0 / (1.0 + rs)

        return result

    # ------------------------------------------------------------------ #
    #  MACD                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def macd(
        values: list[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
        """MACD: (macd_line, signal_line, histogram)."""
        n = len(values)
        none_list: list[Optional[float]] = [None] * n
        if n == 0:
            return none_list[:], none_list[:], none_list[:]

        ema_fast = TechnicalIndicators.ema(values, fast)
        ema_slow = TechnicalIndicators.ema(values, slow)

        macd_line: list[Optional[float]] = [None] * n
        for i in range(n):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                macd_line[i] = ema_fast[i] - ema_slow[i]

        # Signal line = EMA of MACD values (skip Nones)
        macd_vals: list[float] = []
        macd_start: Optional[int] = None
        for i in range(n):
            if macd_line[i] is not None:
                macd_vals.append(macd_line[i])
                if macd_start is None:
                    macd_start = i

        signal_line: list[Optional[float]] = [None] * n
        histogram: list[Optional[float]] = [None] * n

        if macd_vals and macd_start is not None:
            sig_raw = TechnicalIndicators.ema(macd_vals, signal)
            for j, val in enumerate(sig_raw):
                idx = macd_start + j
                if idx < n and val is not None:
                    signal_line[idx] = val
                    if macd_line[idx] is not None:
                        histogram[idx] = macd_line[idx] - val

        return macd_line, signal_line, histogram

    # ------------------------------------------------------------------ #
    #  Rate of Change                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def roc(values: list[float], period: int) -> list[Optional[float]]:
        """Rate of Change (percentage)."""
        n = len(values)
        if period <= 0 or n == 0:
            return [None] * n
        result: list[Optional[float]] = [None] * n
        for i in range(period, n):
            prev = values[i - period]
            if prev != 0:
                result[i] = (values[i] - prev) / prev * 100.0
            else:
                result[i] = None
        return result

    # ------------------------------------------------------------------ #
    #  Rolling z-score                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def rolling_zscore(values: list[float], window: int) -> list[Optional[float]]:
        """Rolling z-score: (value - mean) / std over *window*."""
        n = len(values)
        if window <= 1 or n == 0:
            return [None] * n
        result: list[Optional[float]] = [None] * n
        arr = np.array(values, dtype=np.float64)
        for i in range(window - 1, n):
            w = arr[i - window + 1 : i + 1]
            m = float(np.mean(w))
            s = float(np.std(w, ddof=1))
            if s > 0:
                result[i] = (values[i] - m) / s
            else:
                result[i] = 0.0
        return result

    # ------------------------------------------------------------------ #
    #  Rolling volatility                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def rolling_volatility(values: list[float], window: int) -> list[Optional[float]]:
        """Rolling standard deviation of returns (first differences)."""
        n = len(values)
        if window <= 1 or n < 2:
            return [None] * n
        result: list[Optional[float]] = [None] * n
        arr = np.array(values, dtype=np.float64)
        returns = np.diff(arr)
        # returns has length n-1; result indices shifted by 1
        for i in range(window, n):
            w = returns[i - window : i]
            result[i] = float(np.std(w, ddof=1))
        return result

    # ------------------------------------------------------------------ #
    #  ATR proxy                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def atr_proxy(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> list[Optional[float]]:
        """Average True Range (Wilder smoothing).

        Works with any high/low/close series.  In a tick-based environment
        where true highs/lows are unavailable, callers can pass the same
        series for all three to approximate with absolute price changes.
        """
        n = len(highs)
        if period <= 0 or n < 2:
            return [None] * n
        if len(lows) != n or len(closes) != n:
            return [None] * n

        result: list[Optional[float]] = [None] * n
        h = np.array(highs, dtype=np.float64)
        l = np.array(lows, dtype=np.float64)
        c = np.array(closes, dtype=np.float64)

        # True range
        tr = np.empty(n, dtype=np.float64)
        tr[0] = h[0] - l[0]
        for i in range(1, n):
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

        if n < period + 1:
            return result

        # Seed with simple average of first *period* true ranges
        atr_val = float(np.mean(tr[1 : period + 1]))
        result[period] = atr_val

        for i in range(period + 1, n):
            atr_val = (atr_val * (period - 1) + tr[i]) / period
            result[i] = atr_val

        return result
