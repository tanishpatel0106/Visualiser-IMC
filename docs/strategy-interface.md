# Strategy Interface

This document describes how to write trading strategies for the IMC Prosperity Trading Terminal. Strategies follow the Prosperity competition protocol so that code written for the competition can run unmodified inside the backtester.

---

## Table of Contents

- [Trader Class Interface](#trader-class-interface)
- [TradingState Object](#tradingstate-object)
- [OrderDepth Format](#orderdepth-format)
- [Order Object](#order-object)
- [Return Value](#return-value)
- [Example: Minimal Strategy](#example-minimal-strategy)
- [Example: Market Making Strategy](#example-market-making-strategy)
- [traderData Persistence](#traderdata-persistence)
- [Parameter Definition for Built-in Strategies](#parameter-definition-for-built-in-strategies)
- [Making a Strategy Compatible](#making-a-strategy-compatible)

---

## Trader Class Interface

Every strategy must be a Python class named `Trader` (for uploaded strategies) or any class that implements the following interface:

```python
class Trader:
    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        ...
```

The `run` method is called once per simulation tick. It receives the current market state and returns the strategy's orders, conversions, and persisted data.

The class is instantiated once at the start of the backtest. Between ticks, the only state that persists is whatever the strategy serializes into the `traderData` string.

---

## TradingState Object

The `TradingState` object passed to `run()` contains all the information available to the strategy at the current tick.

| Attribute | Type | Description |
|---|---|---|
| `timestamp` | `int` | Current simulation timestamp (monotonically increasing). |
| `traderData` | `str` | Opaque string the strategy returned on its **previous** call. Empty on the first call. |
| `listings` | `dict[str, Listing]` | Product listing metadata, keyed by product symbol. Each `Listing` has `symbol`, `product`, and `denomination` attributes. |
| `order_depths` | `dict[str, OrderDepth]` | Current order book depth for each product. See [OrderDepth Format](#orderdepth-format). |
| `own_trades` | `dict[str, list[Trade]]` | Strategy's own fills since the last call, keyed by product. |
| `market_trades` | `dict[str, list[Trade]]` | All other participants' trades since the last call, keyed by product. |
| `position` | `dict[str, int]` | Current net position per product. Positive means long, negative means short. |
| `observations` | `Observation` | Market observations container (currently empty; reserved for future enrichment). |

### Trade Object

Each element in `own_trades` and `market_trades` lists is a `Trade`:

| Attribute | Type | Description |
|---|---|---|
| `symbol` | `str` | Product symbol. |
| `price` | `float` | Execution price. |
| `quantity` | `int` | Trade quantity (always positive). |
| `buyer` | `str` | Buyer identifier. |
| `seller` | `str` | Seller identifier. |
| `timestamp` | `int` | Trade timestamp. |

---

## OrderDepth Format

The `OrderDepth` object represents the visible order book for a single product.

```python
class OrderDepth:
    buy_orders: dict[int, int]   # price -> positive volume
    sell_orders: dict[int, int]  # price -> negative volume
```

### Buy Orders (Bids)

`buy_orders` maps integer price levels to **positive** quantities.

```python
{
    9998: 15,   # 15 units bid at 9998
    9997: 20,   # 20 units bid at 9997
    9996: 10,   # 10 units bid at 9996
}
```

The best bid is `max(order_depth.buy_orders.keys())`.

### Sell Orders (Asks)

`sell_orders` maps integer price levels to **negative** quantities. This is the Prosperity convention: negative values indicate resting sell volume.

```python
{
    10002: -12,  # 12 units offered at 10002
    10003: -18,  # 18 units offered at 10003
    10004: -8,   # 8 units offered at 10004
}
```

The best ask is `min(order_depth.sell_orders.keys())`.

To get the absolute volume at an ask level: `abs(order_depth.sell_orders[price])`.

### Computing Mid Price

```python
best_bid = max(order_depth.buy_orders.keys())
best_ask = min(order_depth.sell_orders.keys())
mid_price = (best_bid + best_ask) / 2.0
```

---

## Order Object

Strategies submit orders by creating `Order` objects. The `Order` class is available at runtime from the sandbox adapter:

```python
from backend.app.engines.sandbox.adapter import Order

order = Order(symbol, price, quantity)
```

| Parameter | Type | Description |
|---|---|---|
| `symbol` | `str` | Product symbol (must match a key in `state.order_depths`). |
| `price` | `int` | Limit price. |
| `quantity` | `int` | **Positive** for buy, **negative** for sell. |

Examples:

```python
# Buy 10 units of AMETHYSTS at price 9998
Order("AMETHYSTS", 9998, 10)

# Sell 5 units of AMETHYSTS at price 10002
Order("AMETHYSTS", 10002, -5)
```

---

## Return Value

The `run` method must return a tuple of three values:

```python
return (result, conversions, traderData)
```

| Value | Type | Description |
|---|---|---|
| `result` | `dict[str, list[Order]]` | Maps each product symbol to a list of `Order` objects. Products not included are treated as having no orders. |
| `conversions` | `int` | Number of conversions to request (used in some Prosperity rounds). Use `0` if not applicable. |
| `traderData` | `str` | An arbitrary string that will be passed back as `state.traderData` on the next call. Use this to persist state between ticks. |

### Result Dict

The result dictionary must use product symbols as keys and lists of `Order` objects as values:

```python
result = {
    "AMETHYSTS": [
        Order("AMETHYSTS", 9998, 10),    # Buy 10 at 9998
        Order("AMETHYSTS", 10002, -10),   # Sell 10 at 10002
    ],
    "STARFRUIT": [
        Order("STARFRUIT", 5000, 5),      # Buy 5 at 5000
    ],
}
```

---

## Example: Minimal Strategy

A strategy that does nothing:

```python
class Trader:
    def run(self, state):
        result = {}
        for product in state.order_depths:
            result[product] = []
        return result, 0, ""
```

---

## Example: Market Making Strategy

A simple market maker that places buy and sell orders around the mid price:

```python
import json
import math


class Trader:
    def run(self, state):
        from backend.app.engines.sandbox.adapter import Order

        SPREAD = 4
        ORDER_SIZE = 10
        MAX_POSITION = 20

        # Load persisted state
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except json.JSONDecodeError:
                trader_data = {}

        total_trades = trader_data.get("total_trades", 0)
        result = {}

        for product in state.order_depths:
            orders = []
            order_depth = state.order_depths[product]

            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2.0

            position = state.position.get(product, 0)
            half_spread = SPREAD / 2.0

            bid_price = int(math.floor(mid_price - half_spread))
            ask_price = int(math.ceil(mid_price + half_spread))

            # Scale order size based on inventory
            buy_qty = min(ORDER_SIZE, max(0, MAX_POSITION - position))
            sell_qty = min(ORDER_SIZE, max(0, MAX_POSITION + position))

            if buy_qty > 0:
                orders.append(Order(product, bid_price, buy_qty))
                total_trades += 1

            if sell_qty > 0:
                orders.append(Order(product, ask_price, -sell_qty))
                total_trades += 1

            result[product] = orders

        trader_data["total_trades"] = total_trades
        return result, 0, json.dumps(trader_data)
```

This strategy:
1. Computes the mid price from the best bid and ask.
2. Places a buy order `SPREAD/2` below mid and a sell order `SPREAD/2` above mid.
3. Reduces order sizes as inventory approaches the position limit.
4. Persists a trade counter across ticks via `traderData`.

---

## traderData Persistence

The `traderData` mechanism is the **only** way to persist state between `run()` calls. The third element of the return tuple is saved and passed back as `state.traderData` on the next invocation.

### How It Works

1. On the first call, `state.traderData` is an empty string `""`.
2. At the end of `run()`, the strategy returns a string (typically JSON-serialized data).
3. On the next call, `state.traderData` contains exactly the string returned previously.

### Best Practices

- **Use JSON:** Serialize state as a JSON string for structured persistence.
- **Keep it small:** The string is stored in memory and passed through the system each tick. Avoid storing large datasets.
- **Handle initialization:** Always check if `state.traderData` is empty or invalid.
- **Store only what you need:** Rolling windows, running statistics, signal states, and configuration overrides.

### Example Pattern

```python
import json

class Trader:
    def run(self, state):
        # Load state
        data = {}
        if state.traderData:
            try:
                data = json.loads(state.traderData)
            except json.JSONDecodeError:
                data = {}

        # Read persisted values with defaults
        ema = data.get("ema", None)
        tick_count = data.get("tick_count", 0)

        # ... strategy logic ...

        tick_count += 1

        # Save state
        data["ema"] = ema
        data["tick_count"] = tick_count
        return result, 0, json.dumps(data)
```

---

## Parameter Definition for Built-in Strategies

Built-in strategies define their parameters as metadata in `StrategyDefinition` objects so the frontend can render appropriate input controls:

```python
StrategyDefinition(
    strategy_id="fixed_spread_maker",
    name="Fixed Spread Maker",
    category="market_making",
    description="Places buy and sell orders at a fixed spread around the mid price.",
    source_code=inspect.getsource(FixedSpreadMaker),
    parameters={
        "spread": {
            "type": "int",
            "default": 4,
            "description": "Total spread width",
        },
        "order_size": {
            "type": "int",
            "default": 10,
            "description": "Size of each order",
        },
        "max_position": {
            "type": "int",
            "default": 20,
            "description": "Maximum absolute position",
        },
    },
)
```

Each parameter entry has:

| Field | Type | Description |
|---|---|---|
| `type` | `str` | `"int"` or `"float"`. Determines the input widget. |
| `default` | `int` or `float` | Default value shown in the UI. |
| `description` | `str` | Tooltip and label text. |

Parameters are passed to the strategy via `traderData` as a JSON string. The strategy reads them from `state.traderData` on the first call and can override defaults with user-configured values.

---

## Making a Strategy Compatible

To make a strategy file uploadable and runnable in the terminal:

1. **Define a `Trader` class** at the module level. The sandbox scans for a class named `Trader`.

2. **Implement `run(self, state)`** accepting a `TradingState`-compatible object and returning the three-element tuple `(result, conversions, traderData)`.

3. **Import `Order` inside `run()`** to avoid import errors at load time:
   ```python
   def run(self, state):
       from backend.app.engines.sandbox.adapter import Order
       # ...
   ```

4. **Use `state.traderData` for all persistence.** Do not rely on instance variables surviving between calls in the competition environment. The terminal does preserve instances, but writing portable code via `traderData` is recommended.

5. **Handle empty order books gracefully.** Check that `buy_orders` and `sell_orders` are non-empty before computing prices.

6. **Respect position limits.** Use a helper to clamp order quantities:
   ```python
   def clamp_qty(desired, position, limit):
       if desired > 0:
           return max(0, min(desired, limit - position))
       elif desired < 0:
           return min(0, max(desired, -(limit + position)))
       return 0
   ```

7. **Keep execution fast.** Strategies have a configurable timeout (default 1 second). Avoid expensive computations or network calls.

8. **No external dependencies.** The sandbox provides `json`, `math`, `numpy`, and standard library modules. The `Order`, `OrderDepth`, `Trade`, and `TradingState` classes are available from the sandbox adapter.
