import json
import math


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
    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        # Restore persisted state
        if state.traderData:
            try:
                mem = json.loads(state.traderData)
            except Exception:
                mem = {}
        else:
            mem = {}

        result = {}

        for product in state.order_depths:
            od = state.order_depths[product]

            if product == "TOMATOES":
                orders, mem = self._tomatoes(od, state, mem, Order)
            else:
                orders = []

            result[product] = orders

        trader_data = json.dumps(mem)
        conversions = 0
        return result, conversions, trader_data

    # ─────────────────────────────────────────────────────────────────────────
    # TOMATOES — Max-Fill Touch Maker V3
    # ─────────────────────────────────────────────────────────────────────────
    def _tomatoes(self, od, state, mem, Order):
        orders = []
        pos = state.position.get("TOMATOES", 0)

        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None

        if best_ask is None or best_bid is None:
            return orders, mem

        mid = (best_bid + best_ask) / 2.0

        # ---------------------------------------------------------------------
        # Update history
        # ---------------------------------------------------------------------
        history = mem.get("tom_history", [])
        history.append(mid)
        if len(history) > TOM_HISTORY_MAX:
            history = history[-TOM_HISTORY_MAX:]
        mem["tom_history"] = history

        # Bootstrap: just sit at the touch
        if len(history) < TOM_SIGMA_WINDOW + 2:
            if pos < TOM_POSITION_LIM:
                qty = min(TOM_SIZE_BASE, TOM_POSITION_LIM - pos)
                if qty > 0:
                    orders.append(Order("TOMATOES", best_bid, qty))

            if pos > -TOM_POSITION_LIM:
                qty = min(TOM_SIZE_BASE, TOM_POSITION_LIM + pos)
                if qty > 0:
                    orders.append(Order("TOMATOES", best_ask, -qty))

            return orders, mem

        # ---------------------------------------------------------------------
        # Signal
        # ---------------------------------------------------------------------
        fair_fast = self._ema(history, TOM_FAIR_FAST)
        fair_slow = self._ema(history, TOM_FAIR_SLOW) if len(history) >= TOM_FAIR_SLOW else fair_fast
        sigma = max(self._rolling_std(history, TOM_SIGMA_WINDOW), 1.0)

        z = (mid - fair_fast) / sigma

        # Mild trend filter only affects size bias, not quote placement
        trend = 0
        if fair_fast > fair_slow:
            trend = 1
        elif fair_fast < fair_slow:
            trend = -1

        # ---------------------------------------------------------------------
        # Default: always quote at the touch
        # ---------------------------------------------------------------------
        my_bid = best_bid
        my_ask = best_ask

        bid_size = TOM_SIZE_BASE
        ask_size = TOM_SIZE_BASE
        place_bid = True
        place_ask = True

        # ---------------------------------------------------------------------
        # Signal-based size skew
        # Cheap -> bigger bid, smaller ask
        # Rich  -> smaller bid, bigger ask
        # ---------------------------------------------------------------------
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

        # ---------------------------------------------------------------------
        # Inventory control
        # Stay two-sided as long as possible.
        # Only get defensive when inventory is really stretched.
        # ---------------------------------------------------------------------
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

        # ---------------------------------------------------------------------
        # Rare tiny taker on very extreme dislocations
        # ---------------------------------------------------------------------
        if z <= -TOM_Z_TAKE and pos < TOM_POSITION_LIM:
            qty = min(TOM_TAKE_SIZE, TOM_POSITION_LIM - pos)
            if qty > 0 and best_ask <= fair_fast - 1:
                orders.append(Order("TOMATOES", best_ask, qty))

        elif z >= TOM_Z_TAKE and pos > -TOM_POSITION_LIM:
            qty = min(TOM_TAKE_SIZE, TOM_POSITION_LIM + pos)
            if qty > 0 and best_bid >= fair_fast + 1:
                orders.append(Order("TOMATOES", best_bid, -qty))

        # ---------------------------------------------------------------------
        # Passive bid
        # ---------------------------------------------------------------------
        if place_bid and pos < TOM_POSITION_LIM:
            qty = min(bid_size, TOM_POSITION_LIM - pos)
            if qty > 0 and my_bid < best_ask:
                orders.append(Order("TOMATOES", my_bid, qty))

        # ---------------------------------------------------------------------
        # Passive ask
        # ---------------------------------------------------------------------
        if place_ask and pos > -TOM_POSITION_LIM:
            qty = min(ask_size, TOM_POSITION_LIM + pos)
            if qty > 0 and my_ask > best_bid:
                orders.append(Order("TOMATOES", my_ask, -qty))

        return orders, mem

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
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