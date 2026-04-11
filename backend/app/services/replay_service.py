"""High-level replay service that bridges the API layer to the replay engine."""

import logging
from collections import defaultdict
from typing import Any, Optional

from app.engines.replay.engine import ReplayEngine
from app.engines.replay.state import ReplayState
from app.engines.sandbox.runner import StrategySandbox
from app.engines.sandbox.adapter import ProsperityAdapter
from app.engines.execution.engine import ExecutionEngine, MarketTrade
from app.engines.strategies.registry import StrategyRegistry
from app.models.backtest import TradeMatchingMode, _map_execution_model
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

        # Strategy execution state
        self._strategy_active = False
        self._strategy_instance: Any = None
        self._execution_engine: Optional[ExecutionEngine] = None
        self._adapter = ProsperityAdapter()
        self._sandbox = StrategySandbox()
        self._trader_data: str = ""
        self._products: list[str] = []

        # Positions and cash-flow PnL (matching backtest engine approach)
        self._positions: dict[str, int] = {}
        self._profit_loss: dict[str, float] = {}
        self._mid_prices: dict[str, float] = {}

        # Trade buffers
        self._own_trades: dict[str, list[TradePrint]] = {}
        self._market_trades: dict[str, list[TradePrint]] = {}
        self._strategy_fills: list[dict] = []

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
        self._positions = {p: 0 for p in products}
        self._profit_loss = {p: 0.0 for p in products}
        self._mid_prices = {}
        self._own_trades = {p: [] for p in products}
        self._market_trades = {p: [] for p in products}
        self._strategy_fills = []

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
            source_code = strat_def.source_code
        else:
            storage = get_storage()
            stored = storage.get_strategy(strategy_id)
            if stored is not None:
                source_code = stored.get("source_code")

        if source_code is None:
            raise ValueError(f"Strategy '{strategy_id}' not found")

        self._strategy_instance = self._sandbox.load_strategy(source_code)

        # Map legacy execution_model to TradeMatchingMode
        trade_matching = _map_execution_model(execution_model)

        self._execution_engine = ExecutionEngine(
            trade_matching_mode=trade_matching,
            position_limits=position_limits or {},
        )

        self._strategy_active = True
        logger.info("Strategy '%s' activated for replay", strategy_id)

    def pause_replay(self) -> dict:
        """Pause the running replay."""
        self._engine.pause()
        return self._engine.get_session_state()

    def step_forward(self) -> dict:
        """Step one event forward and return event + state snapshot."""
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
                if "pnl" in strategy_state:
                    result["state"]["pnl"] = strategy_state["pnl"]
                if "positions" in strategy_state:
                    result["state"]["positions"] = self._build_strategy_positions()
                if "fills" in strategy_state and strategy_state["fills"]:
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
                    result["state"]["trade_tape"] = (
                        (existing_trades + fill_trades)
                        if isinstance(existing_trades, list)
                        else fill_trades
                    )
        elif self._strategy_active:
            pnl = self._compute_strategy_pnl(event.timestamp)
            result["state"]["pnl"] = pnl
            result["state"]["positions"] = self._build_strategy_positions()

        # Accumulate market trades for strategy context
        if self._strategy_active and event.event_type == EventType.TRADE_PRINT:
            product = event.product or event.data.get("symbol", "")
            if product in self._market_trades:
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
                self._market_trades[product].append(trade)
                if len(self._market_trades[product]) > 50:
                    self._market_trades[product] = self._market_trades[product][-50:]

        return result

    def _run_strategy_step(self, event) -> Optional[dict]:
        """Execute the strategy against the current book state and return results.

        Uses the same matching logic as BacktestEngine:
        1. Build state from all products' books.
        2. Run strategy once.
        3. Enforce limits + match orders against book + market trades.
        4. Update cash-flow PnL.
        """
        if not self._strategy_instance or not self._execution_engine:
            return None

        try:
            books = self._state.books
            timestamp = event.timestamp
            step_fills = []

            # Update mid prices
            for p in self._products:
                book = books.get(p)
                if book is not None and book.mid_price is not None:
                    self._mid_prices[p] = book.mid_price

            # Build state and run strategy
            trading_state = self._adapter.build_state(
                timestamp=timestamp,
                products=self._products,
                books=books,
                positions=self._positions,
                own_trades=self._own_trades,
                market_trades=self._market_trades,
                trader_data=self._trader_data,
            )

            raw_orders, conversions, trader_data = self._sandbox.execute_strategy(
                self._strategy_instance, trading_state,
            )
            if isinstance(trader_data, str) and not trader_data.startswith("ERROR:"):
                self._trader_data = trader_data

            # Clear own trades (strategy has seen them)
            for p in self._products:
                self._own_trades[p] = []

            # Parse and match orders
            if not isinstance(raw_orders, dict):
                raw_orders = {}

            checked_orders = self._execution_engine.enforce_limits(raw_orders)

            orders_submitted = []
            for product, orders in checked_orders.items():
                if not orders:
                    continue

                for order in orders:
                    qty = getattr(order, "quantity", 0)
                    if qty == 0:
                        continue
                    orders_submitted.append({
                        "product": product,
                        "side": "BUY" if qty > 0 else "SELL",
                        "price": getattr(order, "price", 0),
                        "quantity": abs(qty),
                    })

                book = books.get(product)
                if book is None:
                    continue

                # Build mutable order depth
                buy_depth: dict[int, int] = {}
                sell_depth: dict[int, int] = {}
                for level in book.bids:
                    buy_depth[int(level.price)] = level.volume
                for level in book.asks:
                    sell_depth[int(level.price)] = -level.volume

                # Wrap recent trades as MarketTrade
                recent_trades = [
                    MarketTrade.from_trade_print(t)
                    for t in self._market_trades.get(product, [])
                ]

                fills = self._execution_engine.match_orders(
                    product=product,
                    orders=orders,
                    buy_orders=buy_depth,
                    sell_orders=sell_depth,
                    market_trades=recent_trades,
                    timestamp=timestamp,
                )

                for fill in fills:
                    fd = self._process_fill(fill, timestamp)
                    step_fills.append(fd)

            pnl = self._compute_strategy_pnl(timestamp)

            return {
                "orders_submitted": orders_submitted,
                "fills": step_fills,
                "positions": dict(self._positions),
                "pnl": pnl,
                "total_fills": len(self._strategy_fills),
            }

        except Exception as exc:
            logger.error("Strategy step failed: %s", exc, exc_info=True)
            return {
                "error": str(exc),
                "orders_submitted": [],
                "fills": [],
                "positions": dict(self._positions),
                "pnl": self._compute_strategy_pnl(event.timestamp),
                "total_fills": len(self._strategy_fills),
            }

    def _process_fill(self, fill, timestamp: int) -> dict:
        """Process a fill: update positions and cash-flow PnL."""
        is_buy = fill.side == OrderSide.BUY
        product = fill.product

        fill_dict = {
            "order_id": getattr(fill, "order_id", ""),
            "product": product,
            "side": fill.side.value if hasattr(fill.side, "value") else ("BUY" if is_buy else "SELL"),
            "price": fill.price,
            "quantity": fill.quantity,
            "timestamp": fill.timestamp or timestamp,
            "is_aggressive": fill.is_aggressive,
        }
        self._strategy_fills.append(fill_dict)

        # Cash-flow PnL update
        if is_buy:
            self._profit_loss[product] = self._profit_loss.get(product, 0.0) - fill.price * fill.quantity
            self._positions[product] = self._positions.get(product, 0) + fill.quantity
        else:
            self._profit_loss[product] = self._profit_loss.get(product, 0.0) + fill.price * fill.quantity
            self._positions[product] = self._positions.get(product, 0) - fill.quantity

        self._execution_engine.update_position(product, self._positions[product])

        # Buffer as own trade
        own_trade = TradePrint(
            timestamp=fill.timestamp or timestamp,
            buyer="SUBMISSION" if is_buy else "",
            seller="" if is_buy else "SUBMISSION",
            symbol=product,
            price=fill.price,
            quantity=fill.quantity,
        )
        if product not in self._own_trades:
            self._own_trades[product] = []
        self._own_trades[product].append(own_trade)

        return fill_dict

    def _build_strategy_positions(self) -> dict:
        """Build position dict for frontend."""
        pos_dict = {}
        for p, q in self._positions.items():
            mid = self._mid_prices.get(p, 0.0)
            cash_pnl = self._profit_loss.get(p, 0.0)
            product_pnl = cash_pnl + q * mid
            unrealized = product_pnl - cash_pnl

            pos_dict[p] = {
                "product": p,
                "quantity": q,
                "avg_entry_price": 0.0,  # Not tracked in cash-flow model
                "mark_price": round(mid, 2) if mid else 0.0,
                "unrealized_pnl": round(unrealized, 2),
                "realized_pnl": round(cash_pnl, 2),
                "position_limit": self._execution_engine.get_limit(p) if self._execution_engine else 20,
            }
        return pos_dict

    def _compute_strategy_pnl(self, timestamp: int) -> dict:
        """Compute mark-to-market PnL (same as backtest engine)."""
        total_pnl = 0.0
        total_cash = sum(self._profit_loss.values())

        for product in self._positions:
            cash = self._profit_loss.get(product, 0.0)
            pos = self._positions.get(product, 0)
            mid = self._mid_prices.get(product, 0.0)
            total_pnl += cash + pos * mid

        return {
            "timestamp": timestamp,
            "realized_pnl": round(total_cash, 2),
            "unrealized_pnl": round(total_pnl - total_cash, 2),
            "total_pnl": round(total_pnl, 2),
            "inventory": {p: q for p, q in self._positions.items() if q != 0},
            "cash": round(total_cash, 2),
        }

    def step_backward(self) -> dict:
        """Step one event backward."""
        event = self._engine.step_backward()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        return {
            "done": False,
            "event": event.model_dump(),
            **self._engine.get_session_state(),
        }

    def seek(self, timestamp: int) -> dict:
        """Seek to the nearest event at the given timestamp."""
        event = self._engine.seek(timestamp)
        if event is None:
            return {"error": "Empty event stream"}

        self._state.reset()
        for ev in self._engine.get_events_up_to_current():
            self._state.process_event(ev)

        return {
            "event": event.model_dump(),
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    def set_speed(self, speed: float) -> None:
        self._engine.set_speed(speed)

    def get_state(self) -> dict:
        return {
            "engine": self._engine.get_session_state(),
            "state": self._state.get_state_snapshot(),
        }

    def reset(self) -> None:
        self._engine.stop()
        self._state.reset()

    # ------------------------------------------------------------------
    # Convenience jumps
    # ------------------------------------------------------------------

    def jump_next_trade(self) -> dict:
        event = self._engine.jump_to_next_trade()
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

    def jump_next_fill(self) -> dict:
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
    # Accessors
    # ------------------------------------------------------------------

    @property
    def engine(self) -> ReplayEngine:
        return self._engine

    @property
    def state(self) -> ReplayState:
        return self._state
