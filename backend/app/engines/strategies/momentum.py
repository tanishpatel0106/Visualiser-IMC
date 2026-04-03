"""Momentum and trend-following strategies for the IMC Prosperity trading terminal.

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
# EMACrossover
# =====================================================================

class EMACrossover:
    """Buys when the fast EMA crosses above the slow EMA, sells on the reverse.

    EMA values are computed incrementally using the standard smoothing
    formula: EMA_new = alpha * price + (1 - alpha) * EMA_old.

    Parameters (via traderData JSON):
        fast_period (int): Fast EMA period, default 5.
        slow_period (int): Slow EMA period, default 20.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.fast_period = 5
        self.slow_period = 20
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.fast_period = trader_data.get("fast_period", self.fast_period)
            self.slow_period = trader_data.get("slow_period", self.slow_period)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        ema_state: dict[str, dict] = trader_data.get("ema_state", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            es = ema_state.get(product, {})
            fast_ema = es.get("fast_ema")
            slow_ema = es.get("slow_ema")
            prev_fast = es.get("prev_fast")
            prev_slow = es.get("prev_slow")
            tick_count = es.get("tick_count", 0)
            tick_count += 1

            fast_alpha = 2.0 / (self.fast_period + 1)
            slow_alpha = 2.0 / (self.slow_period + 1)

            if fast_ema is None:
                fast_ema = mid
                slow_ema = mid
            else:
                prev_fast = fast_ema
                prev_slow = slow_ema
                fast_ema = fast_alpha * mid + (1 - fast_alpha) * fast_ema
                slow_ema = slow_alpha * mid + (1 - slow_alpha) * slow_ema

            ema_state[product] = {
                "fast_ema": fast_ema,
                "slow_ema": slow_ema,
                "prev_fast": prev_fast,
                "prev_slow": prev_slow,
                "tick_count": tick_count,
            }

            # Need at least slow_period ticks before trading
            if tick_count < self.slow_period or prev_fast is None or prev_slow is None:
                result[product] = orders
                continue

            pos = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            # Detect crossover
            was_below = prev_fast <= prev_slow
            is_above = fast_ema > slow_ema

            was_above = prev_fast >= prev_slow
            is_below = fast_ema < slow_ema

            if was_below and is_above:
                # Bullish crossover -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif was_above and is_below:
                # Bearish crossover -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))

            result[product] = orders

        trader_data.update({
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "ema_state": ema_state,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# SMACrossover
# =====================================================================

class SMACrossover:
    """Buys when the fast SMA crosses above the slow SMA, sells on the reverse.

    Parameters (via traderData JSON):
        fast_period (int): Fast SMA window, default 5.
        slow_period (int): Slow SMA window, default 20.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.fast_period = 5
        self.slow_period = 20
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.fast_period = trader_data.get("fast_period", self.fast_period)
            self.slow_period = trader_data.get("slow_period", self.slow_period)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        price_history: dict[str, list[float]] = trader_data.get("price_history", {})
        prev_signal: dict[str, str] = trader_data.get("prev_signal", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            history = price_history.get(product, [])
            history.append(mid)
            # Keep enough history for the slow window
            max_len = self.slow_period + 5
            if len(history) > max_len:
                history = history[-max_len:]
            price_history[product] = history

            if len(history) < self.slow_period:
                result[product] = orders
                continue

            fast_sma = sum(history[-self.fast_period:]) / self.fast_period
            slow_sma = sum(history[-self.slow_period:]) / self.slow_period

            current_signal = "bullish" if fast_sma > slow_sma else "bearish"
            last_signal = prev_signal.get(product, "neutral")
            prev_signal[product] = current_signal

            pos = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if current_signal == "bullish" and last_signal != "bullish":
                # Bullish crossover -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif current_signal == "bearish" and last_signal != "bearish":
                # Bearish crossover -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))

            result[product] = orders

        trader_data.update({
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "price_history": price_history,
            "prev_signal": prev_signal,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# BreakoutStrategy
# =====================================================================

class BreakoutStrategy:
    """Buys on new highs, sells on new lows over a lookback window.

    Parameters (via traderData JSON):
        lookback (int): Window for highs/lows, default 20.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.lookback = 20
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.lookback = trader_data.get("lookback", self.lookback)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        price_history: dict[str, list[float]] = trader_data.get("price_history", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            history = price_history.get(product, [])
            history.append(mid)
            max_len = self.lookback + 5
            if len(history) > max_len:
                history = history[-max_len:]
            price_history[product] = history

            if len(history) < self.lookback + 1:
                result[product] = orders
                continue

            # The lookback window is the previous self.lookback prices (not including current)
            lookback_window = history[-(self.lookback + 1):-1]
            highest = max(lookback_window)
            lowest = min(lookback_window)

            pos = state.position.get(product, 0)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if mid > highest:
                # Breakout high -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif mid < lowest:
                # Breakout low -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))

            result[product] = orders

        trader_data.update({
            "lookback": self.lookback,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "price_history": price_history,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# MomentumStrategy
# =====================================================================

class MomentumStrategy:
    """Trades based on rolling return momentum.

    Computes the return over the lookback window. If the return exceeds
    the threshold, trades in the direction of the momentum.

    Parameters (via traderData JSON):
        lookback (int): Window for return computation, default 10.
        threshold (float): Minimum return to trigger, default 0.001.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.lookback = 10
        self.threshold = 0.001
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.lookback = trader_data.get("lookback", self.lookback)
            self.threshold = trader_data.get("threshold", self.threshold)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        price_history: dict[str, list[float]] = trader_data.get("price_history", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            history = price_history.get(product, [])
            history.append(mid)
            max_len = self.lookback + 5
            if len(history) > max_len:
                history = history[-max_len:]
            price_history[product] = history

            if len(history) < self.lookback + 1:
                result[product] = orders
                continue

            past_price = history[-(self.lookback + 1)]
            if past_price == 0:
                result[product] = orders
                continue

            ret = (mid - past_price) / past_price
            pos = state.position.get(product, 0)

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if ret > self.threshold:
                # Positive momentum -> buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif ret < -self.threshold:
                # Negative momentum -> sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))

            result[product] = orders

        trader_data.update({
            "lookback": self.lookback,
            "threshold": self.threshold,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "price_history": price_history,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# TradeFlowMomentum
# =====================================================================

class TradeFlowMomentum:
    """Follows the net trade flow direction.

    Tracks the net signed volume of market trades over a rolling window.
    Positive net flow (more buyer-initiated) triggers a buy; negative
    triggers a sell.

    Parameters (via traderData JSON):
        window (int): Number of ticks to accumulate flow, default 10.
        threshold (int): Minimum net volume to trigger, default 5.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.window = 10
        self.threshold = 5
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.window = trader_data.get("window", self.window)
            self.threshold = trader_data.get("threshold", self.threshold)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)

        flow_history: dict[str, list[int]] = trader_data.get("flow_history", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            # Compute net flow for this tick from market trades
            net_flow = 0
            for trade in state.market_trades.get(product, []):
                # Positive quantity = buyer-initiated, negative = seller-initiated
                net_flow += trade.quantity

            fh = flow_history.get(product, [])
            fh.append(net_flow)
            if len(fh) > self.window:
                fh = fh[-self.window:]
            flow_history[product] = fh

            if len(fh) < 2:
                result[product] = orders
                continue

            total_flow = sum(fh)
            pos = state.position.get(product, 0)

            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(mid) - 1
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(mid) + 1

            if total_flow > self.threshold:
                # Net buying pressure -> follow with buy
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            elif total_flow < -self.threshold:
                # Net selling pressure -> follow with sell
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, best_bid, qty))

            result[product] = orders

        trader_data.update({
            "window": self.window,
            "threshold": self.threshold,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "flow_history": flow_history,
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
        strategy_id="ema_crossover",
        name="EMA Crossover",
        category="momentum",
        description="Buys when the fast EMA crosses above the slow EMA and sells on the reverse crossover.",
        source_code=_get_source(EMACrossover),
        parameters={
            "fast_period": {"type": "int", "default": 5, "description": "Fast EMA period"},
            "slow_period": {"type": "int", "default": 20, "description": "Slow EMA period"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="sma_crossover",
        name="SMA Crossover",
        category="momentum",
        description="Buys when the fast SMA crosses above the slow SMA and sells on the reverse crossover.",
        source_code=_get_source(SMACrossover),
        parameters={
            "fast_period": {"type": "int", "default": 5, "description": "Fast SMA window"},
            "slow_period": {"type": "int", "default": 20, "description": "Slow SMA window"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="breakout_strategy",
        name="Breakout Strategy",
        category="momentum",
        description="Buys on new highs over a lookback window, sells on new lows.",
        source_code=_get_source(BreakoutStrategy),
        parameters={
            "lookback": {"type": "int", "default": 20, "description": "Window for highs/lows"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="momentum_strategy",
        name="Momentum Strategy",
        category="momentum",
        description="Trades based on rolling return momentum over a lookback window.",
        source_code=_get_source(MomentumStrategy),
        parameters={
            "lookback": {"type": "int", "default": 10, "description": "Window for return computation"},
            "threshold": {"type": "float", "default": 0.001, "description": "Minimum return to trigger"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="trade_flow_momentum",
        name="Trade Flow Momentum",
        category="momentum",
        description="Follows the net trade flow direction. Buys on net buying pressure, sells on net selling pressure.",
        source_code=_get_source(TradeFlowMomentum),
        parameters={
            "window": {"type": "int", "default": 10, "description": "Number of ticks to accumulate flow"},
            "threshold": {"type": "int", "default": 5, "description": "Minimum net volume to trigger"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
]
