"""High-level replay service that bridges the API layer to the replay engine."""

import logging
from typing import Any, Optional

from app.engines.replay.engine import ReplayEngine
from app.engines.replay.state import ReplayState
from app.engines.sandbox.runner import StrategySandbox
from app.engines.sandbox.adapter import ProsperityAdapter
from app.engines.execution.engine import ExecutionEngine
from app.engines.strategies.registry import StrategyRegistry
from app.models.backtest import ExecutionModel
from app.models.events import EventType
from app.models.market import OrderSide, VisibleOrderBook, TradePrint
from app.services.dataset_service import DatasetService

logger = logging.getLogger(__name__)


class ReplayService:
    """Orchestrates interactive market replay sessions.

    Wraps :class:`ReplayEngine` and :class:`ReplayState` to provide
    a convenient interface for the API layer.
    """

    def __init__(
        self,
        replay_engine: ReplayEngine,
        dataset_service: DatasetService,
    ) -> None:
        self._engine = replay_engine
        self._dataset = dataset_service
        self._state = ReplayState()

        # Strategy execution state (populated when replay started with strategy)
        self._strategy_active = False
        self._strategy_instance: Any = None
        self._execution_engine: Optional[ExecutionEngine] = None
        self._adapter = ProsperityAdapter()
        self._sandbox = StrategySandbox()
        self._trader_data: str = ""
        self._products: list[str] = []
        self._strategy_positions: dict[str, int] = {}
        self._strategy_own_trades: dict[str, list[TradePrint]] = {}
        self._strategy_market_trades: dict[str, list[TradePrint]] = {}
        self._strategy_fills: list[dict] = []
        self._strategy_pnl: dict = {}
        self._strategy_cash: float = 0.0
        self._strategy_realized_pnl: dict[str, float] = {}
        self._strategy_avg_entry: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_replay(
        self,
        products: list[str],
        days: list[int],
        strategy_id: Optional[str] = None,
        execution_model: str = "BALANCED",
        position_limits: Optional[dict[str, int]] = None,
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Load events for the given products/days and initialise the replay."""
        events = self._dataset.get_event_stream(products, days)
        if not events:
            return {"error": "No events found for the given products and days"}

        self._engine.load_events(events)
        self._state.reset()
        self._products = products

        # Reset strategy state
        self._strategy_active = False
        self._strategy_instance = None
        self._execution_engine = None
        self._trader_data = ""
        self._strategy_positions = {p: 0 for p in products}
        self._strategy_own_trades = {p: [] for p in products}
        self._strategy_market_trades = {p: [] for p in products}
        self._strategy_fills = []
        self._strategy_pnl = {}
        self._strategy_cash = 0.0
        self._strategy_realized_pnl = {p: 0.0 for p in products}
        self._strategy_avg_entry = {p: 0.0 for p in products}

        # If strategy_id is provided, set up strategy execution
        if strategy_id:
            try:
                self._setup_strategy(
                    strategy_id,
                    execution_model=execution_model,
                    position_limits=position_limits or {p: 20 for p in products},
                    parameters=parameters or {},
                )
            except Exception as exc:
                logger.error("Failed to set up strategy for replay: %s", exc)
                return {"error": f"Failed to set up strategy: {exc}"}

        return {
            "session_id": self._engine.session_id,
            "total_events": len(events),
            "products": products,
            "days": days,
            "strategy_id": strategy_id,
            "strategy_active": self._strategy_active,
        }

    def _setup_strategy(
        self,
        strategy_id: str,
        execution_model: str = "BALANCED",
        position_limits: Optional[dict[str, int]] = None,
        parameters: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize strategy sandbox and execution engine for live replay."""
        from app.core.deps import get_strategy_registry, get_storage

        registry = get_strategy_registry()
        strat_def = registry.get_by_id(strategy_id)
        source_code: Optional[str] = None

        if strat_def is not None:
            # Built-in strategy from registry
            source_code = strat_def.source_code
        else:
            # Check uploaded strategies in storage (database)
            storage = get_storage()
            stored = storage.get_strategy(strategy_id)
            if stored is not None:
                source_code = stored.get("source_code")

        if source_code is None:
            raise ValueError(f"Strategy '{strategy_id}' not found")

        # Load the strategy
        self._strategy_instance = self._sandbox.load_strategy(source_code)

        # Create execution engine
        exec_model = ExecutionModel(execution_model)
        self._execution_engine = ExecutionEngine(
            execution_model=exec_model,
            position_limits=position_limits or {},
            fees=0.0,
            slippage=0.0,
        )

        self._strategy_active = True
        logger.info("Strategy '%s' activated for replay", strategy_id)

    def pause_replay(self) -> dict:
        """Pause the running replay."""
        self._engine.pause()
        return self._engine.get_session_state()

    def step_forward(self) -> dict:
        """Step one event forward and return event + state snapshot.

        If a strategy is active, also runs the strategy on BOOK_SNAPSHOT
        events and processes its orders through the execution engine.
        """
        event = self._engine.step_forward()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        changes = self._state.process_event(event)

        result = {
            "done": False,
            "event": event.model_dump(),
            "changes": changes,
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

        # Run strategy on BOOK_SNAPSHOT events
        if self._strategy_active and event.event_type == EventType.BOOK_SNAPSHOT:
            strategy_state = self._run_strategy_step(event)
            if strategy_state:
                result["strategy_state"] = strategy_state
                # Merge strategy PnL into main state so frontend picks it up
                if "pnl" in strategy_state:
                    result["state"]["pnl"] = strategy_state["pnl"]
                if "positions" in strategy_state:
                    result["state"]["positions"] = self._build_strategy_positions()
                if "fills" in strategy_state and strategy_state["fills"]:
                    # Use trade_tape key (what get_state_snapshot returns), NOT trades
                    existing_trades = result["state"].get("trade_tape", [])
                    fill_trades = []
                    for f in strategy_state["fills"]:
                        fill_trades.append({
                            "timestamp": f.get("timestamp", event.timestamp),
                            "symbol": f.get("product", ""),
                            "price": f.get("price", 0),
                            "quantity": f.get("quantity", 0),
                            "aggressor_side": f.get("side", "BUY"),
                            "buyer": "SUBMISSION" if f.get("side") == "BUY" else "",
                            "seller": "SUBMISSION" if f.get("side") == "SELL" else "",
                        })
                    result["state"]["trade_tape"] = (existing_trades + fill_trades) if isinstance(existing_trades, list) else fill_trades
        elif self._strategy_active:
            # On ALL non-BOOK_SNAPSHOT events, send current strategy PnL AND positions
            pnl = self._compute_strategy_pnl(self._state.books, event.timestamp)
            result["state"]["pnl"] = pnl
            result["state"]["positions"] = self._build_strategy_positions()

        # Accumulate market trades for strategy context
        if self._strategy_active and event.event_type == EventType.TRADE_PRINT:
            product = event.product or event.data.get("symbol", "")
            if product in self._strategy_market_trades:
                trade = TradePrint(
                    timestamp=event.timestamp,
                    buyer=event.data.get("buyer", ""),
                    seller=event.data.get("seller", ""),
                    symbol=product,
                    currency=event.data.get("currency", "SEASHELLS"),
                    price=event.data.get("price", 0.0),
                    quantity=event.data.get("quantity", 0),
                    aggressor_side=event.data.get("aggressor_side"),
                )
                self._strategy_market_trades[product].append(trade)
                # Keep only last 50 trades per product
                if len(self._strategy_market_trades[product]) > 50:
                    self._strategy_market_trades[product] = self._strategy_market_trades[product][-50:]

        return result

    def _process_fill(self, fill, timestamp: int) -> dict:
        """Process a single fill: update positions, own trades, PnL. Returns fill dict."""
        is_buy = fill.side == OrderSide.BUY

        fill_dict = {
            "order_id": fill.order_id,
            "product": fill.product,
            "side": fill.side.value if hasattr(fill.side, 'value') else ("BUY" if is_buy else "SELL"),
            "price": fill.price,
            "quantity": fill.quantity,
            "timestamp": fill.timestamp or timestamp,
            "is_aggressive": fill.is_aggressive,
        }
        self._strategy_fills.append(fill_dict)

        # Update positions: BUY adds, SELL subtracts
        signed_qty = fill.quantity if is_buy else -fill.quantity
        old_pos = self._strategy_positions.get(fill.product, 0)
        new_pos = old_pos + signed_qty
        self._strategy_positions[fill.product] = new_pos
        self._execution_engine.update_position(fill.product, new_pos)

        # Track own trades for next strategy call
        own_trade = TradePrint(
            timestamp=fill.timestamp or timestamp,
            buyer="SUBMISSION" if is_buy else "",
            seller="" if is_buy else "SUBMISSION",
            symbol=fill.product,
            price=fill.price,
            quantity=fill.quantity,
        )
        if fill.product not in self._strategy_own_trades:
            self._strategy_own_trades[fill.product] = []
        self._strategy_own_trades[fill.product].append(own_trade)

        # Update PnL tracking
        self._update_strategy_pnl(fill, old_pos)

        return fill_dict

    def _run_strategy_step(self, event) -> Optional[dict]:
        """Execute the strategy against the current book state and return results.

        Flow (matches Prosperity semantics):
        1. Check passive fills on EXISTING resting orders against the NEW book
           (orders placed on tick N are evaluated against tick N+1's book)
        2. Cancel remaining unfilled resting orders
        3. Run the strategy to get new orders
        4. Process new orders: aggressive fills happen immediately,
           passive orders rest until the next tick
        """
        if not self._strategy_instance or not self._execution_engine:
            return None

        try:
            books = self._state.books
            timestamp = event.timestamp
            step_fills = []

            # ── Step 1: Check passive fills on EXISTING resting orders ──
            # Orders from the PREVIOUS tick are checked against the CURRENT book.
            # This is the correct Prosperity flow: orders placed on tick N
            # get evaluated for fills when tick N+1's book arrives.
            for product in self._products:
                book = books.get(product)
                if book is None:
                    continue
                recent = self._strategy_market_trades.get(product, [])
                passive_fills = self._execution_engine.check_passive_fills(book, recent)
                for fill in passive_fills:
                    fd = self._process_fill(fill, timestamp)
                    step_fills.append(fd)

            # ── Step 2: Cancel remaining resting orders (Prosperity semantics) ──
            self._execution_engine.cancel_all_resting(self._products)

            # ── Step 3: Build state and run strategy ──
            trading_state = self._adapter.build_state(
                timestamp=timestamp,
                products=self._products,
                books=books,
                positions=self._strategy_positions,
                own_trades=self._strategy_own_trades,
                market_trades=self._strategy_market_trades,
                trader_data=self._trader_data,
            )

            raw_orders, conversions, trader_data = self._sandbox.execute_strategy(
                self._strategy_instance,
                trading_state,
            )
            self._trader_data = trader_data if isinstance(trader_data, str) and not trader_data.startswith("ERROR:") else self._trader_data

            # ── Step 4: Parse and process new orders ──
            orders = self._adapter.parse_orders(
                raw_orders if isinstance(raw_orders, dict) else {},
                timestamp=timestamp,
            )

            orders_submitted = []
            for order in orders:
                orders_submitted.append({
                    "order_id": order.order_id,
                    "product": order.product,
                    "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                    "price": order.price,
                    "quantity": order.quantity,
                })

                book = books.get(order.product)
                if book is None:
                    continue

                # Aggressive orders fill immediately; passive orders go to resting book
                fills = self._execution_engine.process_order(
                    order, book
                )

                for fill in fills:
                    fd = self._process_fill(fill, timestamp)
                    step_fills.append(fd)

            # Clear own trades after strategy consumed them (Prosperity semantics)
            for p in self._products:
                self._strategy_own_trades[p] = []

            # Compute current PnL
            pnl = self._compute_strategy_pnl(books, timestamp)

            return {
                "orders_submitted": orders_submitted,
                "fills": step_fills,
                "positions": dict(self._strategy_positions),
                "pnl": pnl,
                "total_fills": len(self._strategy_fills),
            }

        except Exception as exc:
            logger.error("Strategy step failed: %s", exc, exc_info=True)
            return {
                "error": str(exc),
                "orders_submitted": [],
                "fills": [],
                "positions": dict(self._strategy_positions),
                "pnl": self._compute_strategy_pnl(self._state.books, event.timestamp),
                "total_fills": len(self._strategy_fills),
            }

    def _update_strategy_pnl(self, fill, old_pos: int) -> None:
        """Update realized PnL when a fill reduces/flips the position."""
        product = fill.product
        is_buy = fill.side == OrderSide.BUY or (hasattr(fill.side, 'value') and fill.side.value == "BUY")
        signed_qty = fill.quantity if is_buy else -fill.quantity
        new_pos = old_pos + signed_qty

        if old_pos == 0:
            self._strategy_avg_entry[product] = fill.price
        elif (old_pos > 0 and signed_qty > 0) or (old_pos < 0 and signed_qty < 0):
            # Adding to position
            total_cost = self._strategy_avg_entry.get(product, 0.0) * abs(old_pos) + fill.price * abs(signed_qty)
            self._strategy_avg_entry[product] = total_cost / abs(new_pos) if new_pos != 0 else 0.0
        else:
            # Reducing/flipping
            closed_qty = min(abs(signed_qty), abs(old_pos))
            avg_entry = self._strategy_avg_entry.get(product, 0.0)
            if old_pos > 0:
                realized = (fill.price - avg_entry) * closed_qty
            else:
                realized = (avg_entry - fill.price) * closed_qty
            self._strategy_realized_pnl[product] = self._strategy_realized_pnl.get(product, 0.0) + realized
            self._strategy_cash += realized

            if abs(signed_qty) > abs(old_pos):
                self._strategy_avg_entry[product] = fill.price

    def _build_strategy_positions(self) -> dict:
        """Build position dict from current strategy state for frontend."""
        pos_dict = {}
        for p, q in self._strategy_positions.items():
            book = self._state.books.get(p)
            mid = book.mid_price if book else 0.0
            avg_entry = self._strategy_avg_entry.get(p, 0.0)
            if q > 0 and mid:
                unrealized = (mid - avg_entry) * q
            elif q < 0 and mid:
                unrealized = (avg_entry - mid) * abs(q)
            else:
                unrealized = 0.0
            pos_dict[p] = {
                "product": p,
                "quantity": q,
                "avg_entry_price": round(avg_entry, 2),
                "mark_price": round(mid, 2) if mid else 0.0,
                "unrealized_pnl": round(unrealized, 2),
                "realized_pnl": round(self._strategy_realized_pnl.get(p, 0.0), 2),
                "position_limit": 20,
            }
        return pos_dict

    def _compute_strategy_pnl(self, books: dict[str, VisibleOrderBook], timestamp: int) -> dict:
        """Compute current strategy PnL from positions and books."""
        total_realized = sum(self._strategy_realized_pnl.values())
        total_unrealized = 0.0
        for product, pos in self._strategy_positions.items():
            if pos == 0:
                continue
            book = books.get(product)
            mid = book.mid_price if book else None
            if mid is None:
                continue
            avg_entry = self._strategy_avg_entry.get(product, 0.0)
            if pos > 0:
                total_unrealized += (mid - avg_entry) * pos
            else:
                total_unrealized += (avg_entry - mid) * abs(pos)

        return {
            "timestamp": timestamp,
            "realized_pnl": round(total_realized, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "total_pnl": round(total_realized + total_unrealized, 2),
            "inventory": {p: q for p, q in self._strategy_positions.items() if q != 0},
            "cash": round(self._strategy_cash, 2),
        }

    def step_backward(self) -> dict:
        """Step one event backward.

        Note: backward stepping returns the event at the new position
        but does NOT reverse state changes. A full state reconstruction
        would require replaying from the beginning up to the new cursor.
        """
        event = self._engine.step_backward()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        return {
            "done": False,
            "event": event.model_dump(),
            **self._engine.get_session_state(),
        }

    def seek(self, timestamp: int) -> dict:
        """Seek to the nearest event at the given timestamp.

        Rebuilds state by replaying all events from the beginning up to
        the new cursor position.
        """
        event = self._engine.seek(timestamp)
        if event is None:
            return {"error": "Empty event stream"}

        # Rebuild state up to current position
        self._state.reset()
        for ev in self._engine.get_events_up_to_current():
            self._state.process_event(ev)

        return {
            "event": event.model_dump(),
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    def set_speed(self, speed: float) -> None:
        """Set the playback speed multiplier."""
        self._engine.set_speed(speed)

    def get_state(self) -> dict:
        """Return the current engine + world state."""
        return {
            "engine": self._engine.get_session_state(),
            "state": self._state.get_state_snapshot(),
        }

    def reset(self) -> None:
        """Full reset of engine and state."""
        self._engine.stop()
        self._state.reset()

    # ------------------------------------------------------------------
    # Convenience jumps
    # ------------------------------------------------------------------

    def jump_next_trade(self) -> dict:
        """Jump to the next TRADE_PRINT event."""
        event = self._engine.jump_to_next_trade()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        # Replay state up to new position
        self._state.reset()
        for ev in self._engine.get_events_up_to_current():
            self._state.process_event(ev)

        return {
            "done": False,
            "event": event.model_dump(),
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    def jump_next_fill(self) -> dict:
        """Jump to the next FILL event."""
        event = self._engine.jump_to_next_fill()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        self._state.reset()
        for ev in self._engine.get_events_up_to_current():
            self._state.process_event(ev)

        return {
            "done": False,
            "event": event.model_dump(),
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    # ------------------------------------------------------------------
    # Accessors for WebSocket streaming
    # ------------------------------------------------------------------

    @property
    def engine(self) -> ReplayEngine:
        return self._engine

    @property
    def state(self) -> ReplayState:
        return self._state
