"""Mean reversion strategies for the IMC Prosperity trading terminal.

Each strategy is a standalone Trader class compatible with the
Prosperity sandbox adapter. All state is persisted via traderData
(JSON string) between calls.
"""

from __future__ import annotations

import inspect
import json
import math

from app.engines.strategies.registry import StrategyDefinition


# =====================================================================
# Helper utilities
# =====================================================================

def _get_mid_price(order_depth):
    """Compute mid price from an OrderDepth object."""
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return None
    best_bid = max(order_depth.buy_orders.keys())
    best_ask = min(order_depth.sell_orders.keys())
    return (best_bid + best_ask) / 2.0


def _clamp_order_qty(desired_qty: int, current_pos: int, max_position: int) -> int:
    """Clamp an order quantity so the resulting position stays within limits."""
    if desired_qty > 0:
        room = max_position - current_pos
        return max(0, min(desired_qty, room))
    elif desired_qty < 0:
        room = max_position + current_pos
        return min(0, max(desired_qty, -room))
    return 0


# =====================================================================
# MidPriceMeanReversion
# =====================================================================

class MidPriceMeanReversion:
    """Trades when mid price deviates from its rolling mean.

    Enters a position when the deviation exceeds entry_threshold
    standard deviations. Exits (or reduces) when deviation drops
    below exit_threshold.

    Parameters (via traderData JSON):
        window (int): Rolling window size, default 20.
        entry_threshold (float): Std devs from mean to enter, default 2.0.
        exit_threshold (float): Std devs from mean to exit, default 0.5.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.window = 20
        self.entry_threshold = 2.0
        self.exit_threshold = 0.5
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.window = trader_data.get("window", self.window)
            self.entry_threshold = trader_data.get("entry_threshold", self.entry_threshold)
            self.exit_threshold = trader_data.get("exit_threshold", self.exit_threshold)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        mid_history: dict[str, list[float]] = trader_data.get("mid_history", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            history = mid_history.get(product, [])
            history.append(mid)
            if len(history) > self.window:
                history = history[-self.window:]
            mid_history[product] = history

            if len(history) < self.window:
                result[product] = orders
                continue

            mean = sum(history) / len(history)
            variance = sum((p - mean) ** 2 for p in history) / len(history)
            std = math.sqrt(variance) if variance > 0 else 0.001

            z_score = (mid - mean) / std
            pos = state.position.get(product, 0)

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if z_score > self.entry_threshold:
                # Price is high -> sell (expect reversion down)
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))
            elif z_score < -self.entry_threshold:
                # Price is low -> buy (expect reversion up)
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif abs(z_score) < self.exit_threshold and pos != 0:
                # Close position near the mean
                if pos > 0:
                    qty = _clamp_order_qty(-min(pos, self.order_size), pos, self.max_position)
                    if qty < 0:
                        orders.append(Order(product, best_bid, qty))
                else:
                    qty = _clamp_order_qty(min(-pos, self.order_size), pos, self.max_position)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

            result[product] = orders

        trader_data.update({
            "window": self.window,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "mid_history": mid_history,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# BollingerBandReversion
# =====================================================================

class BollingerBandReversion:
    """Buys at the lower Bollinger Band and sells at the upper band.

    Parameters (via traderData JSON):
        window (int): Rolling window for mean and std, default 20.
        num_std (float): Number of standard deviations for bands, default 2.0.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.window = 20
        self.num_std = 2.0
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.window = trader_data.get("window", self.window)
            self.num_std = trader_data.get("num_std", self.num_std)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        mid_history: dict[str, list[float]] = trader_data.get("mid_history", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            history = mid_history.get(product, [])
            history.append(mid)
            if len(history) > self.window:
                history = history[-self.window:]
            mid_history[product] = history

            if len(history) < self.window:
                result[product] = orders
                continue

            mean = sum(history) / len(history)
            variance = sum((p - mean) ** 2 for p in history) / len(history)
            std = math.sqrt(variance) if variance > 0 else 0.001

            upper_band = mean + self.num_std * std
            lower_band = mean - self.num_std * std
            pos = state.position.get(product, 0)

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if mid <= lower_band:
                # Price at or below lower band -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif mid >= upper_band:
                # Price at or above upper band -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))
            elif abs(mid - mean) < std * 0.5 and pos != 0:
                # Near the mean, unwind position
                if pos > 0:
                    qty = _clamp_order_qty(-min(pos, self.order_size), pos, self.max_position)
                    if qty < 0:
                        orders.append(Order(product, best_bid, qty))
                else:
                    qty = _clamp_order_qty(min(-pos, self.order_size), pos, self.max_position)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

            result[product] = orders

        trader_data.update({
            "window": self.window,
            "num_std": self.num_std,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "mid_history": mid_history,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# ZScoreReversion
# =====================================================================

class ZScoreReversion:
    """Trades based on the z-score of the current price relative to a rolling mean.

    Parameters (via traderData JSON):
        window (int): Rolling window size, default 30.
        entry_z (float): Z-score threshold to enter, default 2.0.
        exit_z (float): Z-score threshold to exit, default 0.5.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.window = 30
        self.entry_z = 2.0
        self.exit_z = 0.5
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.window = trader_data.get("window", self.window)
            self.entry_z = trader_data.get("entry_z", self.entry_z)
            self.exit_z = trader_data.get("exit_z", self.exit_z)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        mid_history: dict[str, list[float]] = trader_data.get("mid_history", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            history = mid_history.get(product, [])
            history.append(mid)
            if len(history) > self.window:
                history = history[-self.window:]
            mid_history[product] = history

            if len(history) < self.window:
                result[product] = orders
                continue

            mean = sum(history) / len(history)
            variance = sum((p - mean) ** 2 for p in history) / len(history)
            std = math.sqrt(variance) if variance > 0 else 0.001
            z = (mid - mean) / std

            pos = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if z > self.entry_z:
                # Overpriced -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))
            elif z < -self.entry_z:
                # Underpriced -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif abs(z) < self.exit_z and pos != 0:
                # Close toward the mean
                if pos > 0:
                    qty = _clamp_order_qty(-min(pos, self.order_size), pos, self.max_position)
                    if qty < 0:
                        orders.append(Order(product, best_bid, qty))
                else:
                    qty = _clamp_order_qty(min(-pos, self.order_size), pos, self.max_position)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

            result[product] = orders

        trader_data.update({
            "window": self.window,
            "entry_z": self.entry_z,
            "exit_z": self.exit_z,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "mid_history": mid_history,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# VWAPReversion
# =====================================================================

class VWAPReversion:
    """Reverts to VWAP computed from market trade data.

    Computes a volume-weighted average price from recent trades and
    trades toward VWAP when the current mid deviates significantly.

    Parameters (via traderData JSON):
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
        threshold (float): Minimum deviation from VWAP to trade, default 1.5.
    """

    def __init__(self) -> None:
        self.order_size = 10
        self.max_position = 20
        self.threshold = 1.5

    def run(self, state):
        from app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)
            self.threshold = trader_data.get("threshold", self.threshold)

        # Accumulate VWAP components across calls
        vwap_data: dict[str, dict] = trader_data.get("vwap_data", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            # Update VWAP with new market trades
            pv = vwap_data.get(product, {})
            cum_pv = pv.get("cum_pv", 0.0)
            cum_vol = pv.get("cum_vol", 0)

            for trade in state.market_trades.get(product, []):
                cum_pv += trade.price * abs(trade.quantity)
                cum_vol += abs(trade.quantity)

            # Also include own trades
            for trade in state.own_trades.get(product, []):
                cum_pv += trade.price * abs(trade.quantity)
                cum_vol += abs(trade.quantity)

            vwap_data[product] = {"cum_pv": cum_pv, "cum_vol": cum_vol}

            if cum_vol == 0:
                result[product] = orders
                continue

            vwap = cum_pv / cum_vol
            deviation = mid - vwap
            pos = state.position.get(product, 0)

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if deviation > self.threshold:
                # Price above VWAP -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))
            elif deviation < -self.threshold:
                # Price below VWAP -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif abs(deviation) < self.threshold * 0.3 and pos != 0:
                # Near VWAP, unwind
                if pos > 0:
                    qty = _clamp_order_qty(-min(pos, self.order_size), pos, self.max_position)
                    if qty < 0:
                        orders.append(Order(product, best_bid, qty))
                else:
                    qty = _clamp_order_qty(min(-pos, self.order_size), pos, self.max_position)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))

            result[product] = orders

        trader_data.update({
            "order_size": self.order_size,
            "max_position": self.max_position,
            "threshold": self.threshold,
            "vwap_data": vwap_data,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# Strategy definitions for registry
# =====================================================================

_HELPER_SOURCE = inspect.getsource(_get_mid_price) + "\n\n" + inspect.getsource(_clamp_order_qty) + "\n\n"


def _get_source(cls) -> str:
    return _HELPER_SOURCE + inspect.getsource(cls)


STRATEGY_DEFINITIONS = [
    StrategyDefinition(
        strategy_id="mid_price_mean_reversion",
        name="Mid Price Mean Reversion",
        category="mean_reversion",
        description="Trades when the mid price deviates from its rolling mean by a configurable number of standard deviations.",
        source_code=_get_source(MidPriceMeanReversion),
        parameters={
            "window": {"type": "int", "default": 20, "description": "Rolling window size"},
            "entry_threshold": {"type": "float", "default": 2.0, "description": "Std devs from mean to enter"},
            "exit_threshold": {"type": "float", "default": 0.5, "description": "Std devs from mean to exit"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="bollinger_band_reversion",
        name="Bollinger Band Reversion",
        category="mean_reversion",
        description="Buys at the lower Bollinger Band and sells at the upper band, unwinding near the mean.",
        source_code=_get_source(BollingerBandReversion),
        parameters={
            "window": {"type": "int", "default": 20, "description": "Rolling window for mean and std"},
            "num_std": {"type": "float", "default": 2.0, "description": "Number of standard deviations for bands"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="z_score_reversion",
        name="Z-Score Reversion",
        category="mean_reversion",
        description="Trades based on the z-score of the current price relative to its rolling mean.",
        source_code=_get_source(ZScoreReversion),
        parameters={
            "window": {"type": "int", "default": 30, "description": "Rolling window size"},
            "entry_z": {"type": "float", "default": 2.0, "description": "Z-score threshold to enter"},
            "exit_z": {"type": "float", "default": 0.5, "description": "Z-score threshold to exit"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="vwap_reversion",
        name="VWAP Reversion",
        category="mean_reversion",
        description="Reverts to VWAP computed from trade data. Buys below VWAP, sells above it.",
        source_code=_get_source(VWAPReversion),
        parameters={
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
            "threshold": {"type": "float", "default": 1.5, "description": "Minimum deviation from VWAP to trade"},
        },
    ),
]
