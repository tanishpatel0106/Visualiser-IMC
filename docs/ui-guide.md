# UI Guide

This document describes every panel and control in the IMC Prosperity Trading Terminal interface.

---

## Table of Contents

- [Terminal Layout Overview](#terminal-layout-overview)
- [Header Controls](#header-controls)
- [Order Book Panel](#order-book-panel)
- [Depth Chart Panel](#depth-chart-panel)
- [Chart Panel](#chart-panel)
- [Trade Tape Panel](#trade-tape-panel)
- [Strategy Panel](#strategy-panel)
- [Metrics Panel](#metrics-panel)
- [Debug Trace Panel](#debug-trace-panel)
- [Fills Panel](#fills-panel)
- [Positions Panel](#positions-panel)
- [Workspace Presets](#workspace-presets)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Tips for Efficient Workflow](#tips-for-efficient-workflow)

---

## Terminal Layout Overview

The terminal fills the full browser window and is organized into three vertical zones:

1. **Header bar** (top) -- Dataset and product selectors, replay transport controls, speed adjustment, workspace switcher.
2. **Main workspace** (center) -- Resizable panels arranged according to the active workspace preset.
3. **Status bar** (bottom) -- Version identifier, current workspace name, shortcut hints, and clock.

All panels support drag-to-resize via the handles between them. Each panel has a title bar identifying its content. The layout adapts based on the selected workspace preset.

---

## Header Controls

The header bar spans the full width of the terminal and provides top-level controls:

| Control | Description |
|---|---|
| **Dataset selector** | Dropdown to choose from loaded datasets. |
| **Product selector** | Dropdown to choose which product to display. Filters all panels to show data for the selected product. |
| **Day selector** | Choose which trading day within the dataset to view. |
| **Play / Pause** | Start or pause real-time replay of market data. |
| **Step Forward** | Advance one tick. |
| **Step Back** | Go back one tick. |
| **Reset** | Return to the first tick. |
| **Speed control** | Adjust replay speed (1x to 100x). |
| **Workspace switcher** | Buttons or tabs to switch between Trading, Analysis, Strategy, and Debug workspaces. |

---

## Order Book Panel

The order book panel displays a real-time ladder view of the current order book for the selected product.

### Ladder View

The ladder is a vertical price scale with bids (buy orders) on the left or bottom and asks (sell orders) on the right or top, centered around the current mid price.

| Element | Description |
|---|---|
| **Bid levels** | Displayed in green. Each row shows the price and the total volume resting at that price. Up to three levels of depth. |
| **Ask levels** | Displayed in red. Each row shows the price and the absolute volume offered at that price (the underlying data stores negative values; the display shows positive). |
| **Spread** | The gap between the best bid and best ask. Displayed numerically. |
| **Mid price** | The arithmetic mean of the best bid and best ask. |
| **Volume bars** | Horizontal bars proportional to the volume at each level, giving a visual sense of where liquidity is concentrated. |

The ladder updates on every replay tick or WebSocket message.

---

## Depth Chart Panel

The depth chart provides a cumulative visualization of the order book.

The horizontal axis represents price. The vertical axis represents cumulative volume. The bid side is plotted as a step function moving leftward from the best bid, accumulating volume at successively lower prices. The ask side mirrors this from the best ask moving rightward.

This view makes it easy to identify:

- **Thin liquidity:** Steep drops indicate that a small market order would cause significant price movement.
- **Thick support/resistance:** Flat plateaus indicate large resting volume at a price level.
- **Asymmetry:** If one side is much steeper, the book is imbalanced.

---

## Chart Panel

The main chart panel occupies the largest portion of the workspace and supports multiple visualization modes and indicator overlays.

### Chart Modes

| Mode | Description |
|---|---|
| **Candlestick** | Traditional OHLCV candlestick bars reconstructed from mid-price snapshots. Green for up bars, red for down bars. This is the default mode. |
| **OHLC** | Same data as candlestick but rendered as OHLC bar markers. |
| **Tick** | Plots every mid-price snapshot as a continuous line. Highest temporal resolution. |

Switch between modes using the chart mode selector in the panel header.

### Indicator Overlays

The following technical indicators can be overlaid on the price chart or shown in sub-panels:

| Indicator | Description |
|---|---|
| **SMA** | Simple Moving Average over a configurable period. |
| **EMA** | Exponential Moving Average. |
| **WMA** | Weighted (linear) Moving Average. |
| **HMA** | Hull Moving Average (reduced lag). |
| **VWAP** | Cumulative Volume-Weighted Average Price. |
| **Bollinger Bands** | Upper band, middle (SMA), and lower band based on standard deviation. |
| **RSI** | Relative Strength Index (sub-panel). |
| **MACD** | MACD line, signal line, and histogram (sub-panel). |
| **Rate of Change** | Percentage price change over N periods. |
| **Rolling Z-Score** | Standardized deviation from the rolling mean. |
| **Rolling Volatility** | Standard deviation of returns over a rolling window. |
| **ATR Proxy** | Average True Range approximation. |

Use the indicator selector (toggle buttons) in the chart panel header to add or remove overlays. Multiple indicators can be displayed simultaneously.

### Chart Interaction

- Hover over candles or data points to see exact values in a tooltip.
- Scroll to zoom in/out on the time axis.
- Click and drag to pan.
- The chart auto-scrolls during active replay to keep the latest data visible.

---

## Trade Tape Panel

The trade tape shows a chronological list of all market trades (trade prints) for the selected product and day.

| Column | Description |
|---|---|
| **Timestamp** | When the trade occurred. |
| **Price** | Execution price. |
| **Quantity** | Number of units traded. |
| **Buyer** | Buyer identifier. |
| **Seller** | Seller identifier. |

Trades are color-coded:
- Trades at or above the ask are typically green (buyer-initiated).
- Trades at or below the bid are typically red (seller-initiated).

The tape scrolls automatically as new trades appear during replay.

---

## Strategy Panel

The strategy panel is the command center for strategy selection, configuration, and execution.

### Strategy Library

Browse all available strategies organized by category:

- **Market Making** -- Fixed Spread, Inventory Skewed, Adaptive Spread, Reservation Price, Ladder
- **Mean Reversion** -- Mid Price, Bollinger Band, Z-Score, VWAP
- **Momentum** -- EMA Crossover, SMA Crossover, Breakout, Momentum, Trade Flow
- **Microstructure** -- Imbalance Follower, Spread Capture, Tradeburst Reaction

Click a strategy to select it and view its description and source code.

### Parameter Configuration

When a strategy is selected, its configurable parameters appear as input fields below the description. Each parameter has a name, type (integer or float), default value, and a description tooltip.

Modify parameters and click **Run** to execute a backtest with those settings.

Click **Reset** to return all parameters to their defaults.

### Upload

Click the **Upload** button to upload a custom `.py` strategy file. The file must contain a `Trader` class with a `run(self, state)` method. See [docs/strategy-interface.md](strategy-interface.md) for details.

After upload, the strategy appears in the panel and can be run immediately.

### Source Code Viewer

The source code of the selected strategy is displayed in a read-only code viewer, allowing inspection before running.

---

## Metrics Panel

The metrics panel displays quantitative performance results after a backtest run completes.

### Performance Metrics

| Metric | Description |
|---|---|
| **Total PnL** | Sum of realized and unrealized PnL. |
| **Realized PnL** | PnL from closed positions. |
| **Unrealized PnL** | Mark-to-market PnL from open positions. |
| **Total Fees** | Cumulative fees paid. |
| **Sharpe Ratio** | Risk-adjusted return (if enough data points). |
| **Max Drawdown** | Largest peak-to-trough PnL decline. |
| **Win Rate** | Percentage of profitable fills. |

### Execution Metrics

| Metric | Description |
|---|---|
| **Total Fills** | Number of fill events. |
| **Aggressive Fills** | Fills from orders that crossed the book. |
| **Passive Fills** | Fills from resting orders. |
| **Average Fill Price** | Weighted average across all fills. |
| **Fill Rate** | Percentage of submitted orders that filled. |

### PnL Chart

A time-series chart of cumulative PnL over the backtest duration, with realized and unrealized components.

---

## Debug Trace Panel

The debug trace panel shows a per-tick log of strategy execution, providing full transparency into what happened at each timestamp.

Each frame includes:

| Field | Description |
|---|---|
| **Timestamp** | The simulation tick. |
| **Orders submitted** | List of orders the strategy returned. |
| **Fills** | Any fills that occurred (aggressive or passive). |
| **Position** | Net position after this tick. |
| **PnL** | Running PnL at this tick. |
| **traderData** | The serialized state the strategy persisted. |
| **Book state** | Summary of the order book at this tick. |

Scroll through the trace to reconstruct the strategy's decision process at any point in time. This is invaluable for debugging unexpected behavior.

---

## Fills Panel

The fills panel shows a table of all fill events from the most recent backtest run.

| Column | Description |
|---|---|
| **Order ID** | Unique identifier for the parent order. |
| **Product** | Product symbol. |
| **Side** | BUY or SELL. |
| **Price** | Fill price (after fees and slippage). |
| **Quantity** | Number of units filled. |
| **Timestamp** | When the fill occurred. |
| **Aggressive** | Whether the fill was from an aggressive or passive order. |

Rows are color-coded: green for buys, red for sells.

---

## Positions Panel

The positions panel tracks the net position for each product across the backtest.

| Column | Description |
|---|---|
| **Product** | Product symbol. |
| **Position** | Current net position (positive = long, negative = short). |
| **Unrealized PnL** | Mark-to-market PnL on the open position. |
| **Realized PnL** | PnL from closed trades. |

The panel updates on each tick during replay and shows the final state after a backtest completes.

---

## Workspace Presets

Four workspace presets arrange the panels for different tasks:

### Trading (press `1`)

The default workspace for general market observation and strategy execution.

```
+-------------------+---------------------------+---------------+
|                   |                           |               |
|   Order Book      |       Price Chart         |   Strategy    |
|                   |                           |   Panel       |
|   Depth Chart     |                           |               |
|                   |                           |               |
+-------------------+---------------------------+---------------+
|  Trade Tape  |  Fills  |  Positions  |  Metrics  |  Debug     |
+-------------------------------------------------------------------+
```

### Analysis (press `2`)

Optimized for studying market data and backtest results.

```
+-------------------------------------------+---------------+
|                                           |               |
|              Price Chart                  |   Metrics     |
|              (large)                      |   Panel       |
|                                           |               |
+-------------------------------------------+---------------+
|  Trade Tape  |  Fills  |  Positions  |  Metrics  |  Debug     |
+-------------------------------------------------------------------+
```

### Strategy (press `3`)

Focused on strategy development and parameter tuning.

```
+--------------------+----------------------------------------------+
|                    |                                              |
|   Strategy Panel   |              Price Chart                     |
|   (wide)           |                                              |
|                    +----------------------------------------------+
|                    |  Trade Tape | Fills | Positions | Metrics    |
+--------------------+----------------------------------------------+
```

### Debug (press `4`)

Focused on diagnosing strategy behavior tick by tick.

```
+-------------------+----------------------------------------------+
|                   |                                              |
|   Order Book      |              Price Chart                     |
|                   |                                              |
+-------------------+----------------------------------------------+
|                                          |   Positions           |
|         Debug Trace (large)              +-----------------------+
|                                          |   Fills               |
+------------------------------------------+-----------------------+
```

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Space` | Toggle play/pause for replay. |
| `Right Arrow` | Step forward one tick. |
| `Shift + Right Arrow` | Seek forward 10 ticks. |
| `Left Arrow` | Step backward one tick. |
| `Shift + Left Arrow` | Seek backward 10 ticks. |
| `R` | Reset replay to the beginning. |
| `1` | Switch to Trading workspace. |
| `2` | Switch to Analysis workspace. |
| `3` | Switch to Strategy workspace. |
| `4` | Switch to Debug workspace. |

All shortcuts are disabled when focus is inside a text input, textarea, or select element to avoid conflicts with typing.

---

## Tips for Efficient Workflow

1. **Start with the Trading workspace** to get oriented with a new dataset. Check the order book behavior, trade flow, and price action before running any strategy.

2. **Use keyboard shortcuts** for replay control. Stepping through data tick by tick with arrow keys is the fastest way to understand market microstructure.

3. **Step through slowly at key moments.** When investigating a fill or position change, step backward and forward around the event to understand the book state before and after.

4. **Compare execution models.** Run the same strategy three times with Conservative, Balanced, and Optimistic models. If results differ dramatically, the strategy depends heavily on passive fill assumptions.

5. **Use the Debug workspace** after a backtest to inspect the strategy's decision at each tick. The debug trace shows exactly what orders were placed and what traderData the strategy persisted.

6. **Layer indicators.** Add Bollinger Bands or moving averages to the chart before running a mean-reversion or momentum strategy. Seeing the indicator values alongside the strategy's behavior builds intuition.

7. **Resize panels as needed.** Drag the handles between panels to allocate more space to the panel you are actively using. The layout remembers proportions within a session.

8. **Use the Analysis workspace for post-backtest review.** The large chart and metrics sidebar make it easy to study PnL curves and identify periods of strong or weak performance.

9. **Upload strategies iteratively.** Make a change to your strategy file, re-upload, and re-run. The terminal preserves the selected parameters so you can focus on code changes.

10. **Check the status bar.** The bottom bar shows the current workspace and available shortcuts as a quick reference.
