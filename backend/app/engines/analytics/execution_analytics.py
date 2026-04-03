"""Execution quality analytics engine."""

from __future__ import annotations

import numpy as np

from backend.app.models.analytics import ExecutionMetrics
from backend.app.models.market import OrderSide, OrderStatus
from backend.app.models.trading import FillEvent, StrategyOrder


class ExecutionAnalyzer:
    """Computes execution quality metrics from orders and fills."""

    @staticmethod
    def compute_metrics(orders: list, fills: list) -> ExecutionMetrics:
        """
        Parameters
        ----------
        orders : list[StrategyOrder]
            All orders submitted during the session.
        fills : list[FillEvent]
            All fill events produced by the matching engine.

        Returns
        -------
        ExecutionMetrics
        """
        metrics = ExecutionMetrics()

        num_orders = len(orders)
        metrics.num_orders = num_orders
        metrics.fill_count = len(fills)

        if num_orders == 0:
            return metrics

        # -- Fill rates ------------------------------------------------ #
        filled_orders = [o for o in orders if o.status == OrderStatus.FILLED]
        partial_orders = [o for o in orders if o.status == OrderStatus.PARTIAL_FILL]
        cancelled_orders = [o for o in orders if o.status == OrderStatus.CANCELLED]
        rejected_orders = [o for o in orders if o.status == OrderStatus.REJECTED]

        metrics.full_fill_rate = len(filled_orders) / num_orders
        metrics.partial_fill_rate = len(partial_orders) / num_orders
        metrics.cancel_count = len(cancelled_orders)
        metrics.reject_count = len(rejected_orders)

        # -- Fill delay ------------------------------------------------ #
        # Build a lookup from order_id -> order for quick access
        order_map: dict[str, StrategyOrder] = {o.order_id: o for o in orders}

        fill_delays: list[float] = []
        for f in fills:
            order = order_map.get(f.order_id)
            if order is not None and order.created_at > 0 and f.timestamp >= order.created_at:
                fill_delays.append(float(f.timestamp - order.created_at))

        metrics.avg_fill_delay = float(np.mean(fill_delays)) if fill_delays else 0.0

        # -- Volume statistics ----------------------------------------- #
        total_fill_qty = sum(f.quantity for f in fills)
        metrics.total_volume_traded = total_fill_qty
        metrics.avg_fill_size = total_fill_qty / len(fills) if fills else 0.0

        maker_vol = sum(f.quantity for f in fills if not f.is_aggressive)
        taker_vol = sum(f.quantity for f in fills if f.is_aggressive)
        metrics.maker_volume = maker_vol
        metrics.taker_volume = taker_vol

        # Passive/aggressive ratio (maker / taker)
        metrics.passive_aggressive_ratio = (
            maker_vol / taker_vol if taker_vol > 0 else float("inf") if maker_vol > 0 else 0.0
        )

        # -- Effective spread captured --------------------------------- #
        # For passive fills the trader captures the spread; for aggressive
        # fills the trader pays the spread.  We approximate as the average
        # signed edge relative to the order limit price.
        spread_edges: list[float] = []
        for f in fills:
            order = order_map.get(f.order_id)
            if order is None or order.price == 0.0:
                continue
            if f.side == OrderSide.BUY:
                # Bought at f.price; wanted to buy at order.price (limit).
                # Edge = limit - fill (positive means bought cheaper).
                edge = order.price - f.price
            else:
                # Sold at f.price; wanted to sell at order.price (limit).
                # Edge = fill - limit (positive means sold higher).
                edge = f.price - order.price
            spread_edges.append(edge)

        metrics.effective_spread_captured = float(np.mean(spread_edges)) if spread_edges else 0.0

        # -- Estimated slippage ---------------------------------------- #
        # Slippage = difference between order price and actual fill price
        # (negative = worse than expected).
        slippages: list[float] = []
        for f in fills:
            order = order_map.get(f.order_id)
            if order is None or order.price == 0.0:
                continue
            if f.side == OrderSide.BUY:
                slippages.append(order.price - f.price)  # positive = good
            else:
                slippages.append(f.price - order.price)  # positive = good

        metrics.estimated_slippage = float(np.mean(slippages)) if slippages else 0.0

        return metrics

    # ------------------------------------------------------------------ #
    #  Adverse selection (markout analysis)                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def adverse_selection(
        fills: list,
        mid_prices: dict[int, float],
        horizon: int = 10,
    ) -> float:
        """
        Simple markout-based adverse selection metric.

        For each fill, compute the mid-price change over *horizon* ticks
        after the fill.  Adverse selection is the average mark-to-market
        loss experienced: for a buy, if the mid goes down afterwards, the
        fill suffered adverse selection (and vice-versa for sells).

        Parameters
        ----------
        fills : list[FillEvent]
        mid_prices : dict[int, float]
            Mapping of timestamp -> mid price.
        horizon : int
            Number of timestamp ticks to look ahead.

        Returns
        -------
        float
            Average adverse selection cost per unit.  Negative means the
            fills were on average adversely selected.
        """
        if not fills or not mid_prices:
            return 0.0

        sorted_ts = sorted(mid_prices.keys())
        markouts: list[float] = []

        for f in fills:
            # Find mid at fill time
            mid_at_fill = mid_prices.get(f.timestamp)
            if mid_at_fill is None:
                continue

            # Find mid at fill_time + horizon
            future_ts = f.timestamp + horizon
            # Find the closest available timestamp >= future_ts
            future_mid = None
            for ts in sorted_ts:
                if ts >= future_ts:
                    future_mid = mid_prices[ts]
                    break

            if future_mid is None:
                continue

            move = future_mid - mid_at_fill
            if f.side == OrderSide.BUY:
                markouts.append(move)  # positive = price went up = good for buyer
            else:
                markouts.append(-move)  # positive = price went down = good for seller

        return float(np.mean(markouts)) if markouts else 0.0
