# IMC Prosperity Trading Terminal

A professional-grade trading terminal and research platform for the IMC Prosperity algorithmic trading competition. Replay historical market data tick by tick, develop and backtest trading strategies against realistic order book snapshots, and analyze performance with an interactive multi-panel workspace.

Built with a Python FastAPI backend for data processing, strategy execution, and backtesting, and a React TypeScript frontend delivering a Bloomberg-style terminal interface with resizable panels, real-time WebSocket updates, and keyboard-driven navigation.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Terminal Workspace](#terminal-workspace)
- [Quick Start](#quick-start)
- [Loading Sample Data](#loading-sample-data)
- [Uploading a Custom Strategy](#uploading-a-custom-strategy)
- [Running a Built-in Strategy](#running-a-built-in-strategy)
- [Built-in Strategy Library](#built-in-strategy-library)
- [Execution Models](#execution-models)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Workspace Presets](#workspace-presets)
- [Data Format](#data-format)
- [Limitations](#limitations)
- [How to Extend](#how-to-extend)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [License](#license)

---

## Architecture Overview

```
+---------------------+       HTTP / WS        +---------------------+
|                     |  <------------------->  |                     |
|   React Frontend    |   REST API + WebSocket  |   FastAPI Backend   |
|   (TypeScript)      |                         |   (Python)          |
|                     |                         |                     |
|  - Zustand stores   |                         |  - Data loader      |
|  - Resizable panels |                         |  - Replay engine    |
|  - Lightweight      |                         |  - Execution engine |
|    Charts           |                         |  - Backtest engine  |
|  - WebSocket client |                         |  - Sandbox runner   |
|                     |                         |  - Strategy registry|
+---------------------+                         |  - Analytics        |
                                                +---------------------+
                                                         |
                                                    SQLite Storage
                                                    + CSV Data Files
```

The **backend** exposes a REST API under `/api` with routers for datasets, replay, backtest, strategies, and a WebSocket endpoint at `/api/ws/replay` for streaming real-time replay state to the frontend.

The **frontend** connects to the backend via HTTP for commands (load data, run backtest, fetch metrics) and via WebSocket for live replay updates (order book, trades, positions, PnL).

---

## Terminal Workspace

The interface is organized as a multi-panel terminal with four switchable workspace layouts:

**Trading Workspace (default):** Left column shows the order book ladder and depth chart. The center holds the main price chart (tick, OHLC, or candlestick mode with indicator overlays). Right column displays the strategy panel. A tabbed bottom section contains the trade tape, fills, positions, metrics, and debug trace.

**Analysis Workspace:** Emphasizes the chart and metrics panels side by side, with the tabbed bottom section for detailed data review.

**Strategy Workspace:** Gives the strategy panel a wide left column for browsing the library, configuring parameters, and uploading custom code. The right side shows the chart and bottom tabs.

**Debug Workspace:** Splits the view between the order book and chart in the top half, and a large debug trace panel alongside positions and fills in the bottom half.

All panels are resizable via drag handles. A status bar at the bottom shows the current workspace name, version, and shortcut hints.

---

## Quick Start

### Prerequisites

- Python 3.11 or later
- Node.js 18 or later
- npm (comes with Node.js)

### Backend Setup

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

The backend starts on `http://localhost:8000` by default.

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

The frontend starts on `http://localhost:5173` by default.

### Open the Terminal

Navigate to **http://localhost:5173** in your browser. The terminal will connect to the backend automatically and load sample data on startup.

---

## Loading Sample Data

### Automatic Loading

On startup, the backend scans the `sample_data/` directory for CSV files matching the naming convention `prices_round_{N}_day_{D}.csv` and `trades_round_{N}_day_{D}.csv`. Any discovered files are parsed and loaded into the in-memory data store automatically.

The included sample data covers Round 0 with two days of price snapshots and trade prints.

### Manual Loading via API

To load or reload a dataset directory:

```bash
curl -X POST http://localhost:8000/api/datasets/load
```

You can also point to a different directory by setting the `IMC_DATA_DIRECTORY` environment variable before starting the backend.

---

## Uploading a Custom Strategy

### Via the UI

1. Switch to the **Strategy** workspace (press `3`) or use the strategy panel in the Trading workspace.
2. Click the **Upload** button.
3. Select a `.py` file containing a `Trader` class with a `run(self, state)` method.
4. The strategy appears in the panel and can be run immediately.

### Via the API

```bash
curl -X POST http://localhost:8000/api/strategies/upload \
  -F "file=@my_strategy.py"
```

The uploaded file is validated to ensure it contains a compatible `Trader` class. See [docs/strategy-interface.md](docs/strategy-interface.md) for the expected interface.

---

## Running a Built-in Strategy

1. Open the **Strategy** panel (visible in the Trading and Strategy workspaces).
2. Browse the strategy library organized by category (Market Making, Mean Reversion, Momentum, Microstructure).
3. Select a strategy to view its description and configurable parameters.
4. Adjust parameters as needed (spread, order size, position limits, thresholds, and so on).
5. Click **Run** to execute a backtest against the loaded dataset.
6. Results appear in the Metrics, Fills, and Debug Trace tabs at the bottom of the terminal.

You can also run a strategy programmatically:

```bash
curl -X POST http://localhost:8000/api/strategies/fixed_spread_maker/run \
  -H "Content-Type: application/json" \
  -d '{"spread": 4, "order_size": 10, "max_position": 20}'
```

---

## Built-in Strategy Library

### Market Making

| Strategy | Description |
|---|---|
| **Fixed Spread Maker** | Places buy and sell orders at a fixed spread around the mid price. Simple and predictable baseline. |
| **Inventory Skewed Maker** | Adjusts quotes based on current inventory. Skews price away from accumulated position to reduce risk. |
| **Adaptive Spread Maker** | Widens spread during high volatility, tightens during low volatility. Tracks rolling mid prices for estimation. |
| **Reservation Price Maker** | Avellaneda-Stoikov inspired. Computes a reservation price based on inventory risk and sets mathematically optimal spread. |
| **Ladder Maker** | Places multiple orders at different price levels around fair value, creating a ladder of liquidity on both sides. |

### Mean Reversion

| Strategy | Description |
|---|---|
| **Mid Price Mean Reversion** | Trades when the mid price deviates from its rolling mean by a configurable number of standard deviations. |
| **Bollinger Band Reversion** | Buys at the lower Bollinger Band and sells at the upper band, unwinding positions near the mean. |
| **Z-Score Reversion** | Trades based on the z-score of the current price relative to its rolling mean. |
| **VWAP Reversion** | Reverts to the Volume-Weighted Average Price computed from trade data. Buys below VWAP, sells above it. |

### Momentum

| Strategy | Description |
|---|---|
| **EMA Crossover** | Buys when the fast EMA crosses above the slow EMA and sells on the reverse crossover. |
| **SMA Crossover** | Buys when the fast SMA crosses above the slow SMA and sells on the reverse crossover. |
| **Breakout Strategy** | Buys on new highs over a lookback window, sells on new lows. |
| **Momentum Strategy** | Trades based on rolling return momentum over a lookback window. |
| **Trade Flow Momentum** | Follows the net trade flow direction. Buys on net buying pressure, sells on net selling pressure. |

### Microstructure

| Strategy | Description |
|---|---|
| **Imbalance Follower** | Trades in the direction of order book imbalance. Buys when bids dominate, sells when asks dominate. |
| **Spread Capture** | Places passive orders to capture the bid-ask spread. Only participates when spread is wide enough. |
| **Tradeburst Reaction** | Detects bursts of trades and follows the direction of the net volume. |

---

## Execution Models

Because Prosperity data consists of periodic order book **snapshots** rather than a continuous event stream, the terminal must model how passive (resting) orders would be filled. Three execution models govern this assumption:

### Conservative

Only aggressive fills are guaranteed. A passive order fills **only** when an actual trade print exists at a price equal to or better than the resting price. This requires concrete evidence that liquidity was taken at that level. Fill quantity is capped at the total volume of qualifying trade prints.

This is the most realistic model and should be the default for strategy evaluation.

### Balanced

Passive fills use trade-flow evidence **plus** book-movement heuristics. A resting order fills if (a) a trade print occurs at or through the price (same as conservative), **or** (b) the opposing best quote has moved through the resting price, suggesting the level was consumed by other participants.

This is the default execution model and provides a reasonable middle ground.

### Optimistic

A passive order fills whenever the market price merely **touches** the resting level, regardless of actual trade evidence. This overstates fill probability and is useful only as an upper-bound estimate. Strategies that look profitable under optimistic execution but not under conservative execution are likely not robust.

### Why This Matters

Snapshot-based data does not reveal the full order queue, actual fill priority, or exact moment when liquidity is taken. Any backtest result should be interpreted relative to the execution model chosen. Running the same strategy under all three models gives a confidence interval on real-world performance.

See [docs/execution-model.md](docs/execution-model.md) for a detailed treatment.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Space` | Play / Pause replay |
| `Right Arrow` | Step forward one tick |
| `Shift + Right Arrow` | Seek forward 10 ticks |
| `Left Arrow` | Step backward one tick |
| `Shift + Left Arrow` | Seek backward 10 ticks |
| `R` | Reset replay to beginning |
| `1` | Switch to Trading workspace |
| `2` | Switch to Analysis workspace |
| `3` | Switch to Strategy workspace |
| `4` | Switch to Debug workspace |

Shortcuts are disabled when focus is inside an input field, textarea, or select element.

---

## Workspace Presets

| Preset | Key | Focus |
|---|---|---|
| **Trading** | `1` | Order book, chart, strategy panel, and tabbed bottom (trade tape, fills, positions, metrics, debug) |
| **Analysis** | `2` | Large chart with metrics sidebar and tabbed bottom |
| **Strategy** | `3` | Wide strategy panel with chart and tabbed bottom |
| **Debug** | `4` | Order book and chart on top; debug trace, positions, and fills on bottom |

---

## Data Format

### Price Snapshots CSV

File naming: `prices_round_{N}_day_{D}.csv`

Delimiter: semicolon (`;`) preferred; comma fallback is supported.

**Required columns:**

| Column | Type | Description |
|---|---|---|
| `day` | int | Trading day identifier |
| `timestamp` | int | Tick timestamp |
| `product` | str | Product symbol (e.g., `AMETHYSTS`, `STARFRUIT`) |
| `bid_price_1` | float | Best bid price |
| `bid_volume_1` | int | Volume at best bid |
| `ask_price_1` | float | Best ask price |
| `ask_volume_1` | int | Volume at best ask |
| `mid_price` | float | Mid price |

**Optional columns:**

| Column | Type | Description |
|---|---|---|
| `bid_price_2`, `bid_volume_2` | float, int | Second-level bid |
| `bid_price_3`, `bid_volume_3` | float, int | Third-level bid |
| `ask_price_2`, `ask_volume_2` | float, int | Second-level ask |
| `ask_price_3`, `ask_volume_3` | float, int | Third-level ask |
| `profit_and_loss` | float | Cumulative PnL at this snapshot |

### Trade Prints CSV

File naming: `trades_round_{N}_day_{D}.csv`

Delimiter: semicolon (`;`) preferred; comma fallback is supported.

**Required columns:**

| Column | Type | Description |
|---|---|---|
| `timestamp` | int | Trade timestamp |
| `buyer` | str | Buyer identifier |
| `seller` | str | Seller identifier |
| `symbol` | str | Product symbol |
| `currency` | str | Currency denomination |
| `price` | float | Trade price |
| `quantity` | int | Trade quantity |

---

## Limitations

- **Snapshot-based data:** The source data provides periodic order book snapshots, not a full Level 3 (order-by-order) feed. Events between snapshots are unobserved.
- **Reconstructed OHLCV:** Candlestick bars are constructed from mid-price snapshots, not from actual tick-by-tick trade prices. This introduces approximation.
- **Modeled queue position:** The execution engine cannot determine actual queue priority for passive orders. Fill assumptions are governed by the selected execution model and may not reflect real exchange behavior.
- **No partial book visibility:** Only up to three levels of depth are available per side, as provided in the source CSV. Deeper liquidity is unknown.
- **Strategy timeout:** User-uploaded strategies are subject to a configurable execution timeout (default 1 second per call) for safety.

---

## How to Extend

### Adding a New Product

Products are discovered automatically from the `product` column in price CSV files and the `symbol` column in trade CSV files. To add a new product, include it in your data files and reload the dataset.

### Adding a New Round

Follow the naming convention `prices_round_{N}_day_{D}.csv` and `trades_round_{N}_day_{D}.csv`, place the files in the data directory, and reload.

### Adding a Built-in Strategy

1. Create a new class in the appropriate category module under `backend/app/engines/strategies/` (e.g., `market_making.py` for a market-making strategy).
2. Implement a `run(self, state)` method following the Prosperity interface (see [docs/strategy-interface.md](docs/strategy-interface.md)).
3. Add a `StrategyDefinition` entry to the module's `STRATEGY_DEFINITIONS` list with an ID, name, category, description, source code, and parameter metadata.
4. The strategy registry auto-discovers definitions on startup.

### Adding a New Indicator

Add a static method to `backend/app/engines/analytics/indicators.py` in the `TechnicalIndicators` class. The method should accept a list of values and return a list of the same length with `None` for positions where the indicator cannot yet be computed.

### Adding a New Data Adapter

Create a new loader class following the pattern in `backend/app/engines/data/loader.py`. Implement `discover_datasets`, schema validation, and a `load_*_csv` method. Wire it into the dataset service.

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Framework | FastAPI 0.109 |
| Server | Uvicorn 0.27 |
| Validation | Pydantic 2.5 |
| Configuration | pydantic-settings 2.1 |
| Data Processing | pandas 2.1, NumPy 1.26 |
| WebSocket | websockets 12.0 |
| File Uploads | python-multipart 0.0.6 |
| Async Files | aiofiles 23.2 |
| Testing | pytest 7.4, pytest-asyncio 0.23, httpx 0.26 |

### Frontend

| Component | Technology |
|---|---|
| UI Library | React 18.2 |
| Language | TypeScript 5.2 |
| Build Tool | Vite 5.0 |
| State Management | Zustand 4.4 |
| Charting | Lightweight Charts 4.1 (TradingView) |
| Layout | react-resizable-panels 1.0 |
| Styling | CSS custom properties (no Tailwind) |

---

## Project Structure

```
Visualiser-IMC/
|-- backend/
|   |-- requirements.txt
|   |-- app/
|       |-- main.py                          # FastAPI app entry point, lifespan, routers
|       |-- __init__.py
|       |-- core/
|       |   |-- config.py                    # Settings (pydantic-settings)
|       |   |-- deps.py                      # Dependency injection helpers
|       |-- models/
|       |   |-- market.py                    # MarketSnapshot, TradePrint, OrderBook models
|       |   |-- trading.py                   # StrategyOrder, FillEvent models
|       |   |-- strategy.py                  # Strategy metadata models
|       |   |-- backtest.py                  # BacktestConfig, BacktestRun, ExecutionModel
|       |   |-- analytics.py                 # Performance and execution metric models
|       |   |-- events.py                    # Event models
|       |-- api/
|       |   |-- datasets.py                  # /api/datasets endpoints
|       |   |-- replay.py                    # /api/replay endpoints
|       |   |-- backtest.py                  # /api/backtest endpoints
|       |   |-- strategies.py                # /api/strategies endpoints
|       |   |-- websocket.py                 # /api/ws/replay WebSocket
|       |-- engines/
|       |   |-- data/
|       |   |   |-- loader.py                # CSV discovery and parsing
|       |   |   |-- normalizer.py            # Type normalization
|       |   |   |-- aggregator.py            # OHLCV aggregation
|       |   |-- replay/
|       |   |   |-- engine.py                # Market replay engine
|       |   |   |-- state.py                 # Replay session state
|       |   |-- execution/
|       |   |   |-- engine.py                # Order execution simulation
|       |   |-- backtest/
|       |   |   |-- engine.py                # Backtest orchestration
|       |   |-- sandbox/
|       |   |   |-- runner.py                # Strategy sandbox execution
|       |   |   |-- adapter.py               # Prosperity protocol adapter
|       |   |-- orderbook/
|       |   |   |-- book.py                  # Order book construction
|       |   |   |-- metrics.py               # Book metrics (imbalance, spread)
|       |   |-- analytics/
|       |   |   |-- indicators.py            # Technical indicators (SMA, EMA, RSI, MACD, etc.)
|       |   |   |-- execution_analytics.py   # Execution quality analysis
|       |   |-- strategies/
|       |       |-- registry.py              # Strategy registry
|       |       |-- market_making.py         # 5 market making strategies
|       |       |-- mean_reversion.py        # 4 mean reversion strategies
|       |       |-- momentum.py              # 5 momentum strategies
|       |       |-- microstructure.py        # 3 microstructure strategies
|       |-- storage/
|       |   |-- database.py                  # SQLite persistence
|       |-- tests/
|           |-- test_api.py
|           |-- test_backtest.py
|           |-- test_data_loader.py
|           |-- test_execution.py
|           |-- test_models.py
|           |-- test_orderbook.py
|           |-- test_replay.py
|           |-- test_sandbox.py
|           |-- test_analytics.py
|-- frontend/
|   |-- index.html
|   |-- package.json
|   |-- tsconfig.json
|   |-- tsconfig.node.json
|   |-- vite.config.ts
|   |-- src/
|       |-- main.tsx                         # React entry point
|       |-- app/
|       |   |-- App.tsx                      # Root component
|       |-- types/
|       |   |-- index.ts                     # TypeScript type definitions
|       |-- store/
|       |   |-- index.ts                     # Zustand stores (Dataset, Replay, Backtest, Strategy, UI)
|       |-- services/
|       |   |-- api.ts                       # HTTP and WebSocket API client
|       |-- hooks/
|       |   |-- useKeyboardShortcuts.ts      # Keyboard shortcut handler
|       |   |-- useWebSocket.ts              # WebSocket connection hook
|       |-- components/
|       |   |-- Header.tsx                   # Top header bar with controls
|       |-- layouts/
|       |   |-- TerminalLayout.tsx           # Workspace layout manager
|       |-- panels/
|       |   |-- OrderBookPanel.tsx           # Order book ladder view
|       |   |-- DepthChartPanel.tsx          # Visual depth chart
|       |   |-- ChartPanel.tsx               # Main price chart (tick/OHLC/candlestick)
|       |   |-- TradeTapePanel.tsx           # Real-time trade tape
|       |   |-- StrategyPanel.tsx            # Strategy library and configuration
|       |   |-- MetricsPanel.tsx             # Performance metrics display
|       |   |-- DebugTracePanel.tsx          # Per-tick strategy debug output
|       |   |-- FillsPanel.tsx               # Fill history table
|       |   |-- PositionsPanel.tsx           # Position tracking
|       |-- styles/
|           |-- global.css                   # Global styles with CSS variables
|-- sample_data/
|   |-- prices_round_0_day_-1.csv
|   |-- prices_round_0_day_-2.csv
|   |-- trades_round_0_day_-1.csv
|   |-- trades_round_0_day_-2.csv
|-- sample_strategies/
|   |-- simple_market_maker.py
|   |-- mean_reversion_example.py
|-- storage/                                 # SQLite database (created at runtime)
|-- docs/
|   |-- strategy-interface.md
|   |-- execution-model.md
|   |-- ui-guide.md
|   |-- development.md
```

---

## License

MIT
