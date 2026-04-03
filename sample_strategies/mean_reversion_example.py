"""Mean Reversion Example - Strategy for IMC Prosperity Trading Terminal.

This is a standalone strategy file that can be uploaded to the sandbox.
It tracks a rolling average of the mid price and trades when the price
deviates significantly, betting on reversion to the mean.

Usage: Upload this file to the strategy sandbox. The Trader class will
be automatically detected and used.
"""

import json
import math


class Trader:
    """Mean reversion strategy using a rolling average and z-score signals.

    Buys when the price drops significantly below the rolling mean,
    sells when it rises significantly above. Unwinds positions as
    the price returns toward the mean.
    """

    def run(self, state):
        # Import Order from the sandbox adapter (available at runtime)
        from backend.app.engines.sandbox.adapter import Order

        # --- Configuration ---
        WINDOW = 20           # Rolling window size
        ENTRY_Z = 2.0         # Z-score to enter a trade
        EXIT_Z = 0.5          # Z-score to exit a trade
        ORDER_SIZE = 10       # Base order size
        MAX_POSITION = 20     # Maximum absolute position

        # --- Load persisted state ---
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except json.JSONDecodeError:
                trader_data = {}

        # Per-product price history
        price_history = trader_data.get("price_history", {})

        # --- Generate orders for each product ---
        result = {}

        for product in state.order_depths:
            orders = []
            order_depth = state.order_depths[product]

            # Calculate mid price
            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2.0

            # Update rolling price history
            history = price_history.get(product, [])
            history.append(mid_price)
            if len(history) > WINDOW:
                history = history[-WINDOW:]
            price_history[product] = history

            # Need a full window before generating signals
            if len(history) < WINDOW:
                result[product] = orders
                continue

            # Compute rolling mean and standard deviation
            mean = sum(history) / len(history)
            variance = sum((p - mean) ** 2 for p in history) / len(history)
            std = math.sqrt(variance) if variance > 0 else 0.001

            # Z-score of current price
            z_score = (mid_price - mean) / std

            # Current position
            position = state.position.get(product, 0)

            if z_score > ENTRY_Z:
                # Price is high relative to mean -> sell (expect drop)
                room = MAX_POSITION + position  # room to sell
                qty = min(ORDER_SIZE, max(0, room))
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))

            elif z_score < -ENTRY_Z:
                # Price is low relative to mean -> buy (expect rise)
                room = MAX_POSITION - position  # room to buy
                qty = min(ORDER_SIZE, max(0, room))
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))

            elif abs(z_score) < EXIT_Z and position != 0:
                # Price near the mean, unwind existing position
                if position > 0:
                    # Sell to reduce long position
                    qty = min(position, ORDER_SIZE)
                    orders.append(Order(product, best_bid, -qty))
                else:
                    # Buy to reduce short position
                    qty = min(-position, ORDER_SIZE)
                    orders.append(Order(product, best_ask, qty))

            result[product] = orders

        # --- Persist state ---
        trader_data["price_history"] = price_history
        trader_data_str = json.dumps(trader_data)

        return result, 0, trader_data_str
