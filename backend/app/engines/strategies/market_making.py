"""Market making strategies for the IMC Prosperity trading terminal.

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
    """Clamp an order quantity so the resulting position stays within limits.

    Parameters
    ----------
    desired_qty : int
        Positive for buy, negative for sell.
    current_pos : int
        Current net position.
    max_position : int
        Maximum absolute position allowed.

    Returns
    -------
    Clamped quantity (may be 0 if the order would breach limits).
    """
    if desired_qty > 0:
        room = max_position - current_pos
        return max(0, min(desired_qty, room))
    elif desired_qty < 0:
        room = max_position + current_pos
        return min(0, max(desired_qty, -room))
    return 0


# =====================================================================
# FixedSpreadMaker
# =====================================================================

class FixedSpreadMaker:
    """Places buy and sell orders at a fixed spread around the mid price.

    Parameters (via traderData JSON):
        spread (int): Total spread width, default 4.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
    """

    def __init__(self) -> None:
        self.spread = 4
        self.order_size = 10
        self.max_position = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.spread = trader_data.get("spread", self.spread)
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

            pos = state.position.get(product, 0)
            half_spread = self.spread / 2.0

            bid_price = int(math.floor(mid - half_spread))
            ask_price = int(math.ceil(mid + half_spread))

            buy_qty = _clamp_order_qty(self.order_size, pos, self.max_position)
            sell_qty = _clamp_order_qty(-self.order_size, pos, self.max_position)

            if buy_qty > 0:
                orders.append(Order(product, bid_price, buy_qty))
            if sell_qty < 0:
                orders.append(Order(product, ask_price, sell_qty))

            result[product] = orders

        trader_data.update({
            "spread": self.spread,
            "order_size": self.order_size,
            "max_position": self.max_position,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# InventorySkewedMaker
# =====================================================================

class InventorySkewedMaker:
    """Market maker that skews quotes based on current inventory.

    When holding a long position, the bid is lowered (less eager to buy)
    and the ask is lowered (more eager to sell), and vice versa.

    Parameters (via traderData JSON):
        base_spread (int): Base spread width, default 4.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
        skew_factor (float): How aggressively to skew per unit of inventory, default 0.5.
    """

    def __init__(self) -> None:
        self.base_spread = 4
        self.order_size = 10
        self.max_position = 20
        self.skew_factor = 0.5

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.base_spread = trader_data.get("base_spread", self.base_spread)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)
            self.skew_factor = trader_data.get("skew_factor", self.skew_factor)

        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            pos = state.position.get(product, 0)
            half_spread = self.base_spread / 2.0

            # Skew: shift the fair value away from current inventory
            skew = -self.skew_factor * pos
            adjusted_mid = mid + skew

            bid_price = int(math.floor(adjusted_mid - half_spread))
            ask_price = int(math.ceil(adjusted_mid + half_spread))

            buy_qty = _clamp_order_qty(self.order_size, pos, self.max_position)
            sell_qty = _clamp_order_qty(-self.order_size, pos, self.max_position)

            if buy_qty > 0:
                orders.append(Order(product, bid_price, buy_qty))
            if sell_qty < 0:
                orders.append(Order(product, ask_price, sell_qty))

            result[product] = orders

        trader_data.update({
            "base_spread": self.base_spread,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "skew_factor": self.skew_factor,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# AdaptiveSpreadMaker
# =====================================================================

class AdaptiveSpreadMaker:
    """Market maker that adapts spread to recent volatility.

    Tracks a rolling window of mid prices and computes standard
    deviation. High volatility widens the spread; low volatility
    tightens it.

    Parameters (via traderData JSON):
        min_spread (int): Minimum spread, default 2.
        max_spread (int): Maximum spread, default 8.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
        volatility_window (int): Number of mid price observations to track, default 20.
    """

    def __init__(self) -> None:
        self.min_spread = 2
        self.max_spread = 8
        self.order_size = 10
        self.max_position = 20
        self.volatility_window = 20

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.min_spread = trader_data.get("min_spread", self.min_spread)
            self.max_spread = trader_data.get("max_spread", self.max_spread)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)
            self.volatility_window = trader_data.get("volatility_window", self.volatility_window)

        # Per-product mid price history
        mid_history: dict[str, list[float]] = trader_data.get("mid_history", {})

        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            # Update history
            history = mid_history.get(product, [])
            history.append(mid)
            if len(history) > self.volatility_window:
                history = history[-self.volatility_window:]
            mid_history[product] = history

            # Compute volatility (std dev of mid prices)
            if len(history) >= 2:
                mean_mid = sum(history) / len(history)
                variance = sum((p - mean_mid) ** 2 for p in history) / len(history)
                vol = math.sqrt(variance)
            else:
                vol = 0.0

            # Map volatility to spread: higher vol -> wider spread
            # Normalize: if vol is 0, use min_spread; scale linearly
            if vol > 0:
                # Use a simple linear mapping; cap at max_spread
                spread = self.min_spread + vol * 2.0
                spread = max(self.min_spread, min(self.max_spread, spread))
            else:
                spread = self.min_spread

            pos = state.position.get(product, 0)
            half_spread = spread / 2.0

            bid_price = int(math.floor(mid - half_spread))
            ask_price = int(math.ceil(mid + half_spread))

            buy_qty = _clamp_order_qty(self.order_size, pos, self.max_position)
            sell_qty = _clamp_order_qty(-self.order_size, pos, self.max_position)

            if buy_qty > 0:
                orders.append(Order(product, bid_price, buy_qty))
            if sell_qty < 0:
                orders.append(Order(product, ask_price, sell_qty))

            result[product] = orders

        trader_data.update({
            "min_spread": self.min_spread,
            "max_spread": self.max_spread,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "volatility_window": self.volatility_window,
            "mid_history": mid_history,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# ReservationPriceMaker
# =====================================================================

class ReservationPriceMaker:
    """Avellaneda-Stoikov inspired market maker.

    Computes a reservation price that accounts for inventory risk:
        r = mid - gamma * pos * sigma^2 * T

    Then places quotes symmetrically around the reservation price
    with a spread determined by gamma, sigma, and kappa.

    Parameters (via traderData JSON):
        gamma (float): Risk aversion parameter, default 0.1.
        sigma (float): Estimated volatility (0 = auto-estimate), default 0.
        order_size (int): Size of each order, default 10.
        max_position (int): Maximum absolute position, default 20.
        kappa (float): Order arrival intensity parameter, default 1.5.
    """

    def __init__(self) -> None:
        self.gamma = 0.1
        self.sigma = 0.0
        self.order_size = 10
        self.max_position = 20
        self.kappa = 1.5

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.gamma = trader_data.get("gamma", self.gamma)
            self.sigma = trader_data.get("sigma", self.sigma)
            self.order_size = trader_data.get("order_size", self.order_size)
            self.max_position = trader_data.get("max_position", self.max_position)
            self.kappa = trader_data.get("kappa", self.kappa)

        mid_history: dict[str, list[float]] = trader_data.get("mid_history", {})
        result: dict[str, list] = {}

        for product in state.order_depths:
            orders = []
            depth = state.order_depths[product]
            mid = _get_mid_price(depth)
            if mid is None:
                result[product] = orders
                continue

            pos = state.position.get(product, 0)

            # Track mid history for sigma estimation
            history = mid_history.get(product, [])
            history.append(mid)
            if len(history) > 50:
                history = history[-50:]
            mid_history[product] = history

            # Estimate sigma if not provided
            sigma = self.sigma
            if sigma <= 0 and len(history) >= 5:
                returns = [
                    (history[i] - history[i - 1]) / history[i - 1]
                    for i in range(1, len(history))
                    if history[i - 1] != 0
                ]
                if returns:
                    mean_r = sum(returns) / len(returns)
                    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
                    sigma = math.sqrt(var_r) if var_r > 0 else 1.0
                else:
                    sigma = 1.0
            elif sigma <= 0:
                sigma = 1.0

            # Avellaneda-Stoikov reservation price
            # T represents remaining time fraction; use 1.0 as a simplification
            T = 1.0
            reservation_price = mid - self.gamma * pos * (sigma ** 2) * T

            # Optimal spread
            optimal_spread = (
                self.gamma * (sigma ** 2) * T
                + (2.0 / self.gamma) * math.log(1.0 + self.gamma / self.kappa)
            )
            optimal_spread = max(2.0, optimal_spread)

            half_spread = optimal_spread / 2.0
            bid_price = int(math.floor(reservation_price - half_spread))
            ask_price = int(math.ceil(reservation_price + half_spread))

            buy_qty = _clamp_order_qty(self.order_size, pos, self.max_position)
            sell_qty = _clamp_order_qty(-self.order_size, pos, self.max_position)

            if buy_qty > 0:
                orders.append(Order(product, bid_price, buy_qty))
            if sell_qty < 0:
                orders.append(Order(product, ask_price, sell_qty))

            result[product] = orders

        trader_data.update({
            "gamma": self.gamma,
            "sigma": self.sigma,
            "order_size": self.order_size,
            "max_position": self.max_position,
            "kappa": self.kappa,
            "mid_history": mid_history,
        })
        return result, 0, json.dumps(trader_data)


# =====================================================================
# LadderMaker
# =====================================================================

class LadderMaker:
    """Places multiple orders at different price levels around fair value.

    Creates a ladder of buy orders below mid and sell orders above mid,
    each level separated by level_spacing ticks.

    Parameters (via traderData JSON):
        num_levels (int): Number of price levels on each side, default 3.
        level_spacing (int): Tick spacing between levels, default 1.
        order_size (int): Size per level, default 5.
        max_position (int): Maximum absolute position, default 30.
    """

    def __init__(self) -> None:
        self.num_levels = 3
        self.level_spacing = 1
        self.order_size = 5
        self.max_position = 30

    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        trader_data: dict = {}
        if state.traderData:
            trader_data = json.loads(state.traderData)
            self.num_levels = trader_data.get("num_levels", self.num_levels)
            self.level_spacing = trader_data.get("level_spacing", self.level_spacing)
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

            pos = state.position.get(product, 0)
            mid_int = int(round(mid))

            # Place buy ladder below mid
            for level in range(1, self.num_levels + 1):
                price = mid_int - level * self.level_spacing
                qty = _clamp_order_qty(self.order_size, pos, self.max_position)
                if qty > 0:
                    orders.append(Order(product, price, qty))
                    # Anticipate the fill for position clamping of next level
                    pos += qty

            # Reset pos for sell side
            pos = state.position.get(product, 0)

            # Place sell ladder above mid
            for level in range(1, self.num_levels + 1):
                price = mid_int + level * self.level_spacing
                qty = _clamp_order_qty(-self.order_size, pos, self.max_position)
                if qty < 0:
                    orders.append(Order(product, price, qty))
                    pos += qty

            result[product] = orders

        trader_data.update({
            "num_levels": self.num_levels,
            "level_spacing": self.level_spacing,
            "order_size": self.order_size,
            "max_position": self.max_position,
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
        strategy_id="fixed_spread_maker",
        name="Fixed Spread Maker",
        category="market_making",
        description="Places buy and sell orders at a fixed spread around the mid price. Simple and predictable.",
        source_code=_get_source(FixedSpreadMaker),
        parameters={
            "spread": {"type": "int", "default": 4, "description": "Total spread width"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
        },
    ),
    StrategyDefinition(
        strategy_id="inventory_skewed_maker",
        name="Inventory Skewed Maker",
        category="market_making",
        description="Adjusts quotes based on current inventory to reduce risk. Skews price away from accumulated position.",
        source_code=_get_source(InventorySkewedMaker),
        parameters={
            "base_spread": {"type": "int", "default": 4, "description": "Base spread width"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
            "skew_factor": {"type": "float", "default": 0.5, "description": "How aggressively to skew per unit of inventory"},
        },
    ),
    StrategyDefinition(
        strategy_id="adaptive_spread_maker",
        name="Adaptive Spread Maker",
        category="market_making",
        description="Widens spread when volatility is high, tightens when low. Tracks rolling mid prices to estimate volatility.",
        source_code=_get_source(AdaptiveSpreadMaker),
        parameters={
            "min_spread": {"type": "int", "default": 2, "description": "Minimum spread"},
            "max_spread": {"type": "int", "default": 8, "description": "Maximum spread"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
            "volatility_window": {"type": "int", "default": 20, "description": "Number of observations for volatility calculation"},
        },
    ),
    StrategyDefinition(
        strategy_id="reservation_price_maker",
        name="Reservation Price Maker",
        category="market_making",
        description="Avellaneda-Stoikov inspired market maker. Computes reservation price based on inventory risk and sets optimal spread.",
        source_code=_get_source(ReservationPriceMaker),
        parameters={
            "gamma": {"type": "float", "default": 0.1, "description": "Risk aversion parameter"},
            "sigma": {"type": "float", "default": 0.0, "description": "Estimated volatility (0 = auto-estimate)"},
            "order_size": {"type": "int", "default": 10, "description": "Size of each order"},
            "max_position": {"type": "int", "default": 20, "description": "Maximum absolute position"},
            "kappa": {"type": "float", "default": 1.5, "description": "Order arrival intensity parameter"},
        },
    ),
    StrategyDefinition(
        strategy_id="ladder_maker",
        name="Ladder Maker",
        category="market_making",
        description="Places multiple orders at different price levels around fair value, creating a ladder of liquidity.",
        source_code=_get_source(LadderMaker),
        parameters={
            "num_levels": {"type": "int", "default": 3, "description": "Number of price levels on each side"},
            "level_spacing": {"type": "int", "default": 1, "description": "Tick spacing between levels"},
            "order_size": {"type": "int", "default": 5, "description": "Size per level"},
            "max_position": {"type": "int", "default": 30, "description": "Maximum absolute position"},
        },
    ),
]
