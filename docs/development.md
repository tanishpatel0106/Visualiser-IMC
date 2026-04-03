# Development Guide

Notes for developers working on the IMC Prosperity Trading Terminal codebase. Covers architecture decisions, extension points, testing, and conventions.

---

## Table of Contents

- [Architecture Decisions](#architecture-decisions)
- [Module Boundaries](#module-boundaries)
- [How to Add a New Built-in Strategy](#how-to-add-a-new-built-in-strategy)
- [How to Add a New Indicator](#how-to-add-a-new-indicator)
- [How to Add a New Product](#how-to-add-a-new-product)
- [How to Add a New Data Adapter](#how-to-add-a-new-data-adapter)
- [Testing Approach](#testing-approach)
- [API Endpoint Conventions](#api-endpoint-conventions)
- [WebSocket Protocol](#websocket-protocol)
- [Frontend State Management with Zustand](#frontend-state-management-with-zustand)
- [Styling Conventions](#styling-conventions)

---

## Architecture Decisions

### Separation of backend and frontend

The backend is a standalone FastAPI application that serves as a headless API. The frontend is a standalone Vite/React application. They communicate exclusively over HTTP and WebSocket. This separation allows either side to be replaced or extended independently.

### Engine-based backend design

The backend organizes domain logic into **engines** rather than services or fat models. Each engine owns a specific simulation responsibility:

| Engine | Responsibility |
|---|---|
| `data/` | CSV discovery, parsing, schema validation, normalization. |
| `replay/` | Stateful market replay (play, pause, step, seek, reset). |
| `execution/` | Order matching, fill simulation, position tracking. |
| `backtest/` | Orchestrates a full backtest: load data, build state, call strategy, process orders, collect results. |
| `sandbox/` | Runs user-uploaded strategy code in a controlled environment. Provides the Prosperity protocol adapter. |
| `orderbook/` | Constructs `VisibleOrderBook` from snapshots, computes book metrics. |
| `analytics/` | Technical indicators and execution quality analytics. |
| `strategies/` | Built-in strategy library and the strategy registry. |

Engines are stateless where possible (execution engine holds resting orders as deliberate state) and are instantiated per request or per session.

### Prosperity protocol compatibility

The sandbox adapter translates between internal models (`VisibleOrderBook`, `TradePrint`, `StrategyOrder`) and the Prosperity competition's expected types (`TradingState`, `OrderDepth`, `Order`, `Trade`). This allows competition-grade strategies to run unmodified.

### Snapshot-aware execution modeling

The three execution models (Conservative, Balanced, Optimistic) exist because snapshot data is fundamentally different from a full exchange feed. This is a deliberate design choice, not a simplification to be removed later.

### Frontend with minimal dependencies

The frontend uses only four production dependencies: React, Zustand, Lightweight Charts, and react-resizable-panels. There is no routing library (it is a single-page terminal), no CSS framework (CSS custom properties handle theming), and no data-fetching library beyond `fetch`.

---

## Module Boundaries

### Backend

```
app/
  api/          -- FastAPI routers. Thin layer: validate input, call engines, return response.
  models/       -- Pydantic models and enums. No business logic.
  engines/      -- All domain logic. Engines may depend on models but not on api/.
  core/         -- Configuration and dependency injection. No domain logic.
  storage/      -- SQLite persistence. Engines use storage through dependency injection.
  tests/        -- Unit and integration tests.
```

**Dependency rule:** `api/ -> engines/ -> models/`. Never `models/ -> engines/` or `engines/ -> api/`.

### Frontend

```
src/
  app/          -- Root App component.
  types/        -- TypeScript type definitions. No logic.
  store/        -- Zustand stores. State and actions only.
  services/     -- API client functions. Network calls only.
  hooks/        -- React hooks. Compose stores + side effects.
  components/   -- Reusable UI components (Header).
  layouts/      -- Workspace layout definitions.
  panels/       -- Domain-specific panel components.
  styles/       -- Global CSS.
```

**Dependency rule:** Panels depend on stores, hooks, and services. Stores depend only on types. Services depend only on types.

---

## How to Add a New Built-in Strategy

1. **Choose a category.** Open the corresponding module in `backend/app/engines/strategies/`:
   - `market_making.py` for market-making strategies
   - `mean_reversion.py` for mean-reversion strategies
   - `momentum.py` for momentum / trend strategies
   - `microstructure.py` for microstructure strategies

   Or create a new module for a new category and import it in `registry.py`'s `load_builtins()` method.

2. **Write the strategy class.** Follow the established pattern:

   ```python
   class MyNewStrategy:
       """Docstring explaining the strategy.

       Parameters (via traderData JSON):
           param_a (int): Description, default X.
           param_b (float): Description, default Y.
       """

       def __init__(self) -> None:
           self.param_a = 10
           self.param_b = 0.5

       def run(self, state):
           from backend.app.engines.sandbox.adapter import Order

           trader_data: dict = {}
           if state.traderData:
               trader_data = json.loads(state.traderData)
               self.param_a = trader_data.get("param_a", self.param_a)
               self.param_b = trader_data.get("param_b", self.param_b)

           result: dict[str, list] = {}

           for product in state.order_depths:
               orders = []
               # ... strategy logic ...
               result[product] = orders

           trader_data.update({
               "param_a": self.param_a,
               "param_b": self.param_b,
           })
           return result, 0, json.dumps(trader_data)
   ```

   Key conventions:
   - Import `Order` inside `run()`, not at module level.
   - Read parameters from `traderData` with defaults.
   - Write parameters back to `traderData` at the end.
   - Use the `_clamp_order_qty` helper for position-limit-aware sizing.
   - Use `_get_mid_price` for mid-price computation.

3. **Add a `StrategyDefinition` entry.** Append to the module's `STRATEGY_DEFINITIONS` list:

   ```python
   STRATEGY_DEFINITIONS = [
       # ... existing entries ...
       StrategyDefinition(
           strategy_id="my_new_strategy",
           name="My New Strategy",
           category="market_making",  # must match the module's category
           description="One-sentence description.",
           source_code=_get_source(MyNewStrategy),
           parameters={
               "param_a": {"type": "int", "default": 10, "description": "What it controls"},
               "param_b": {"type": "float", "default": 0.5, "description": "What it controls"},
           },
       ),
   ]
   ```

4. **Verify.** Start the backend and check that the strategy appears in the registry:
   ```bash
   curl http://localhost:8000/api/strategies | python -m json.tool
   ```

---

## How to Add a New Indicator

1. **Open** `backend/app/engines/analytics/indicators.py`.

2. **Add a static method** to the `TechnicalIndicators` class:

   ```python
   @staticmethod
   def my_indicator(values: list[float], period: int) -> list[Optional[float]]:
       """Description of the indicator."""
       n = len(values)
       if period <= 0 or n == 0:
           return [None] * n
       result: list[Optional[float]] = [None] * n
       for i in range(period - 1, n):
           # ... computation ...
           result[i] = computed_value
       return result
   ```

   Conventions:
   - Return a list the same length as the input.
   - Fill positions where the indicator cannot be computed with `None`.
   - Use NumPy for performance on large arrays.
   - Accept a `period` or `window` parameter for rolling computations.

3. **Wire it into the API** by updating the indicator endpoint in `backend/app/api/datasets.py` to recognize the new indicator name and call the method.

4. **Expose it in the frontend** by adding the indicator name to the selector in `frontend/src/panels/ChartPanel.tsx` and mapping it to the appropriate chart series type (overlay on price, or sub-panel).

---

## How to Add a New Product

Products are discovered automatically from the data. No code changes are needed.

1. Include the product name in the `product` column of your price CSV files.
2. Include the product name in the `symbol` column of your trade CSV files.
3. Place the files in the data directory following the naming convention `prices_round_{N}_day_{D}.csv` and `trades_round_{N}_day_{D}.csv`.
4. Reload the dataset (restart the backend or call `POST /api/datasets/load`).

The product will appear in the frontend's product selector and all panels will display its data.

If you need product-specific position limits, configure them in the backtest config:

```json
{
  "position_limits": {
    "NEW_PRODUCT": 20
  }
}
```

---

## How to Add a New Data Adapter

To support a data source with a different schema or format:

1. **Create a new loader** in `backend/app/engines/data/`. Follow the pattern in `loader.py`:
   - Implement `discover_datasets(directory)` to scan for files.
   - Implement schema validation methods.
   - Implement `load_*` methods that return `MarketSnapshot` and `TradePrint` model objects.

2. **Register the adapter** in the dataset service (in `core/deps.py` or wherever the service is constructed). The service should detect which adapter to use based on file format or explicit configuration.

3. **Normalize output** to the standard `MarketSnapshot` and `TradePrint` models so that downstream engines (replay, execution, analytics) work without modification.

Example: to support a JSON-based data format:

```python
class JsonDataLoader:
    def discover_datasets(self, directory: str) -> dict[str, str]:
        # Scan for .json files matching a pattern
        ...

    def load_price_json(self, filepath: str) -> list[MarketSnapshot]:
        with open(filepath) as f:
            raw = json.load(f)
        snapshots = []
        for entry in raw:
            snapshot = MarketSnapshot(
                day=entry["day"],
                timestamp=entry["timestamp"],
                product=entry["product"],
                bid_prices=[entry.get("bid_1_price")],
                bid_volumes=[entry.get("bid_1_vol")],
                ask_prices=[entry.get("ask_1_price")],
                ask_volumes=[entry.get("ask_1_vol")],
                mid_price=entry.get("mid"),
            )
            snapshots.append(snapshot)
        return snapshots
```

---

## Testing Approach

### Backend tests

Tests live in `backend/app/tests/` and use pytest with pytest-asyncio for async endpoint tests.

| Test module | Coverage |
|---|---|
| `test_api.py` | HTTP endpoint behavior (status codes, response shapes). |
| `test_backtest.py` | Backtest engine orchestration. |
| `test_data_loader.py` | CSV parsing, schema validation, error handling. |
| `test_execution.py` | Execution engine: aggressive fills, passive fills per model, position limits, fees, slippage. |
| `test_models.py` | Pydantic model validation and serialization. |
| `test_orderbook.py` | Order book construction and metrics. |
| `test_replay.py` | Replay session state management. |
| `test_sandbox.py` | Strategy sandbox: adapter translation, timeouts, error isolation. |
| `test_analytics.py` | Indicator correctness. |

Run all tests:

```bash
cd backend
python -m pytest app/tests/ -v
```

Run a specific test file:

```bash
python -m pytest app/tests/test_execution.py -v
```

### Testing conventions

- Each test function tests a single behavior.
- Use descriptive test names: `test_aggressive_buy_fills_at_ask_levels`.
- Test edge cases: empty order books, zero-volume levels, boundary position limits.
- Use httpx `AsyncClient` for API tests against the FastAPI app directly (no server needed).
- Execution engine tests construct `VisibleOrderBook` and `TradePrint` objects directly rather than loading CSV files.

### Frontend

The frontend does not currently have automated tests. Manual testing via the browser is the primary approach. Consider adding:
- Vitest for unit testing Zustand store logic.
- Playwright or Cypress for end-to-end testing of workspace interactions.

---

## API Endpoint Conventions

### URL structure

All endpoints are mounted under `/api`:

| Prefix | Router | Purpose |
|---|---|---|
| `/api/datasets` | `datasets.py` | Dataset loading, product/day listing, snapshot/trade/OHLCV/indicator queries. |
| `/api/replay` | `replay.py` | Replay transport: start, pause, step, seek, reset, speed. |
| `/api/backtest` | `backtest.py` | Run backtests, fetch results, metrics, trace, fills, PnL, export. |
| `/api/strategies` | `strategies.py` | List strategies, get details, get source, upload, run. |
| `/api/ws/replay` | `websocket.py` | WebSocket for streaming replay state. |

### HTTP methods

- `GET` for read-only queries.
- `POST` for actions that change state (start replay, run backtest, upload strategy).

### Request/response format

- Request bodies use JSON (`Content-Type: application/json`).
- File uploads use multipart form data.
- Responses return JSON with appropriate Pydantic model serialization.
- Error responses include a plain-text error message in the body.

### Idempotency

- Replay control endpoints (pause, step, seek, reset) are idempotent.
- Backtest runs create a new `run_id` each time and are not idempotent.

---

## WebSocket Protocol

The WebSocket endpoint at `/api/ws/replay` streams real-time replay state updates to connected clients.

### Connection

```javascript
const ws = new WebSocket('ws://localhost:8000/api/ws/replay');
```

The frontend's `useWebSocket` hook manages the connection lifecycle with automatic reconnection on disconnect (3-second delay).

### Message format

The server sends JSON messages containing partial `ReplayState` updates:

```json
{
  "is_playing": true,
  "current_timestamp": 15000,
  "current_index": 42,
  "total_events": 1000,
  "speed": 1.0,
  "books": {
    "AMETHYSTS": {
      "product": "AMETHYSTS",
      "timestamp": 15000,
      "bids": [{"price": 9998, "volume": 15}],
      "asks": [{"price": 10002, "volume": 12}],
      "best_bid": 9998,
      "best_ask": 10002
    }
  },
  "trades": [...],
  "positions": {...},
  "pnl": {
    "timestamp": 15000,
    "realized_pnl": 50.0,
    "unrealized_pnl": -10.0,
    "total_pnl": 40.0,
    "fees": 2.0
  },
  "inventory": {...}
}
```

Fields are optional; the client merges partial updates into its local state.

### Client behavior

The frontend's `useReplayStore.updateReplayState()` merges incoming WebSocket messages into the Zustand store, triggering re-renders only for panels that consume the changed state slices.

---

## Frontend State Management with Zustand

The frontend uses five Zustand stores, each owning a distinct domain:

### DatasetStore

Tracks which datasets are available and which product/day is selected.

| State | Description |
|---|---|
| `datasets` | List of available dataset names. |
| `loadedDataset` | Currently loaded dataset info (products, days). |
| `products` | Available products in the loaded dataset. |
| `days` | Available days in the loaded dataset. |
| `selectedProduct` | Currently selected product for all panels. |
| `selectedDay` | Currently selected day. |

### ReplayStore

Tracks the real-time replay state, updated by WebSocket messages.

| State | Description |
|---|---|
| `isPlaying` | Whether replay is active. |
| `currentTimestamp` | Current tick timestamp. |
| `speed` | Replay speed multiplier. |
| `totalEvents` | Total events in the replay sequence. |
| `currentIndex` | Current position in the sequence. |
| `books` | Current order books per product. |
| `trades` | Recent trade prints. |
| `positions` | Current positions per product. |
| `pnl` | Current PnL state. |
| `inventory` | Inventory breakdown. |

### BacktestStore

Tracks backtest runs and their results.

| State | Description |
|---|---|
| `runs` | List of all backtest runs. |
| `currentRun` | The currently selected/active run. |
| `metrics` | Performance and execution metrics for the current run. |
| `trace` | Debug trace frames. |
| `fills` | Fill events. |
| `pnlHistory` | PnL time series. |
| `ohlcv` | OHLCV bar data. |

### StrategyStore

Manages strategy selection and parameter configuration.

| State | Description |
|---|---|
| `strategies` | List of available strategy definitions. |
| `selectedStrategy` | Currently selected strategy. |
| `parameters` | Current parameter values (key-value map). |
| `sourceCode` | Source code of the selected strategy. |

When a strategy is selected, parameters are automatically populated with defaults.

### UIStore

Controls UI-only state that has no backend counterpart.

| State | Description |
|---|---|
| `activeWorkspace` | Current workspace preset (`trading`, `analysis`, `strategy`, `debug`). |
| `selectedIndicators` | List of enabled indicator names for the chart. |
| `chartMode` | Current chart mode (`tick`, `ohlc`, `candlestick`). |
| `bottomTab` | Active tab in the bottom panel. |
| `showSettings` | Whether the settings modal is visible. |

### Design principles

- Stores are flat (no nesting). Computed values are derived in components.
- Actions are defined inside the store creator for colocation.
- Components subscribe to specific state slices (`useStore(s => s.field)`) to minimize re-renders.
- API calls are made in hooks or event handlers, not inside stores.

---

## Styling Conventions

### CSS custom properties

All colors, borders, backgrounds, and typography sizes are defined as CSS custom properties in `frontend/src/styles/global.css`. Components reference these variables rather than hardcoding values:

```css
/* Example variables (defined in global.css) */
--bg-base: #0d1117;
--bg-panel: #161b22;
--bg-panel-alt: #1c2128;
--text-primary: #e6edf3;
--text-dim: #8b949e;
--border-primary: #30363d;
--accent-green: #3fb950;
--accent-red: #f85149;
```

### No Tailwind

The project deliberately avoids Tailwind CSS and utility-class frameworks. Styles are defined using:

1. **CSS custom properties** for theming.
2. **Inline styles** via JavaScript objects (used in layout components for computed dimensions).
3. **CSS class selectors** in `global.css` for shared patterns (`.panel`, `.panel-header`, `.tab`, `.tab.active`).

### Panel styling pattern

Every panel follows the same structural pattern:

```tsx
<div className="panel" style={{ height: '100%' }}>
  <div className="panel-header">
    <span className="panel-title">Panel Name</span>
    {/* Optional controls */}
  </div>
  <div className="panel-body">
    {/* Panel content */}
  </div>
</div>
```

### Color semantics

- **Green** (`--accent-green`) for positive values, buys, bids, up candles, and profitable metrics.
- **Red** (`--accent-red`) for negative values, sells, asks, down candles, and loss metrics.
- **Dim text** (`--text-dim`) for secondary information, timestamps, labels.
- **Primary text** (`--text-primary`) for values and headings.

### Inline styles vs CSS classes

Use inline styles (via `React.CSSProperties` objects) for:
- Layout-specific positioning (flex direction, panel dimensions).
- One-off styles unique to a single component.

Use CSS classes for:
- Shared patterns used across multiple components (panels, tabs, headers).
- Interactive states (hover, active, focus).
- Animations and transitions.
