"""Backtest engine for the IMC Prosperity trading terminal.

Orchestrates the full backtest lifecycle: iterates through historical
market events, feeds them to a strategy via the Prosperity adapter,
processes resulting orders through the execution engine, tracks
positions, inventory, and PnL, and produces a complete BacktestRun
with debug frames and performance metrics.
"""

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend.app.engines.execution.engine import ExecutionEngine
from backend.app.engines.orderbook.book import OrderBookEngine
from backend.app.engines.sandbox.adapter import ProsperityAdapter
from backend.app.engines.sandbox.runner import StrategySandbox
from backend.app.models.analytics import ExecutionMetrics, PerformanceMetrics
from backend.app.models.backtest import BacktestConfig, BacktestRun, ExecutionModel
from backend.app.models.events import Event, EventType
from backend.app.models.market import (
    MarketSnapshot,
    OrderSide,
    TradePrint,
    VisibleOrderBook,
)
from backend.app.models.strategy import DebugFrame
from backend.app.models.trading import (
    FillEvent,
    InventoryState,
    PnLState,
    PositionState,
    StrategyOrder,
)


class BacktestEngine:
    """Drives a full backtest run against historical event data.

    The engine replays events in chronological order. On each
    BOOK_SNAPSHOT event it:

    1. Updates the internal order book via OrderBookEngine.
    2. Checks for passive fills on any resting orders.
    3. Builds a Prosperity-compatible TradingState.
    4. Calls the strategy's ``run`` method.
    5. Processes the strategy's orders through ExecutionEngine.
    6. Updates positions, PnL, and debug frames.

    TRADE_PRINT events update the recent-trade buffer and are also
    checked for passive fills.

    Parameters
    ----------
    config : BacktestConfig
        Full backtest configuration (strategy, products, execution model,
        position limits, fees, slippage, etc.).
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

        # Core sub-engines
        self._book_engine = OrderBookEngine()
        self._execution_engine = ExecutionEngine(
            execution_model=config.execution_model,
            position_limits=config.position_limits,
            fees=config.fees,
            slippage=config.slippage,
        )
        self._adapter = ProsperityAdapter()

        # State accumulators
        self._positions: dict[str, int] = {}          # product -> net qty
        self._avg_entry_prices: dict[str, float] = {} # product -> avg entry
        self._cash: float = config.initial_cash
        self._realized_pnl: dict[str, float] = {}     # product -> realized pnl

        # Result collectors
        self._fills: list[FillEvent] = []
        self._pnl_history: list[PnLState] = []
        self._debug_frames: list[DebugFrame] = []
        self._all_orders: list[StrategyOrder] = []

        # Recent trades buffer: product -> list of recent TradePrints
        self._recent_trades: dict[str, list[TradePrint]] = {}
        # Own trades (fills) buffer: product -> list of TradePrints
        # Reset each tick so the strategy only sees new fills.
        self._own_trades_buffer: dict[str, list[TradePrint]] = {}

        # Strategy trader_data persistence across ticks
        self._trader_data: str = ""

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(
        self,
        events: list[Event],
        strategy_callable: Any,
    ) -> BacktestRun:
        """Execute the backtest over the provided event stream.

        Parameters
        ----------
        events:
            Chronologically ordered list of Event objects.
        strategy_callable:
            An instance of a Trader class with a ``run(state)`` method
            (as produced by StrategySandbox.load_strategy).

        Returns
        -------
        A fully populated BacktestRun with metrics, status, and timing.
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        run = BacktestRun(
            run_id=run_id,
            config=self._config,
            status="running",
            started_at=started_at,
        )

        try:
            self._execute_events(events, strategy_callable)

            # Compute final metrics
            perf_metrics = self._compute_performance_metrics()
            exec_metrics = self._compute_execution_metrics()

            run.metrics = _sanitize_floats({
                "performance": perf_metrics.model_dump(),
                "execution": exec_metrics.model_dump(),
                "pnl_history": [p.model_dump() for p in self._pnl_history],
                "total_fills": len(self._fills),
                "total_orders": len(self._all_orders),
            })
            run.status = "completed"

        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)

        run.completed_at = datetime.now(timezone.utc).isoformat()
        return run

    # ------------------------------------------------------------------
    # Event processing loop
    # ------------------------------------------------------------------

    def _execute_events(self, events: list[Event], strategy: Any) -> None:
        """Iterate through events and drive the simulation."""
        sandbox = StrategySandbox(timeout=5.0)

        for event in events:
            if event.event_type == EventType.BOOK_SNAPSHOT:
                self._handle_book_snapshot(event, strategy, sandbox)

            elif event.event_type == EventType.TRADE_PRINT:
                self._handle_trade_print(event)

    def _handle_book_snapshot(
        self, event: Event, strategy: Any, sandbox: StrategySandbox
    ) -> None:
        """Process a BOOK_SNAPSHOT event: update book, run strategy,
        process orders, record state."""
        product = event.product or ""
        data = event.data

        # Rebuild the order book from snapshot data
        snapshot = MarketSnapshot(
            day=data.get("day", 0),
            timestamp=event.timestamp,
            product=product,
            bid_prices=data.get("bid_prices", []),
            bid_volumes=data.get("bid_volumes", []),
            ask_prices=data.get("ask_prices", []),
            ask_volumes=data.get("ask_volumes", []),
            mid_price=data.get("mid_price"),
        )
        book = self._book_engine.update_from_snapshot(snapshot)

        # Check for passive fills on resting orders
        recent = self._recent_trades.get(product, [])
        passive_fills = self._execution_engine.check_passive_fills(book, recent)
        self._process_fills(passive_fills, book)

        # Build Prosperity-compatible state for the strategy
        products = self._config.products or [product]
        books = {p: self._book_engine.get_current_book(p) or book for p in products}

        state = self._adapter.build_state(
            timestamp=event.timestamp,
            products=products,
            books=books,
            positions=self._positions,
            own_trades=self._own_trades_buffer,
            market_trades=self._recent_trades,
            trader_data=self._trader_data,
        )

        # Execute strategy
        raw_orders, conversions, trader_data = sandbox.execute_strategy(
            strategy, state, timeout=1.0
        )
        self._trader_data = trader_data if not trader_data.startswith("ERROR:") else self._trader_data

        # Clear own-trade buffer for next tick (strategy has seen them)
        self._own_trades_buffer = {p: [] for p in products}

        # Convert strategy output to internal orders
        strategy_orders = self._process_strategy_output(raw_orders, event.timestamp)
        self._all_orders.extend(strategy_orders)

        # Process each order through the execution engine
        tick_fills: list[FillEvent] = []
        for order in strategy_orders:
            fills = self._execution_engine.process_order(order, book, recent)
            tick_fills.extend(fills)

        self._process_fills(tick_fills, book)

        # Clear recent trades after processing (strategy + execution have seen them)
        self._recent_trades[product] = []

        # Record PnL snapshot
        pnl_state = self._build_pnl_state(event.timestamp, books)
        self._pnl_history.append(pnl_state)

        # Build debug frame
        debug_frame = self._build_debug_frame(
            event, book, strategy_orders, tick_fills + passive_fills, raw_orders
        )
        self._debug_frames.append(debug_frame)

    def _handle_trade_print(self, event: Event) -> None:
        """Process a TRADE_PRINT event: buffer the trade and check
        passive fills."""
        data = event.data
        product = event.product or data.get("symbol", "")

        trade = TradePrint(
            timestamp=event.timestamp,
            buyer=data.get("buyer", ""),
            seller=data.get("seller", ""),
            symbol=product,
            price=data.get("price", 0.0),
            quantity=data.get("quantity", 0),
            aggressor_side=data.get("aggressor_side"),
        )

        self._recent_trades.setdefault(product, []).append(trade)

        # Check passive fills using the latest known book for this product
        book = self._book_engine.get_current_book(product)
        if book is not None:
            passive_fills = self._execution_engine.check_passive_fills(
                book, [trade]
            )
            self._process_fills(passive_fills, book)

    # ------------------------------------------------------------------
    # Fill processing and position tracking
    # ------------------------------------------------------------------

    def _process_fills(
        self, fills: list[FillEvent], book: VisibleOrderBook
    ) -> None:
        """Apply fills to positions, cash, and PnL tracking."""
        for fill in fills:
            self._fills.append(fill)
            product = fill.product

            old_pos = self._positions.get(product, 0)
            old_avg = self._avg_entry_prices.get(product, 0.0)

            if fill.side == OrderSide.BUY:
                new_pos = old_pos + fill.quantity
                signed_qty = fill.quantity
            else:
                new_pos = old_pos - fill.quantity
                signed_qty = -fill.quantity

            # Update cash: buying costs money, selling earns money
            self._cash -= signed_qty * fill.price

            # Calculate realized PnL when reducing or flipping position
            realized = 0.0
            if old_pos != 0 and _sign(old_pos) != _sign(new_pos) or (
                old_pos != 0 and abs(new_pos) < abs(old_pos)
            ):
                # Closing (partially or fully) an existing position
                closing_qty = min(abs(signed_qty), abs(old_pos))
                if fill.side == OrderSide.SELL and old_pos > 0:
                    # Closing a long: profit = (sell_price - avg_entry) * qty
                    realized = (fill.price - old_avg) * closing_qty
                elif fill.side == OrderSide.BUY and old_pos < 0:
                    # Closing a short: profit = (avg_entry - buy_price) * qty
                    realized = (old_avg - fill.price) * closing_qty

                self._realized_pnl[product] = self._realized_pnl.get(product, 0.0) + realized

            # Update average entry price
            if new_pos == 0:
                self._avg_entry_prices[product] = 0.0
            elif _sign(new_pos) == _sign(old_pos) and abs(new_pos) > abs(old_pos):
                # Adding to position: update weighted average
                total = abs(old_pos) + abs(signed_qty)
                self._avg_entry_prices[product] = (
                    old_avg * abs(old_pos) + fill.price * abs(signed_qty)
                ) / total
            elif _sign(new_pos) != _sign(old_pos):
                # Flipped direction: new entry price is the fill price
                self._avg_entry_prices[product] = fill.price
            # else: reducing position, avg entry stays the same

            self._positions[product] = new_pos

            # Sync position with execution engine for limit checks
            self._execution_engine.update_position(product, new_pos)

            # Buffer as own trade for strategy visibility on next tick
            own_trade = TradePrint(
                timestamp=fill.timestamp,
                buyer="STRATEGY" if fill.side == OrderSide.BUY else "MARKET",
                seller="MARKET" if fill.side == OrderSide.BUY else "STRATEGY",
                symbol=product,
                price=fill.price,
                quantity=fill.quantity,
            )
            self._own_trades_buffer.setdefault(product, []).append(own_trade)

    # ------------------------------------------------------------------
    # Strategy output conversion
    # ------------------------------------------------------------------

    def _process_strategy_output(
        self, raw_orders: Any, timestamp: int
    ) -> list[StrategyOrder]:
        """Convert raw strategy output (Prosperity order dict) to
        internal StrategyOrder list."""
        if not isinstance(raw_orders, dict):
            return []

        return self._adapter.parse_orders(raw_orders, timestamp=timestamp)

    # ------------------------------------------------------------------
    # State builders
    # ------------------------------------------------------------------

    def _build_strategy_state(
        self,
        event: Event,
        book: VisibleOrderBook,
        positions: dict[str, int],
        trader_data: str,
    ) -> dict:
        """Build a raw state dict (non-Prosperity format) for reference.

        This is the internal representation; the actual strategy receives
        a TradingState object built by ProsperityAdapter.
        """
        return {
            "timestamp": event.timestamp,
            "product": event.product,
            "book": {
                "bids": [(l.price, l.volume) for l in book.bids],
                "asks": [(l.price, l.volume) for l in book.asks],
                "mid_price": book.mid_price,
                "spread": book.spread,
            },
            "positions": dict(positions),
            "trader_data": trader_data,
        }

    def _build_pnl_state(
        self, timestamp: int, books: dict[str, VisibleOrderBook]
    ) -> PnLState:
        """Capture a point-in-time PnL snapshot."""
        total_realized = sum(self._realized_pnl.values())
        total_unrealized = 0.0

        for product, qty in self._positions.items():
            if qty == 0:
                continue
            mark = _get_mark_price(books.get(product))
            if mark is not None:
                avg = self._avg_entry_prices.get(product, 0.0)
                if qty > 0:
                    total_unrealized += (mark - avg) * qty
                else:
                    total_unrealized += (avg - mark) * abs(qty)

        return PnLState(
            timestamp=timestamp,
            realized_pnl=total_realized,
            unrealized_pnl=total_unrealized,
            total_pnl=total_realized + total_unrealized,
            inventory={p: q for p, q in self._positions.items()},
            cash=self._cash,
        )

    def _build_debug_frame(
        self,
        event: Event,
        book: VisibleOrderBook,
        orders: list[StrategyOrder],
        fills: list[FillEvent],
        raw_orders: Any,
    ) -> DebugFrame:
        """Build a debug frame capturing full state at this timestamp."""
        warnings: list[str] = []

        # Warn about rejected orders
        for order in orders:
            if order.status.value == "REJECTED":
                warnings.append(
                    f"Order {order.order_id[:8]} REJECTED: "
                    f"{order.side.value} {order.quantity} {order.product} @ {order.price}"
                )

        return DebugFrame(
            timestamp=event.timestamp,
            product=event.product or "",
            market_state={
                "mid_price": book.mid_price,
                "spread": book.spread,
                "best_bid": book.best_bid,
                "best_ask": book.best_ask,
                "bid_depth": book.total_bid_depth,
                "ask_depth": book.total_ask_depth,
            },
            strategy_inputs={
                "positions": dict(self._positions),
                "trader_data_length": len(self._trader_data),
            },
            strategy_outputs={
                "raw_orders": str(raw_orders) if raw_orders else "{}",
                "num_orders": len(orders),
            },
            orders_submitted=[o.model_dump() for o in orders],
            fills=[f.model_dump() for f in fills],
            position={p: q for p, q in self._positions.items()},
            pnl={
                "realized": sum(self._realized_pnl.values()),
                "unrealized": self._pnl_history[-1].unrealized_pnl if self._pnl_history else 0.0,
                "total": self._pnl_history[-1].total_pnl if self._pnl_history else 0.0,
                "cash": self._cash,
            },
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Metrics computation
    # ------------------------------------------------------------------

    def _compute_performance_metrics(self) -> PerformanceMetrics:
        """Compute aggregate performance metrics from the completed run."""
        total_realized = sum(self._realized_pnl.values())

        # Unrealized from last PnL snapshot
        total_unrealized = self._pnl_history[-1].unrealized_pnl if self._pnl_history else 0.0
        total_pnl = total_realized + total_unrealized

        # Per-product PnL
        pnl_by_product: dict[str, float] = {}
        for product in self._realized_pnl:
            pnl_by_product[product] = self._realized_pnl[product]

        # Trade-level analysis
        # Group fills into round-trip trades for win/loss analysis
        trade_pnls = self._compute_trade_pnls()
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        num_trades = len(trade_pnls)

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        win_rate = len(wins) / num_trades if num_trades > 0 else 0.0

        # Turnover: total volume * price
        turnover = sum(f.price * f.quantity for f in self._fills)

        # Return per trade
        return_per_trade = total_pnl / num_trades if num_trades > 0 else 0.0

        # Max drawdown from PnL curve
        max_dd, dd_duration = self._compute_max_drawdown()

        # Sharpe ratio (from PnL time series, assuming per-tick returns)
        sharpe, vol = self._compute_sharpe()

        # Inventory stats
        inventory_values = []
        for snap in self._pnl_history:
            inv = sum(abs(v) for v in snap.inventory.values())
            inventory_values.append(inv)

        avg_inventory = sum(inventory_values) / len(inventory_values) if inventory_values else 0.0
        max_inventory = max(inventory_values) if inventory_values else 0.0

        # Profit factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0 if gross_profit > 0 else 0.0

        # Consecutive wins/losses
        max_consec_wins, max_consec_losses = self._compute_consecutive(trade_pnls)

        return PerformanceMetrics(
            total_pnl=total_pnl,
            realized_pnl=total_realized,
            unrealized_pnl=total_unrealized,
            pnl_by_product=pnl_by_product,
            return_per_trade=return_per_trade,
            avg_win=avg_win,
            avg_loss=avg_loss,
            win_rate=win_rate,
            num_trades=num_trades,
            turnover=turnover,
            max_drawdown=max_dd,
            drawdown_duration=dd_duration,
            sharpe_ratio=sharpe,
            pnl_volatility=vol,
            avg_inventory=avg_inventory,
            max_inventory=max_inventory,
            profit_factor=profit_factor,
            max_consecutive_wins=max_consec_wins,
            max_consecutive_losses=max_consec_losses,
        )

    def _compute_execution_metrics(self) -> ExecutionMetrics:
        """Compute execution quality metrics."""
        num_orders = len(self._all_orders)
        fill_count = len(self._fills)

        full_fills = sum(
            1 for o in self._all_orders if o.status.value == "FILLED"
        )
        partial_fills = sum(
            1 for o in self._all_orders if o.status.value == "PARTIAL_FILL"
        )
        cancels = sum(
            1 for o in self._all_orders if o.status.value == "CANCELLED"
        )
        rejects = sum(
            1 for o in self._all_orders if o.status.value == "REJECTED"
        )

        full_fill_rate = full_fills / num_orders if num_orders > 0 else 0.0
        partial_fill_rate = partial_fills / num_orders if num_orders > 0 else 0.0

        # Passive vs aggressive fills
        passive_fills = [f for f in self._fills if not f.is_aggressive]
        aggressive_fills = [f for f in self._fills if f.is_aggressive]
        passive_vol = sum(f.quantity for f in passive_fills)
        aggressive_vol = sum(f.quantity for f in aggressive_fills)
        total_vol = passive_vol + aggressive_vol

        pa_ratio = passive_vol / aggressive_vol if aggressive_vol > 0 else float("inf") if passive_vol > 0 else 0.0

        avg_fill_size = total_vol / fill_count if fill_count > 0 else 0.0

        return ExecutionMetrics(
            num_orders=num_orders,
            fill_count=fill_count,
            full_fill_rate=full_fill_rate,
            partial_fill_rate=partial_fill_rate,
            cancel_count=cancels,
            reject_count=rejects,
            avg_fill_delay=0.0,  # Would need order-to-fill timestamp tracking
            effective_spread_captured=0.0,  # Requires mid-price at fill time
            passive_aggressive_ratio=pa_ratio,
            estimated_slippage=self._config.slippage,
            avg_fill_size=avg_fill_size,
            total_volume_traded=total_vol,
            maker_volume=passive_vol,
            taker_volume=aggressive_vol,
        )

    def _compute_trade_pnls(self) -> list[float]:
        """Approximate per-trade PnL from fills.

        Groups fills into offsetting pairs (FIFO basis) and computes
        PnL for each completed round trip.
        """
        # Track open fill entries per product as FIFO queues
        open_entries: dict[str, list[tuple[float, int, OrderSide]]] = {}
        trade_pnls: list[float] = []

        for fill in self._fills:
            product = fill.product
            entries = open_entries.setdefault(product, [])

            if not entries or entries[0][2] == fill.side:
                # Same direction: adding to position
                entries.append((fill.price, fill.quantity, fill.side))
            else:
                # Opposite direction: closing position (FIFO)
                remaining_close = fill.quantity
                while remaining_close > 0 and entries and entries[0][2] != fill.side:
                    entry_price, entry_qty, entry_side = entries[0]
                    close_qty = min(remaining_close, entry_qty)

                    if entry_side == OrderSide.BUY:
                        pnl = (fill.price - entry_price) * close_qty
                    else:
                        pnl = (entry_price - fill.price) * close_qty

                    trade_pnls.append(pnl)

                    if close_qty >= entry_qty:
                        entries.pop(0)
                    else:
                        entries[0] = (entry_price, entry_qty - close_qty, entry_side)

                    remaining_close -= close_qty

                # Any leftover opens a new position in the fill direction
                if remaining_close > 0:
                    entries.append((fill.price, remaining_close, fill.side))

        return trade_pnls

    def _compute_max_drawdown(self) -> tuple[float, int]:
        """Compute maximum drawdown and its duration from PnL history."""
        if not self._pnl_history:
            return 0.0, 0

        peak = self._pnl_history[0].total_pnl
        max_dd = 0.0
        dd_start = 0
        max_dd_duration = 0
        current_dd_start = 0

        for i, snap in enumerate(self._pnl_history):
            if snap.total_pnl > peak:
                peak = snap.total_pnl
                current_dd_start = i
            else:
                dd = peak - snap.total_pnl
                if dd > max_dd:
                    max_dd = dd
                    max_dd_duration = i - current_dd_start

        return max_dd, max_dd_duration

    def _compute_sharpe(self) -> tuple[float, float]:
        """Compute annualized Sharpe ratio and PnL volatility.

        Uses tick-by-tick PnL changes. Assumes ~1000 ticks per day
        and 252 trading days for annualization (adjustable).
        """
        if len(self._pnl_history) < 2:
            return 0.0, 0.0

        returns = []
        for i in range(1, len(self._pnl_history)):
            ret = self._pnl_history[i].total_pnl - self._pnl_history[i - 1].total_pnl
            returns.append(ret)

        if not returns:
            return 0.0, 0.0

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(variance) if variance > 0 else 0.0

        if std_ret == 0:
            return 0.0, 0.0

        # Raw Sharpe per tick, then annualize (assuming ~1000 ticks/day, 252 days)
        ticks_per_year = 1000 * 252
        sharpe = (mean_ret / std_ret) * math.sqrt(ticks_per_year)

        return sharpe, std_ret

    @staticmethod
    def _compute_consecutive(trade_pnls: list[float]) -> tuple[int, int]:
        """Compute max consecutive wins and max consecutive losses."""
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for pnl in trade_pnls:
            if pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            elif pnl < 0:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0

        return max_wins, max_losses

    # ------------------------------------------------------------------
    # Public accessors for results
    # ------------------------------------------------------------------

    def get_debug_frames(self) -> list[DebugFrame]:
        """Return all debug frames collected during the run."""
        return list(self._debug_frames)

    def get_pnl_history(self) -> list[PnLState]:
        """Return the full PnL time series."""
        return list(self._pnl_history)

    def get_fills(self) -> list[FillEvent]:
        """Return all fills generated during the run."""
        return list(self._fills)


# =====================================================================
# Module-level helpers
# =====================================================================


def _sanitize_floats(obj):
    """Replace NaN/Inf floats with None for JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _sign(x: int) -> int:
    """Return the sign of an integer: -1, 0, or 1."""
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0


def _get_mark_price(book: Optional[VisibleOrderBook]) -> Optional[float]:
    """Extract a mark price from a book, preferring mid then best bid/ask."""
    if book is None:
        return None
    if book.mid_price is not None:
        return book.mid_price
    if book.best_bid is not None:
        return book.best_bid
    if book.best_ask is not None:
        return book.best_ask
    return None
