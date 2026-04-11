import json
import math


# ─────────────────────────────────────────────────────────────────────────────
# TOMATOES PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
TOM_POSITION_LIM = 20

# History / fair value
TOM_HISTORY_MAX = 250
TOM_FAIR_FAST = 20
TOM_FAIR_SLOW = 80
TOM_SIGMA_WINDOW = 20

# Inventory control
TOM_INV_PENALTY = 0.35

# Z-score thresholds
TOM_NEUTRAL_Z = 0.5
TOM_SKEW_Z = 1.0
TOM_EXTREME_Z = 1.5

# Order sizes
TOM_BASE_PASSIVE = 3
TOM_SKEW_PASSIVE = 5
TOM_EXTREME_PASSIVE = 7

# Quote placement
TOM_MIN_HALF_SPREAD = 2
TOM_MAKE_INSIDE_FRAC = 0.8

# Regime filter
TOM_TREND_WEIGHT = 0.25


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
    # TOMATOES — Passive Mean-Reversion MM + Inventory Skew + Trend Filter
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
        half_spread = max(TOM_MIN_HALF_SPREAD, spread / 2.0)

        # ---------------------------------------------------------------------
        # Update rolling price history
        # ---------------------------------------------------------------------
        history = mem.get("tom_history", [])
        history.append(mid)
        if len(history) > TOM_HISTORY_MAX:
            history = history[-TOM_HISTORY_MAX:]
        mem["tom_history"] = history

        # Need a bit of history before activating the full logic
        if len(history) < max(TOM_FAIR_FAST, TOM_SIGMA_WINDOW) + 1:
            # Bootstrap: very small passive quoting around current market
            boot_bid = best_bid + 1 if best_bid + 1 < best_ask else best_bid
            boot_ask = best_ask - 1 if best_ask - 1 > best_bid else best_ask

            if pos < TOM_POSITION_LIM:
                qty = min(2, TOM_POSITION_LIM - pos)
                if qty > 0:
                    orders.append(Order("TOMATOES", boot_bid, qty))

            if pos > -TOM_POSITION_LIM:
                qty = min(2, TOM_POSITION_LIM + pos)
                if qty > 0:
                    orders.append(Order("TOMATOES", boot_ask, -qty))

            return orders, mem

        # ---------------------------------------------------------------------
        # Fair value, sigma, z-score
        # ---------------------------------------------------------------------
        fair_fast = self._ema(history, TOM_FAIR_FAST)
        fair_slow = self._ema(history, TOM_FAIR_SLOW) if len(history) >= TOM_FAIR_SLOW else fair_fast

        sigma = self._rolling_std(history, TOM_SIGMA_WINDOW)
        sigma = max(sigma, 1.0)  # avoid overreacting when price is flat

        z = (mid - fair_fast) / sigma

        # ---------------------------------------------------------------------
        # Mild regime filter
        # If fast fair > slow fair, allow slightly more bullish quoting
        # If fast fair < slow fair, allow slightly more bearish quoting
        # ---------------------------------------------------------------------
        trend_signal = 0.0
        if fair_fast > fair_slow:
            trend_signal = TOM_TREND_WEIGHT
        elif fair_fast < fair_slow:
            trend_signal = -TOM_TREND_WEIGHT

        # ---------------------------------------------------------------------
        # Inventory-aware reservation price
        # Long inventory -> lower reservation price
        # Short inventory -> raise reservation price
        # Also include a mild trend adjustment
        # ---------------------------------------------------------------------
        reservation = fair_fast - TOM_INV_PENALTY * pos + trend_signal

        # ---------------------------------------------------------------------
        # Base passive quotes around reservation value
        # ---------------------------------------------------------------------
        raw_bid = reservation - TOM_MAKE_INSIDE_FRAC * half_spread
        raw_ask = reservation + TOM_MAKE_INSIDE_FRAC * half_spread

        my_bid = math.floor(raw_bid)
        my_ask = math.ceil(raw_ask)

        # Keep quotes sensible relative to market
        my_bid = min(my_bid, best_ask - 1)
        my_ask = max(my_ask, best_bid + 1)

        # Ensure non-crossing quotes
        if my_bid >= my_ask:
            mid_quote = int(round(reservation))
            my_bid = min(mid_quote - 1, best_ask - 1)
            my_ask = max(mid_quote + 1, best_bid + 1)

        # ---------------------------------------------------------------------
        # Decide quoting regime from z-score
        # ---------------------------------------------------------------------
        buy_size = TOM_BASE_PASSIVE
        sell_size = TOM_BASE_PASSIVE
        place_bid = True
        place_ask = True

        # Strong undervaluation -> lean hard to buy
        if z <= -TOM_EXTREME_Z:
            buy_size = TOM_EXTREME_PASSIVE
            sell_size = 1
            place_bid = True
            place_ask = False if pos <= 0 else True

            # Make bid slightly more competitive
            my_bid = min(best_bid + 1, best_ask - 1)

        # Moderate undervaluation -> buy skew
        elif z <= -TOM_SKEW_Z:
            buy_size = TOM_SKEW_PASSIVE
            sell_size = 2
            my_bid = min(max(my_bid, best_bid + 1), best_ask - 1)

        # Strong overvaluation -> lean hard to sell
        elif z >= TOM_EXTREME_Z:
            buy_size = 1
            sell_size = TOM_EXTREME_PASSIVE
            place_bid = False if pos >= 0 else True
            place_ask = True

            # Make ask slightly more competitive
            my_ask = max(best_ask - 1, best_bid + 1)

        # Moderate overvaluation -> sell skew
        elif z >= TOM_SKEW_Z:
            buy_size = 2
            sell_size = TOM_SKEW_PASSIVE
            my_ask = max(min(my_ask, best_ask - 1), best_bid + 1)

        # Neutral zone -> quote both sides normally
        elif abs(z) < TOM_NEUTRAL_Z:
            buy_size = TOM_BASE_PASSIVE
            sell_size = TOM_BASE_PASSIVE

        # ---------------------------------------------------------------------
        # Small inventory overrides
        # ---------------------------------------------------------------------
        if pos >= TOM_POSITION_LIM - 3:
            place_bid = False
            sell_size = max(sell_size, TOM_SKEW_PASSIVE)

        if pos <= -TOM_POSITION_LIM + 3:
            place_ask = False
            buy_size = max(buy_size, TOM_SKEW_PASSIVE)

        # ---------------------------------------------------------------------
        # Opportunistic aggressive fills only when price is far from fair
        # ---------------------------------------------------------------------
        if z <= -2.25 and pos < TOM_POSITION_LIM:
            take_qty = min(3, TOM_POSITION_LIM - pos)
            if take_qty > 0 and best_ask < fair_fast:
                orders.append(Order("TOMATOES", best_ask, take_qty))

        elif z >= 2.25 and pos > -TOM_POSITION_LIM:
            take_qty = min(3, TOM_POSITION_LIM + pos)
            if take_qty > 0 and best_bid > fair_fast:
                orders.append(Order("TOMATOES", best_bid, -take_qty))

        # ---------------------------------------------------------------------
        # Passive bid
        # ---------------------------------------------------------------------
        if place_bid and pos < TOM_POSITION_LIM:
            qty = min(buy_size, TOM_POSITION_LIM - pos)
            if qty > 0 and my_bid < best_ask:
                orders.append(Order("TOMATOES", my_bid, qty))

        # ---------------------------------------------------------------------
        # Passive ask
        # ---------------------------------------------------------------------
        if place_ask and pos > -TOM_POSITION_LIM:
            qty = min(sell_size, TOM_POSITION_LIM + pos)
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
        if len(prices) < window:
            window_prices = prices
        else:
            window_prices = prices[-window:]

        if not window_prices:
            return 1.0

        mean_val = sum(window_prices) / len(window_prices)
        var = sum((x - mean_val) ** 2 for x in window_prices) / len(window_prices)
        return math.sqrt(var)