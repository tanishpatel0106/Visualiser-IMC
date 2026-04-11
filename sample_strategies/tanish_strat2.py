import json
import math


# ─────────────────────────────────────────────────────────────────────────────
# TOMATOES PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
TOM_POSITION_LIM = 20

# History / signal
TOM_HISTORY_MAX = 300
TOM_FAIR_FAST = 20
TOM_FAIR_SLOW = 80
TOM_SIGMA_WINDOW = 20

# Inventory control
TOM_INV_SOFT = 10
TOM_INV_HARD = 16
TOM_INV_PENALTY = 0.45

# Z-score thresholds
TOM_Z_LIGHT = 0.75
TOM_Z_MED = 1.25
TOM_Z_EXTREME = 1.75

# Sizes
TOM_SIZE_BASE = 3
TOM_SIZE_MED = 5
TOM_SIZE_HIGH = 7
TOM_SIZE_EXTREME = 9

# Small trend bias
TOM_TREND_WEIGHT = 0.20


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
    # TOMATOES — Top-of-Book Queue-Priority Maker
    # ─────────────────────────────────────────────────────────────────────────
    def _tomatoes(self, od, state, mem, Order):
        orders = []
        pos = state.position.get("TOMATOES", 0)

        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None

        if best_ask is None or best_bid is None:
            return orders, mem

        mid = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid

        # ---------------------------------------------------------------------
        # Update price history
        # ---------------------------------------------------------------------
        history = mem.get("tom_history", [])
        history.append(mid)
        if len(history) > TOM_HISTORY_MAX:
            history = history[-TOM_HISTORY_MAX:]
        mem["tom_history"] = history

        # Bootstrap
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
        # Fair value / sigma / z-score
        # ---------------------------------------------------------------------
        fair_fast = self._ema(history, TOM_FAIR_FAST)
        fair_slow = self._ema(history, TOM_FAIR_SLOW) if len(history) >= TOM_FAIR_SLOW else fair_fast
        sigma = max(self._rolling_std(history, TOM_SIGMA_WINDOW), 1.0)

        z = (mid - fair_fast) / sigma

        # Mild regime tilt
        trend_bias = 0.0
        if fair_fast > fair_slow:
            trend_bias = TOM_TREND_WEIGHT
        elif fair_fast < fair_slow:
            trend_bias = -TOM_TREND_WEIGHT

        # Inventory-adjusted reservation value
        reservation = fair_fast - TOM_INV_PENALTY * pos + trend_bias

        # ---------------------------------------------------------------------
        # Quote prices: prioritize presence at the touch
        # ---------------------------------------------------------------------
        my_bid = best_bid
        my_ask = best_ask

        # When inventory gets uncomfortable, skew quote competitiveness a bit
        # without abandoning touch-making completely too early.
        if pos >= TOM_INV_SOFT:
            my_bid = best_bid - 1
        if pos <= -TOM_INV_SOFT:
            my_ask = best_ask + 1

        # If reservation is strongly off mid, allow one side to become less
        # competitive, but still keep the other side at/near the touch.
        if reservation < mid - 1:
            my_bid = min(my_bid, best_bid - 1)
        elif reservation > mid + 1:
            my_ask = max(my_ask, best_ask + 1)

        # ---------------------------------------------------------------------
        # Base regime from z-score
        # ---------------------------------------------------------------------
        bid_size = TOM_SIZE_BASE
        ask_size = TOM_SIZE_BASE
        place_bid = True
        place_ask = True

        # Cheap -> lean buy
        if z <= -TOM_Z_EXTREME:
            bid_size = TOM_SIZE_EXTREME
            ask_size = 1
            place_bid = True
            place_ask = False if pos <= 0 else True

        elif z <= -TOM_Z_MED:
            bid_size = TOM_SIZE_HIGH
            ask_size = 1

        elif z <= -TOM_Z_LIGHT:
            bid_size = TOM_SIZE_MED
            ask_size = 2

        # Rich -> lean sell
        elif z >= TOM_Z_EXTREME:
            bid_size = 1
            ask_size = TOM_SIZE_EXTREME
            place_bid = False if pos >= 0 else True
            place_ask = True

        elif z >= TOM_Z_MED:
            bid_size = 1
            ask_size = TOM_SIZE_HIGH

        elif z >= TOM_Z_LIGHT:
            bid_size = 2
            ask_size = TOM_SIZE_MED

        # ---------------------------------------------------------------------
        # Inventory overrides
        # ---------------------------------------------------------------------
        # Strongly long -> reduce bidding, increase ask pressure
        if pos >= TOM_INV_HARD:
            place_bid = False
            place_ask = True
            ask_size = max(ask_size, TOM_SIZE_HIGH)
            my_ask = max(best_bid + 1, best_ask)

        elif pos >= TOM_INV_SOFT:
            bid_size = min(bid_size, 1)
            ask_size = max(ask_size, TOM_SIZE_MED)

        # Strongly short -> reduce asking, increase bid pressure
        if pos <= -TOM_INV_HARD:
            place_ask = False
            place_bid = True
            bid_size = max(bid_size, TOM_SIZE_HIGH)
            my_bid = min(best_ask - 1, best_bid)

        elif pos <= -TOM_INV_SOFT:
            ask_size = min(ask_size, 1)
            bid_size = max(bid_size, TOM_SIZE_MED)

        # ---------------------------------------------------------------------
        # Do not cross the book by accident
        # ---------------------------------------------------------------------
        if my_bid >= best_ask:
            my_bid = best_ask - 1
        if my_ask <= best_bid:
            my_ask = best_bid + 1

        # In very tight books, stay sensible
        if my_bid >= my_ask:
            my_bid = best_bid
            my_ask = best_ask
            if my_bid >= my_ask:
                return orders, mem

        # ---------------------------------------------------------------------
        # Place passive bid
        # ---------------------------------------------------------------------
        if place_bid and pos < TOM_POSITION_LIM:
            qty = min(bid_size, TOM_POSITION_LIM - pos)
            if qty > 0:
                orders.append(Order("TOMATOES", my_bid, qty))

        # ---------------------------------------------------------------------
        # Place passive ask
        # ---------------------------------------------------------------------
        if place_ask and pos > -TOM_POSITION_LIM:
            qty = min(ask_size, TOM_POSITION_LIM + pos)
            if qty > 0:
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
        if len(prices) < window:
            vals = prices
        else:
            vals = prices[-window:]

        if not vals:
            return 1.0

        mean_val = sum(vals) / len(vals)
        var = sum((x - mean_val) ** 2 for x in vals) / len(vals)
        return math.sqrt(var)