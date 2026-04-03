"""Simple Market Maker - Example Strategy for IMC Prosperity Trading Terminal.

This is a standalone strategy file that can be uploaded to the sandbox.
It places buy and sell orders around the mid price with a fixed spread,
adjusting order sizes based on current inventory to manage risk.

Usage: Upload this file to the strategy sandbox. The Trader class will
be automatically detected and used.
"""

import json
import math


class Trader:
    """A simple market maker that quotes around the mid price.

    Maintains a fixed spread and reduces order sizes as inventory
    approaches the position limit.
    """

    def run(self, state):
        # Import Order from the sandbox adapter (available at runtime)
        from backend.app.engines.sandbox.adapter import Order

        # --- Configuration ---
        SPREAD = 4
        ORDER_SIZE = 10
        MAX_POSITION = 20

        # --- Load persisted state ---
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except json.JSONDecodeError:
                trader_data = {}

        total_trades = trader_data.get("total_trades", 0)

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

            # Current position
            position = state.position.get(product, 0)

            # Calculate quote prices
            half_spread = SPREAD / 2.0
            bid_price = int(math.floor(mid_price - half_spread))
            ask_price = int(math.ceil(mid_price + half_spread))

            # Scale order size based on inventory
            # Reduce buy size when long, reduce sell size when short
            buy_room = MAX_POSITION - position
            sell_room = MAX_POSITION + position

            buy_qty = min(ORDER_SIZE, max(0, buy_room))
            sell_qty = min(ORDER_SIZE, max(0, sell_room))

            if buy_qty > 0:
                orders.append(Order(product, bid_price, buy_qty))
                total_trades += 1

            if sell_qty > 0:
                orders.append(Order(product, ask_price, -sell_qty))
                total_trades += 1

            result[product] = orders

        # --- Persist state ---
        trader_data["total_trades"] = total_trades
        trader_data_str = json.dumps(trader_data)

        return result, 0, trader_data_str
