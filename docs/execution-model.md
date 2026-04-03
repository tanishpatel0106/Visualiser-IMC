# Execution Model

This document explains how the trading terminal simulates order execution against historical market data, why the execution model matters, and how to choose between the three available modes.

---

## Table of Contents

- [Why Execution Modeling Matters](#why-execution-modeling-matters)
- [Snapshot Data vs Full Exchange Feed](#snapshot-data-vs-full-exchange-feed)
- [Three Execution Models](#three-execution-models)
  - [Conservative](#conservative)
  - [Balanced](#balanced)
  - [Optimistic](#optimistic)
- [Aggressive Order Execution](#aggressive-order-execution)
- [Passive Order Execution](#passive-order-execution)
- [Position Limits and Risk Controls](#position-limits-and-risk-controls)
- [Fee and Slippage Configuration](#fee-and-slippage-configuration)
- [Queue Position Modeling](#queue-position-modeling)
- [Fill Assumptions and Limitations](#fill-assumptions-and-limitations)
- [How to Choose Between Models](#how-to-choose-between-models)

---

## Why Execution Modeling Matters

Backtesting a trading strategy requires answering a fundamental question: **would this order have been filled?**

For aggressive orders that cross the visible book, the answer is straightforward -- they consume posted liquidity and fill at the displayed prices. But for passive orders that rest in the book waiting for a counterparty, the answer depends on information that snapshot data does not provide: the exact order queue, the timing of incoming orders, and whether any market participant actually traded at that price level.

Different assumptions about passive fill behavior can dramatically change backtest results. A market-making strategy may appear highly profitable under optimistic fill assumptions but barely break even under conservative ones. Understanding and selecting the right execution model is essential for producing trustworthy backtest results.

---

## Snapshot Data vs Full Exchange Feed

The IMC Prosperity competition provides market data as **periodic snapshots** of the order book rather than a continuous event stream.

### What the data provides

- Order book state at each snapshot: best 1-3 price levels on each side with volumes.
- Trade prints that occurred between snapshots: price, quantity, buyer, seller.
- Mid price at each snapshot.

### What the data does not provide

- **Order queue position:** There is no way to know where a resting order would sit in the queue at a given price level. Multiple participants may have rested orders at the same price before yours.
- **Exact timing of fills:** Between two snapshots, multiple trades may have occurred. The order in which they happened is unknown.
- **Full depth beyond 3 levels:** Liquidity deeper than the visible book is unobserved.
- **Order cancellations and modifications:** Whether resting orders were pulled and replaced between snapshots is unknown.

These gaps mean that any execution simulation is necessarily an approximation. The three execution models represent different points on the optimism spectrum.

---

## Three Execution Models

### Conservative

**Philosophy:** Only fill passive orders when there is concrete evidence that liquidity was taken at the resting price.

**Rule:** A resting buy order at price P fills only when a trade print exists with `trade.price <= P`. A resting sell order at price P fills only when a trade print exists with `trade.price >= P`. The fill quantity is capped at the total volume of qualifying trade prints.

**Rationale:** Trade prints are the most reliable evidence that a transaction occurred at a price level. By requiring actual trade evidence, this model avoids phantom fills where the price may have touched a level but no execution actually happened.

**Behavior:**
- Passive buy at 9998 and a trade prints at 9997 with quantity 5 --> fills up to 5 units.
- Passive buy at 9998 and best ask drops to 9998 but no trades print --> no fill.
- Multiple qualifying trades are summed to determine available fill volume.

### Balanced

**Philosophy:** Use trade evidence when available, supplemented by book-movement heuristics.

**Rule:** A resting order fills if **either** of the following conditions holds:
1. A trade print occurs at or through the resting price (identical to conservative).
2. The opposing best quote has moved through the resting price, indicating the level was consumed.

For condition (2), the full remaining quantity fills because the price level was clearly traded through.

**Rationale:** When the best ask drops from 10002 to 9997, the 9998 level was necessarily traded through by other participants (or swept by a large incoming order). This heuristic captures fills that the conservative model would miss due to sparse trade-print data.

**Behavior:**
- Passive buy at 9998 and best ask moves from 10000 to 9997 --> full fill (level was consumed).
- Passive buy at 9998 and best ask stays at 10000 with no qualifying trades --> no fill.
- Trade evidence is checked first; book movement is the fallback.

### Optimistic

**Philosophy:** Fill whenever the market price touches the resting level.

**Rule:** A resting buy fills if `best_ask <= resting_price`. A resting sell fills if `best_bid >= resting_price`. The full remaining quantity fills.

**Rationale:** Provides an upper bound on fill probability. Every scenario where the price reaches the resting level is assumed to result in a fill, regardless of queue position or actual trade activity.

**Behavior:**
- Passive buy at 9998 and best ask is 9998 --> full fill.
- Passive buy at 9998 and best ask is 9999 --> no fill.
- No trade evidence is required.

---

## Aggressive Order Execution

Aggressive orders are those that cross the current best quote:

- A **buy** order is aggressive when its limit price >= the best ask.
- A **sell** order is aggressive when its limit price <= the best bid.
- **Market orders** are always aggressive.

Aggressive orders are handled identically across all three execution models. The execution engine walks through the visible book levels consuming liquidity:

1. For a buy order, iterate through ask levels from lowest (best) to highest.
2. For a sell order, iterate through bid levels from highest (best) to lowest.
3. At each level, fill up to the available volume, respecting the order's limit price.
4. Slippage is added to each fill price (see [Fee and Slippage Configuration](#fee-and-slippage-configuration)).
5. If the order is partially filled and is a limit order, the remainder rests passively.
6. If the order is a market order and gets no fills, it is rejected.

**Example:** A buy order for 25 units at price 10005 against this ask side:

| Ask Price | Volume |
|---|---|
| 10002 | 12 |
| 10003 | 18 |
| 10004 | 8 |

Fills: 12 at 10002, then 13 at 10003. Total filled: 25. The 10003 level has 5 units remaining.

---

## Passive Order Execution

Passive orders are those that do not cross the current book:

- A **buy** order is passive when its limit price < the best ask.
- A **sell** order is passive when its limit price > the best bid.

When a passive order is submitted, it is placed on the engine's internal resting book. At each subsequent tick, the engine evaluates all resting orders against the new market state using the selected execution model (see [Three Execution Models](#three-execution-models) above).

The evaluation flow:

1. For each resting order, check if the fill conditions are met per the active model.
2. Compute the fill quantity (may be partial under the conservative model).
3. Generate fill events at the resting order's limit price (not at the market price).
4. Apply fees to the fill price.
5. Update the order state (partial fill or fully filled).
6. Remove fully filled orders from the resting book.

---

## Position Limits and Risk Controls

The execution engine enforces position limits per product. Before processing any order, it checks whether filling the entire order quantity would cause the net position to exceed the configured limit.

```
projected_position = current_position + order_quantity  (for buys)
projected_position = current_position - order_quantity  (for sells)

if abs(projected_position) > position_limit:
    REJECT the order
```

Position limits are configured per product in the `BacktestConfig`:

```json
{
  "position_limits": {
    "AMETHYSTS": 20,
    "STARFRUIT": 20
  }
}
```

The default position limit is 20 (configurable via `IMC_DEFAULT_POSITION_LIMIT`).

Orders that would breach the limit are rejected with status `REJECTED`. The strategy is responsible for tracking its own position and sizing orders to stay within limits.

---

## Fee and Slippage Configuration

### Fees

A per-unit fee is applied to every fill, making the effective price worse for the trader:

- **Buy fills:** effective price = fill price + fee
- **Sell fills:** effective price = fill price - fee

Fees apply to both aggressive and passive fills.

### Slippage

An additional per-unit adverse price adjustment applied only to **aggressive** fills:

- **Buy fills:** effective price = fill price + slippage
- **Sell fills:** effective price = fill price - slippage

Slippage models the market impact and price movement that occurs when consuming liquidity.

### Configuration

Both are set in the backtest configuration:

```json
{
  "fees": 0.0,
  "slippage": 0.0
}
```

Set to `0.0` by default. Increasing these values produces more conservative PnL estimates.

---

## Queue Position Modeling

The terminal does **not** model explicit queue position. In a real exchange, passive orders at the same price level are filled in FIFO (first-in, first-out) order. Since the snapshot data does not reveal the order queue, the engine makes simplifying assumptions:

- **Conservative model:** Queue position is implicitly modeled by capping fill quantity at the observed trade volume through the resting price. If 5 units traded at your price, you can fill at most 5 units, regardless of your order size.
- **Balanced model:** When using the book-movement heuristic (condition b), the full remaining quantity fills because the entire level was consumed.
- **Optimistic model:** No queue modeling. Touching the price level fills the full order.

This is a significant limitation. In practice, a resting order at a popular price level (e.g., fair value) would be deep in the queue and might not fill even if trades occur at that price. The conservative model partially accounts for this; the others do not.

---

## Fill Assumptions and Limitations

### What is modeled

- Aggressive fills against visible book levels with price-level granularity.
- Passive fills based on configurable evidence requirements.
- Position limit enforcement before order acceptance.
- Per-unit fees and slippage.
- Partial fills when available volume is less than order quantity.
- Weighted-average fill prices across multiple levels (aggressive) and multiple partial fills (passive).

### What is not modeled

- **Queue priority:** No FIFO queue simulation within a price level.
- **Market impact:** Aggressive fills do not cause the book to replenish or move. The book state comes from the next snapshot.
- **Self-trade prevention:** The engine does not check whether a resting order would be filled by the strategy's own aggressive order.
- **Inter-snapshot dynamics:** All fills within a tick happen atomically against the snapshot state.
- **Hidden liquidity:** Iceberg orders and dark pools are not represented.
- **Latency:** Orders are assumed to arrive and be processed instantaneously.

---

## How to Choose Between Models

### For strategy development and comparison

Use **Balanced** (the default). It provides a reasonable middle ground that captures most legitimate fills without being overly generous. Most strategies should be evaluated here first.

### For risk assessment and production readiness

Use **Conservative**. If a strategy is profitable under conservative fill assumptions, it is more likely to be robust in live trading. This should be the bar for deciding whether to deploy a strategy.

### For upper-bound analysis

Use **Optimistic**. This shows the theoretical best case for a strategy. Useful for determining the maximum potential of an approach before investing effort in refinement.

### Confidence interval approach

Run the same strategy under all three models. The resulting PnL range gives a confidence interval:

| Model | PnL | Interpretation |
|---|---|---|
| Conservative | +$50 | Floor: minimum expected performance |
| Balanced | +$120 | Baseline: expected performance |
| Optimistic | +$200 | Ceiling: maximum expected performance |

If the conservative result is negative while the optimistic result is positive, the strategy's profitability depends heavily on fill assumptions and may not be reliable.

### Model selection by strategy type

| Strategy Type | Recommended Model | Reason |
|---|---|---|
| Aggressive execution (crosses the book) | Any (fills are identical) | Aggressive fills are model-independent. |
| Market making (passive quotes) | Conservative or Balanced | Passive fill rate is the primary driver of PnL. |
| Mean reversion (aggressive entries, passive exits) | Balanced | Mixed fill types; balanced captures the reasonable case. |
| Momentum (aggressive entries and exits) | Any | Primarily aggressive execution. |
