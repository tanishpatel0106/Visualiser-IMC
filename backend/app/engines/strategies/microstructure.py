"""Microstructure strategies for the IMC Prosperity trading terminal.

Each strategy is a standalone Trader class compatible with the
Prosperity sandbox adapter. All state is persisted via traderData
(JSON string) between calls.
"""

from __future__ import annotations

import inspect
import json
import math

from backend.app.engines.strategies.registry import StrategyDefinition


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
# ImbalanceFollower
# =====================================================================

class ImbalanceFollower:
    """Trades in the direction of order book imbalance.

    Computes the ratio of total bid volume to total ask volume.
    When bids dominate (imbalance > threshold), buys; when asks
    dominate, sells.

    Parameters (via traderData JSON):
        imbalance_threshold (float): Minimum imbalance ratio deviation from 0.5, default 0.3.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.imbalance_threshold = 0.3
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.imbalance_threshold = trader_data.get("imbalance_threshold", self.imbalance_threshold)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            # Compute total bid and ask volumes
            total_bid_vol = sum(depth.buy_orders.values())  # positive values
            total_ask_vol = sum(abs(v) for v in depth.sell_orders.values())  # sell_orders are negative

            total_vol = total_bid_vol + total_ask_vol
            if total_vol == 0:
                result[product] = orders
                continue

            # Imbalance ratio: 1.0 = all bids, 0.0 = all asks, 0.5 = balanced
            imbalance = total_bid_vol / total_vol

            pos = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())

            if imbalance > 0.5 + self.imbalance_threshold:
                # Strong bid imbalance -> price likely to rise -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif imbalance < 0.5 - self.imbalance_threshold:
                # Strong ask imbalance -> price likely to fall -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))

            result[product] = orders

        trader_data.update({
            "imbalance_threshold": self.imbalance_threshold,
            "order_size": self.order_size,
            "max_position": self.max_position,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# SpreadCapture
# =====================================================================

class SpreadCapture:
    """Places passive orders on both sides to capture the bid-ask spread.

    Only places orders when the spread is wide enough. Posts at
    best_bid + 1 and best_ask - 1 to be first in queue while
    still capturing spread.

    Parameters (via traderData JSON):
        min_spread (int): Minimum spread width to participate, default 2.
        order_size (int): Size of each order, default 5.
        max_position (int): Maximum absolute position, default 15.
    """

    def __init__(self) -> None:
        self.min_spread = 2
        self.order_size = 5
        self.max_position = 15

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.min_spread = trader_data.get("min_spread", self.min_spread)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]

            if not depth.buy_orders or not depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            spread = best_ask - best_bid

            if spread < self.min_spread:
                result[product] = orders
                continue

            pos = state.position.get(product, 0)

            # Post inside the spread to be competitive
            # If spread is wide enough, improve by 1 tick
            our_bid = best_bid + 1 if spread > 2 else best_bid
            our_ask = best_ask - 1 if spread > 2 else best_ask

            buy_qty = _clamp_order_qty(self.order_size, pos, self.max_position)
            sell_qty = _clamp_order_qty(-self.order_size, pos, self.max_position)

            if buy_qty > 0:
                orders.append(Order(product, our_bid, buy_qty))
            if sell_qty < 0:
                orders.append(Order(product, our_ask, sell_qty))

            result[product] = orders

        trader_data.update({
            "min_spread": self.min_spread,
            "order_size": self.order_size,
            "max_position": self.max_position,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# TradeburstReaction
# =====================================================================

class TradeburstReaction:
    """Detects bursts of trades and follows the direction.

    When a burst of trades (more than burst_count in recent ticks)
    is detected, the strategy trades in the direction of the net
    volume of that burst.

    Parameters (via traderData JSON):
        burst_count (int): Minimum number of trades to consider a burst, default 5.
        burst_window (int): Number of ticks to look back for burst detection, default 10.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.burst_count = 5
        self.burst_window = 10
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.burst_count = trader_data.get("burst_count", self.burst_count)
            self.burst_window = trader_data.get("burst_window", self.burst_window)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        # Track trade counts and net volume per tick per product
        trade_log: dict[str, list[dict]] = trader_data.get("trade_log", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            # Record this tick's market trades
            market_trades = state.market_trades.get(product, [])
            tick_count = len(market_trades)
            tick_net_vol = sum(t.quantity for t in market_trades)

            log = trade_log.get(product, [])
            log.append({"count": tick_count, "net_vol": tick_net_vol})
            if len(log) > self.burst_window:
                log = log[-self.burst_window:]
            trade_log[product] = log

            # Check for burst: total trade count over window
            total_trades = sum(entry["count"] for entry in log)
            total_net_vol = sum(entry["net_vol"] for entry in log)

            if total_trades < self.burst_count:
                result[product] = orders
                continue

            pos = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if total_net_vol > 0:
                # Net buying burst -> follow with buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif total_net_vol < 0:
                # Net selling burst -> follow with sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))

            result[product] = orders

        trader_data.update({
            "burst_count": self.burst_count,
            "burst_window": self.burst_window,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "trade_log": trade_log,
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
        strategy_id="imbalance_follower",
        name="Imbalance Follower",
        category="microstructure",
        description="Trades in the direction of order book imbalance. Buys when bids dominate, sells when asks dominate.",
        source_code=_get_source(ImbalanceFollower),
        parameters={
            "imbalance_threshold": {"type": "float", "default": 0.3, "description": "Minimum imbalance ratio deviation from 0.5"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="spread_capture",
        name="Spread Capture",
        category="microstructure",
        description="Places passive orders to capture the bid-ask spread. Only participates when spread is wide enough.",
        source_code=_get_source(SpreadCapture),
        parameters={
            "min_spread": {"type": "int", "default": 2, "description": "Minimum spread width to participate"},
            "order_size": {"type": "int", "default": 5, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 15, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="tradeburst_reaction",
        name="Tradeburst Reaction",
        category="microstructure",
        description="Detects bursts of trades and follows the direction of the net volume.",
        source_code=_get_source(TradeburstReaction),
        parameters={
            "burst_count": {"type": "int", "default": 5, "description": "Minimum number of trades to consider a burst"},
            "burst_window": {"type": "int", "default": 10, "description": "Number of ticks to look back"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
]
