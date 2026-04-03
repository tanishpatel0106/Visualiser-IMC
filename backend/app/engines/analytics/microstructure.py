"""Microstructure analytics engine."""

from __future__ import annotations

import numpy as np

from app.models.analytics import MicrostructureMetrics
from app.models.market import OrderSide, TradePrint, VisibleOrderBook


class MicrostructureAnalyzer:
    """Computes microstructure statistics from order book snapshots and trade prints."""

    @staticmethod
    def compute_metrics(
        books: list[VisibleOrderBook],
        trades: list[TradePrint],
    ) -> MicrostructureMetrics:
        """
        Parameters
        ----------
        books : list[VisibleOrderBook]
            Chronologically ordered order book snapshots.
        trades : list[TradePrint]
            Chronologically ordered trade prints.

        Returns
        -------
        MicrostructureMetrics
        """
        metrics = MicrostructureMetrics()

        # ---- Order-book statistics ----------------------------------- #
        if books:
            spreads: list[float] = []
            imbalances: list[float] = []
            bid_depths: list[float] = []
            ask_depths: list[float] = []

            for book in books:
                if book.spread is not None:
                    spreads.append(book.spread)
                if book.top_level_imbalance is not None:
                    imbalances.append(book.top_level_imbalance)
                bid_depths.append(float(book.total_bid_depth))
                ask_depths.append(float(book.total_ask_depth))

            if spreads:
                arr = np.array(spreads, dtype=np.float64)
                metrics.avg_spread = float(np.mean(arr))
                metrics.spread_std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

            if imbalances:
                metrics.avg_imbalance = float(np.mean(imbalances))

            if bid_depths:
                metrics.avg_depth_bid = float(np.mean(bid_depths))
            if ask_depths:
                metrics.avg_depth_ask = float(np.mean(ask_depths))

        # ---- Trade statistics ---------------------------------------- #
        trade_count = len(trades)
        metrics.trade_count = trade_count

        if trades:
            sizes = np.array([t.quantity for t in trades], dtype=np.float64)
            metrics.avg_trade_size = float(np.mean(sizes))

            buy_vol = sum(
                t.quantity for t in trades if t.aggressor_side == OrderSide.BUY
            )
            sell_vol = sum(
                t.quantity for t in trades if t.aggressor_side == OrderSide.SELL
            )
            metrics.buy_volume = buy_vol
            metrics.sell_volume = sell_vol

            # VWAP
            prices = np.array([t.price for t in trades], dtype=np.float64)
            quantities = np.array([t.quantity for t in trades], dtype=np.float64)
            total_qty = float(np.sum(quantities))
            metrics.vwap = float(np.dot(prices, quantities) / total_qty) if total_qty > 0 else 0.0

            # Price volatility (std of trade prices)
            if len(prices) > 1:
                metrics.price_volatility = float(np.std(prices, ddof=1))

            # Trade imbalance = (buy_vol - sell_vol) / (buy_vol + sell_vol)
            total_vol = buy_vol + sell_vol
            trade_imbalance = (buy_vol - sell_vol) / total_vol if total_vol > 0 else 0.0

            # Inter-trade time statistics
            timestamps = np.array([t.timestamp for t in trades], dtype=np.float64)
            if len(timestamps) > 1:
                inter_times = np.diff(timestamps)
                inter_times = inter_times[inter_times >= 0]  # safety

                if len(inter_times) > 0:
                    mean_itt = float(np.mean(inter_times))
                    std_itt = float(np.std(inter_times, ddof=1)) if len(inter_times) > 1 else 0.0

                    # Arrival rate = trades per unit time
                    if mean_itt > 0:
                        metrics.arrival_rate = 1.0 / mean_itt

                    # Burstiness (Goh-Barabasi): B = (std - mean) / (std + mean)
                    denom = std_itt + mean_itt
                    burstiness = (std_itt - mean_itt) / denom if denom > 0 else 0.0
                else:
                    trade_imbalance = trade_imbalance  # keep as-is
                    burstiness = 0.0
            else:
                burstiness = 0.0

            # Kyle's lambda: simple regression of price change on signed volume
            if len(trades) > 1:
                price_changes = np.diff(prices)
                signed_volumes = []
                for t in trades[1:]:
                    sign = 1.0 if t.aggressor_side == OrderSide.BUY else -1.0
                    signed_volumes.append(sign * t.quantity)
                signed_volumes = np.array(signed_volumes, dtype=np.float64)

                sv_var = float(np.var(signed_volumes))
                if sv_var > 0:
                    cov = float(np.cov(price_changes, signed_volumes)[0, 1])
                    metrics.kyle_lambda = cov / sv_var

            # Roll spread estimate: 2 * sqrt(-cov(dp_t, dp_{t-1})) if cov < 0
            if len(prices) > 2:
                dp = np.diff(prices)
                auto_cov = float(np.cov(dp[:-1], dp[1:])[0, 1])
                if auto_cov < 0:
                    metrics.roll_spread = 2.0 * np.sqrt(-auto_cov)

        return metrics
