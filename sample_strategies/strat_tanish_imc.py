from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math


# ─────────────────────────────────────────────────────────────────────────────
# EMERALDS PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
EM_FAIR_VALUE = 10_000
EM_POSITION_LIM = 20
EM_BID_NORMAL = 9_993
EM_ASK_NORMAL = 10_007
EM_BID_AGG = 9_997
EM_ASK_AGG = 10_003
EM_TRADE_SIZE = 5

# ─────────────────────────────────────────────────────────────────────────────
# TOMATOES PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
TOM_POSITION_LIM = 20

# History / signal
TOM_HISTORY_MAX = 400
TOM_FAIR_FAST = 20
TOM_FAIR_SLOW = 80
TOM_SIGMA_WINDOW = 20

# Inventory control
TOM_INV_SOFT = 12
TOM_INV_HARD = 17

# Z-score thresholds
TOM_Z_LIGHT = 0.75
TOM_Z_MED = 1.50
TOM_Z_EXTREME = 2.25
TOM_Z_TAKE = 3.00

# Sizes
TOM_SIZE_BASE = 5
TOM_SIZE_LIGHT = 6
TOM_SIZE_MED = 7
TOM_SIZE_HIGH = 9
TOM_SIZE_EXTREME = 10

# Tiny taker
TOM_TAKE_SIZE = 1


class Trader:
    def bid(self):
        # Optional for Round 2; harmless in other rounds.
        return 15

    def run(self, state: TradingState):
        mem = self._load_mem(state.traderData)
        result: Dict[str, List[Order]] = {}

        for product, od in state.order_depths.items():
            if product == "TOMATOES":
                orders = self._tomatoes(od, state, mem)
            elif product == "EMERALDS":
                orders = self._emeralds(od, state, mem)
            else:
                orders = []

            result[product] = orders

        trader_data = self._dump_mem(mem)
        conversions = 0
        return result, conversions, trader_data

    # ─────────────────────────────────────────────────────────────────────────
    # EMERALDS — OU Market Maker
    # ─────────────────────────────────────────────────────────────────────────
    def _emeralds(self, od: OrderDepth, state: TradingState, mem: dict) -> List[Order]:
        product = "EMERALDS"
        orders: List[Order] = []
        pos = state.position.get(product, 0)

        if not od.sell_orders or not od.buy_orders:
            return orders

        best_ask = min(od.sell_orders.keys())
        best_bid = max(od.buy_orders.keys())
        best_ask_vol = -od.sell_orders[best_ask]
        best_bid_vol = od.buy_orders[best_bid]

        mid = (best_bid + best_ask) / 2.0

        # Quote regime
        if mid <= 9996:
            my_bid, my_ask = EM_BID_AGG, EM_ASK_AGG
        else:
            my_bid, my_ask = EM_BID_NORMAL, EM_ASK_NORMAL

        buy_used = 0
        sell_used = 0

        # Aggressive buy
        if best_ask <= my_bid:
            qty = min(EM_TRADE_SIZE, best_ask_vol)
            buy_used = self._place_buy(
                orders, product, best_ask, qty, pos, EM_POSITION_LIM, buy_used
            )

        # Aggressive sell
        if best_bid >= my_ask:
            qty = min(EM_TRADE_SIZE, best_bid_vol)
            sell_used = self._place_sell(
                orders, product, best_bid, qty, pos, EM_POSITION_LIM, sell_used
            )

        # Passive bid
        if my_bid < best_ask:
            buy_used = self._place_buy(
                orders, product, my_bid, EM_TRADE_SIZE, pos, EM_POSITION_LIM, buy_used
            )

        # Passive ask
        if my_ask > best_bid:
            sell_used = self._place_sell(
                orders, product, my_ask, EM_TRADE_SIZE, pos, EM_POSITION_LIM, sell_used
            )

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    # TOMATOES — Max-Fill Touch Maker V3
    # ─────────────────────────────────────────────────────────────────────────
    def _tomatoes(self, od: OrderDepth, state: TradingState, mem: dict) -> List[Order]:
        product = "TOMATOES"
        orders: List[Order] = []
        pos = state.position.get(product, 0)

        if not od.sell_orders or not od.buy_orders:
            return orders

        best_ask = min(od.sell_orders.keys())
        best_bid = max(od.buy_orders.keys())
        best_ask_vol = -od.sell_orders[best_ask]
        best_bid_vol = od.buy_orders[best_bid]

        mid = (best_bid + best_ask) / 2.0

        # Update history
        history = mem.get("tom_history", [])
        history.append(mid)
        if len(history) > TOM_HISTORY_MAX:
            history = history[-TOM_HISTORY_MAX:]
        mem["tom_history"] = history

        buy_used = 0
        sell_used = 0

        # Bootstrap: quote at the touch
        if len(history) < TOM_SIGMA_WINDOW + 2:
            if best_bid < best_ask:
                buy_used = self._place_buy(
                    orders,
                    product,
                    best_bid,
                    TOM_SIZE_BASE,
                    pos,
                    TOM_POSITION_LIM,
                    buy_used,
                )
                sell_used = self._place_sell(
                    orders,
                    product,
                    best_ask,
                    TOM_SIZE_BASE,
                    pos,
                    TOM_POSITION_LIM,
                    sell_used,
                )
            return orders

        # Signal
        fair_fast = self._ema(history, TOM_FAIR_FAST)
        fair_slow = (
            self._ema(history, TOM_FAIR_SLOW)
            if len(history) >= TOM_FAIR_SLOW
            else fair_fast
        )
        sigma = max(self._rolling_std(history, TOM_SIGMA_WINDOW), 1.0)
        z = (mid - fair_fast) / sigma

        trend = 0
        if fair_fast > fair_slow:
            trend = 1
        elif fair_fast < fair_slow:
            trend = -1

        # Default: always quote at the touch
        my_bid = best_bid
        my_ask = best_ask

        bid_size = TOM_SIZE_BASE
        ask_size = TOM_SIZE_BASE
        place_bid = True
        place_ask = True

        # Signal-based size skew
        if z <= -TOM_Z_EXTREME:
            bid_size = TOM_SIZE_EXTREME
            ask_size = 1
        elif z <= -TOM_Z_MED:
            bid_size = TOM_SIZE_HIGH
            ask_size = 2
        elif z <= -TOM_Z_LIGHT:
            bid_size = TOM_SIZE_LIGHT
            ask_size = 3
        elif z >= TOM_Z_EXTREME:
            bid_size = 1
            ask_size = TOM_SIZE_EXTREME
        elif z >= TOM_Z_MED:
            bid_size = 2
            ask_size = TOM_SIZE_HIGH
        elif z >= TOM_Z_LIGHT:
            bid_size = 3
            ask_size = TOM_SIZE_LIGHT

        # Mild trend nudge
        if trend > 0:
            if z <= 0:
                bid_size = min(bid_size + 1, TOM_SIZE_EXTREME)
            if z > 0:
                ask_size = max(1, ask_size - 1)
        elif trend < 0:
            if z >= 0:
                ask_size = min(ask_size + 1, TOM_SIZE_EXTREME)
            if z < 0:
                bid_size = max(1, bid_size - 1)

        # Inventory control
        if pos >= TOM_INV_HARD:
            place_bid = False
            place_ask = True
            ask_size = max(ask_size, TOM_SIZE_HIGH)
        elif pos >= TOM_INV_SOFT:
            bid_size = 1
            ask_size = max(ask_size, TOM_SIZE_MED)

        if pos <= -TOM_INV_HARD:
            place_ask = False
            place_bid = True
            bid_size = max(bid_size, TOM_SIZE_HIGH)
        elif pos <= -TOM_INV_SOFT:
            ask_size = 1
            bid_size = max(bid_size, TOM_SIZE_MED)

        # Rare tiny taker on very extreme dislocations
        if z <= -TOM_Z_TAKE and best_ask <= fair_fast - 1:
            qty = min(TOM_TAKE_SIZE, best_ask_vol)
            buy_used = self._place_buy(
                orders, product, best_ask, qty, pos, TOM_POSITION_LIM, buy_used
            )

        elif z >= TOM_Z_TAKE and best_bid >= fair_fast + 1:
            qty = min(TOM_TAKE_SIZE, best_bid_vol)
            sell_used = self._place_sell(
                orders, product, best_bid, qty, pos, TOM_POSITION_LIM, sell_used
            )

        # Passive bid
        if place_bid and my_bid < best_ask:
            buy_used = self._place_buy(
                orders, product, my_bid, bid_size, pos, TOM_POSITION_LIM, buy_used
            )

        # Passive ask
        if place_ask and my_ask > best_bid:
            sell_used = self._place_sell(
                orders, product, my_ask, ask_size, pos, TOM_POSITION_LIM, sell_used
            )

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    # ORDER / RISK HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _buy_capacity(self, pos: int, limit: int, buy_used: int) -> int:
        return max(0, limit - pos - buy_used)

    def _sell_capacity(self, pos: int, limit: int, sell_used: int) -> int:
        return max(0, pos + limit - sell_used)

    def _place_buy(
        self,
        orders: List[Order],
        product: str,
        price: int,
        desired_qty: int,
        pos: int,
        limit: int,
        buy_used: int,
    ) -> int:
        cap = self._buy_capacity(pos, limit, buy_used)
        qty = min(int(desired_qty), cap)
        if qty > 0:
            orders.append(Order(product, int(price), qty))
            buy_used += qty
        return buy_used

    def _place_sell(
        self,
        orders: List[Order],
        product: str,
        price: int,
        desired_qty: int,
        pos: int,
        limit: int,
        sell_used: int,
    ) -> int:
        cap = self._sell_capacity(pos, limit, sell_used)
        qty = min(int(desired_qty), cap)
        if qty > 0:
            orders.append(Order(product, int(price), -qty))
            sell_used += qty
        return sell_used

    # ─────────────────────────────────────────────────────────────────────────
    # STATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _load_mem(self, trader_data: str) -> dict:
        if not trader_data:
            return {}
        try:
            mem = json.loads(trader_data)
            return mem if isinstance(mem, dict) else {}
        except Exception:
            return {}

    def _dump_mem(self, mem: dict) -> str:
        try:
            return json.dumps(mem, separators=(",", ":"))
        except Exception:
            return "{}"

    # ─────────────────────────────────────────────────────────────────────────
    # SIGNAL HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _ema(self, prices, span):
        if not prices:
            return 0.0

        k = 2.0 / (span + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _rolling_std(self, prices, window):
        vals = prices[-window:] if len(prices) >= window else prices
        if not vals:
            return 1.0

        mean_val = sum(vals) / len(vals)
        var = sum((x - mean_val) ** 2 for x in vals) / len(vals)
        return math.sqrt(var)