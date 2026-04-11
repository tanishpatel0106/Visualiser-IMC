"""Backtest engine for the IMC Prosperity trading terminal.

Implements Prosperity-accurate backtesting semantics based on the
reference backtester (nabayansaha/imc-prosperity-4-backtester):

• Strategy is called **once per timestamp** with all products' state.
• Orders are matched against the order book (consuming volume) and
  then against market trades, with configurable matching modes.
• PnL uses simple cash-flow accounting:
    profit_loss[product] -= price * volume   (for buys)
    profit_loss[product] += price * volume   (for sells)
  Mark-to-market: total_pnl = sum(profit_loss[p] + position[p] * mid_price[p])
• Position limits use aggregate pre-check + per-fill clamping.
"""

import copy
import math
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from app.engines.execution.engine import ExecutionEngine, MarketTrade
from app.engines.orderbook.book import OrderBookEngine
from app.engines.sandbox.adapter import ProsperityAdapter
from app.engines.sandbox.runner import StrategySandbox
from app.models.analytics import ExecutionMetrics, PerformanceMetrics
from app.models.backtest import BacktestConfig, BacktestRun
from app.models.events import Event, EventType
from app.models.market import (
    MarketSnapshot,
    OrderSide,
    TradePrint,
    VisibleOrderBook,
)
from app.models.strategy import DebugFrame
from app.models.trading import (
    FillEvent,
    PnLState,
    StrategyOrder,
)


class BacktestEngine:
    """Drives a full backtest run against historical event data.

    The engine groups events by timestamp and for each timestamp:
    1. Updates order books from all BOOK_SNAPSHOT events.
    2. Collects market trades from all TRADE_PRINT events.
    3. Builds a Prosperity-compatible TradingState (all products).
    4. Calls the strategy's ``run`` method **once**.
    5. Enforces position limits (aggregate pre-check).
    6. Matches orders against order book + market trades.
    7. Updates positions and cash-flow PnL.
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

        # Core sub-engines
        self._book_engine = OrderBookEngine()
        self._execution_engine = ExecutionEngine(
            trade_matching_mode=config.get_trade_matching(),
            position_limits=config.position_limits,
            default_limit=50,
        )
        self._adapter = ProsperityAdapter()

        # Position and PnL tracking (cash-flow based, like Prosperity)
        self._positions: dict[str, int] = {}
        self._profit_loss: dict[str, float] = {}  # cash PnL per product

        # Result collectors
        self._fills: list[FillEvent] = []
        self._pnl_history: list[PnLState] = []
        self._debug_frames: list[DebugFrame] = []
        self._all_orders: list[StrategyOrder] = []

        # Trade buffers for strategy visibility (Prosperity semantics):
        # • own_trades   – fills from the PREVIOUS tick (cleared after strategy sees them)
        # • market_trades – LEFTOVER (unconsumed) market trades from the previous
        #                   tick's matching phase.  NOT a rolling buffer.
        self._own_trades: dict[str, list[TradePrint]] = {}
        self._market_trades: dict[str, list[TradePrint]] = {}

        # Strategy trader_data persistence across ticks
        self._trader_data: str = json.dumps(config.parameters or {})

        # Track mid prices for mark-to-market
        self._mid_prices: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(
        self,
        events: list[Event],
        strategy_callable: Any,
    ) -> BacktestRun:
        """Execute the backtest over the provided event stream."""
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
    # Event processing – grouped by timestamp
    # ------------------------------------------------------------------

    def _execute_events(self, events: list[Event], strategy: Any) -> None:
        """Group events by timestamp and process each group."""
        sandbox = StrategySandbox(timeout=5.0)
        products = self._config.products or []

        # Initialize product state
        for p in products:
            self._positions.setdefault(p, 0)
            self._profit_loss.setdefault(p, 0.0)
            self._own_trades.setdefault(p, [])
            self._market_trades.setdefault(p, [])

        # Group events by timestamp
        events_by_ts: dict[int, dict[str, list[Event]]] = {}
        for event in events:
            ts = event.timestamp
            if ts not in events_by_ts:
                events_by_ts[ts] = {"snapshots": [], "trades": []}
            if event.event_type == EventType.BOOK_SNAPSHOT:
                events_by_ts[ts]["snapshots"].append(event)
            elif event.event_type == EventType.TRADE_PRINT:
                events_by_ts[ts]["trades"].append(event)

        # Process timestamps in order
        for ts in sorted(events_by_ts.keys()):
            group = events_by_ts[ts]
            self._process_timestamp(
                ts, group["snapshots"], group["trades"],
                strategy, sandbox, products,
            )

    def _process_timestamp(
        self,
        timestamp: int,
        snapshot_events: list[Event],
        trade_events: list[Event],
        strategy: Any,
        sandbox: StrategySandbox,
        products: list[str],
    ) -> None:
        """Process all events at a single timestamp.

        This is the core simulation tick, matching Prosperity semantics:
        1. Update all order books from snapshots.
        2. Collect market trades (wrapped as MarketTrade for capacity tracking).
        3. Build TradingState and run strategy once.
        4. Enforce aggregate position limits.
        5. Match orders product-by-product against book + market trades.
        6. Update PnL and record state.
        """
        # ── Step 1: Update order books ──
        for event in snapshot_events:
            product = event.product or ""
            data = event.data
            snapshot = MarketSnapshot(
                day=data.get("day", 0),
                timestamp=timestamp,
                product=product,
                bid_prices=data.get("bid_prices", []),
                bid_volumes=data.get("bid_volumes", []),
                ask_prices=data.get("ask_prices", []),
                ask_volumes=data.get("ask_volumes", []),
                mid_price=data.get("mid_price"),
            )
            self._book_engine.update_from_snapshot(snapshot)

            # Discover products dynamically
            if product and product not in products:
                products.append(product)
                self._positions.setdefault(product, 0)
                self._profit_loss.setdefault(product, 0.0)
                self._own_trades.setdefault(product, [])
                self._market_trades.setdefault(product, [])

        # ── Step 2: Collect market trades for this timestamp ──
        # These MarketTrade wrappers are used for MATCHING only.
        # The strategy sees previous tick's leftovers (self._market_trades),
        # not this tick's raw trades.
        ts_market_trades: dict[str, list[MarketTrade]] = defaultdict(list)

        for event in trade_events:
            data = event.data
            product = event.product or data.get("symbol", "")
            trade = TradePrint(
                timestamp=timestamp,
                buyer=data.get("buyer", ""),
                seller=data.get("seller", ""),
                symbol=product,
                price=data.get("price", 0.0),
                quantity=data.get("quantity", 0),
                aggressor_side=data.get("aggressor_side"),
            )
            ts_market_trades[product].append(MarketTrade.from_trade_print(trade))

        # Skip strategy call if no snapshots at this timestamp
        if not snapshot_events:
            return

        # ── Step 3: Build Prosperity TradingState ──
        # state.market_trades = previous tick's leftover trades (already in self._market_trades)
        books = {p: self._book_engine.get_current_book(p) for p in products}

        # Update mid prices for mark-to-market
        for p in products:
            book = books.get(p)
            if book is not None and book.mid_price is not None:
                self._mid_prices[p] = book.mid_price

        state = self._adapter.build_state(
            timestamp=timestamp,
            products=products,
            books=books,
            positions=self._positions,
            own_trades=self._own_trades,
            market_trades=self._market_trades,
            trader_data=self._trader_data,
        )

        # ── Step 4: Execute strategy ──
        raw_orders, conversions, trader_data = sandbox.execute_strategy(
            strategy, state, timeout=1.0,
        )
        if isinstance(trader_data, str) and not trader_data.startswith("ERROR:"):
            self._trader_data = trader_data

        # Clear own-trade buffer (strategy has seen them)
        for p in products:
            self._own_trades[p] = []

        # ── Step 5: Apply conversions ──
        if conversions != 0:
            self._apply_conversions(conversions, state, products, timestamp)

        # ── Step 6: Enforce aggregate position limits ──
        if not isinstance(raw_orders, dict):
            raw_orders = {}

        checked_orders = self._execution_engine.enforce_limits(raw_orders)

        # ── Step 7: Match orders product-by-product ──
        tick_fills: list[FillEvent] = []
        tick_orders: list[StrategyOrder] = []

        for product, orders in checked_orders.items():
            if not orders:
                continue

            # Convert to StrategyOrder for tracking
            for order in orders:
                qty = getattr(order, "quantity", 0)
                if qty == 0:
                    continue
                tick_orders.append(StrategyOrder(
                    order_id=str(uuid.uuid4()),
                    product=product,
                    side=OrderSide.BUY if qty > 0 else OrderSide.SELL,
                    price=float(getattr(order, "price", 0)),
                    quantity=abs(qty),
                    timestamp=timestamp,
                    created_at=timestamp,
                ))

            # Build mutable copies of order depth for this product
            book = books.get(product)
            if book is None:
                continue

            buy_depth: dict[int, int] = {}
            sell_depth: dict[int, int] = {}
            for level in book.bids:
                buy_depth[int(level.price)] = level.volume
            for level in book.asks:
                sell_depth[int(level.price)] = -level.volume  # Prosperity: negative

            product_fills = self._execution_engine.match_orders(
                product=product,
                orders=orders,
                buy_orders=buy_depth,
                sell_orders=sell_depth,
                market_trades=ts_market_trades.get(product, []),
                timestamp=timestamp,
            )
            tick_fills.extend(product_fills)

        self._all_orders.extend(tick_orders)

        # ── Step 8: Process fills – update PnL and positions ──
        self._process_fills(tick_fills, timestamp)

        # ── Step 9: Compute leftover market trades for next tick ──
        # After matching, any MarketTrade with remaining_quantity > 0
        # becomes state.market_trades for the next tick.
        for product, mts in ts_market_trades.items():
            leftovers = [
                TradePrint(
                    timestamp=mt.timestamp,
                    buyer=mt.buyer,
                    seller=mt.seller,
                    symbol=mt.symbol,
                    price=mt.price,
                    quantity=mt.remaining_quantity,
                )
                for mt in mts
                if mt.remaining_quantity > 0
            ]
            self._market_trades[product] = leftovers
        # Products with no trades this tick keep their existing leftovers
        # (matches reference: prepare_state doesn't clear market_trades)

        # ── Step 8: Record PnL snapshot (mark-to-market) ──
        pnl_state = self._build_pnl_state(timestamp)
        self._pnl_history.append(pnl_state)

        # ── Step 9: Build debug frame ──
        primary_book = None
        primary_product = ""
        if snapshot_events:
            primary_product = snapshot_events[0].product or ""
            primary_book = books.get(primary_product)
        if primary_book is None:
            primary_book = VisibleOrderBook(product="", timestamp=timestamp)

        debug_frame = self._build_debug_frame(
            timestamp, primary_product, primary_book,
            tick_orders, tick_fills, raw_orders,
        )
        self._debug_frames.append(debug_frame)

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    def _apply_conversions(
        self,
        conversions: int,
        state: Any,
        products: list[str],
        timestamp: int,
    ) -> None:
        """Apply conversions for products with ConversionObservation data.

        In Prosperity, the strategy returns a single integer ``conversions``.
        For each product that has a ConversionObservation in the state's
        observations, the conversion adjusts position and cash:

        * conversions > 0 (import/buy from south):
            cost = (askPrice + transportFees + importTariff) * conversions
            position += conversions
        * conversions < 0 (export/sell to south):
            revenue = (bidPrice − transportFees − exportTariff) * |conversions|
            position += conversions  (negative, so position decreases)

        If no product has ConversionObservation data, this is a no-op.
        """
        observations = getattr(state, "observations", None)
        if observations is None:
            return

        conv_obs_map = getattr(observations, "conversionObservations", {})
        if not conv_obs_map:
            return

        for product, conv_obs in conv_obs_map.items():
            if not hasattr(conv_obs, "askPrice"):
                continue

            if conversions > 0:
                cost_per_unit = (
                    conv_obs.askPrice + conv_obs.transportFees + conv_obs.importTariff
                )
                self._profit_loss[product] = (
                    self._profit_loss.get(product, 0.0) - cost_per_unit * conversions
                )
                self._positions[product] = (
                    self._positions.get(product, 0) + conversions
                )
            elif conversions < 0:
                revenue_per_unit = (
                    conv_obs.bidPrice - conv_obs.transportFees - conv_obs.exportTariff
                )
                self._profit_loss[product] = (
                    self._profit_loss.get(product, 0.0)
                    + revenue_per_unit * abs(conversions)
                )
                self._positions[product] = (
                    self._positions.get(product, 0) + conversions
                )

            # Sync position with execution engine
            self._execution_engine.update_position(
                product, self._positions[product]
            )

    # ------------------------------------------------------------------
    # Fill processing – cash-flow PnL
    # ------------------------------------------------------------------

    def _process_fills(self, fills: list[FillEvent], timestamp: int) -> None:
        """Apply fills using simple cash-flow PnL (Prosperity style).

        Buy:  profit_loss[product] -= price * volume
              position[product] += volume
        Sell: profit_loss[product] += price * volume
              position[product] -= volume
        """
        for fill in fills:
            self._fills.append(fill)
            product = fill.product

            if fill.side == OrderSide.BUY:
                self._profit_loss[product] = (
                    self._profit_loss.get(product, 0.0) - fill.price * fill.quantity
                )
                self._positions[product] = self._positions.get(product, 0) + fill.quantity
            else:
                self._profit_loss[product] = (
                    self._profit_loss.get(product, 0.0) + fill.price * fill.quantity
                )
                self._positions[product] = self._positions.get(product, 0) - fill.quantity

            # Sync position with execution engine
            self._execution_engine.update_position(product, self._positions[product])

            # Buffer as own trade for strategy visibility on next tick
            own_trade = TradePrint(
                timestamp=fill.timestamp or timestamp,
                buyer="SUBMISSION" if fill.side == OrderSide.BUY else "",
                seller="" if fill.side == OrderSide.BUY else "SUBMISSION",
                symbol=product,
                price=fill.price,
                quantity=fill.quantity,
            )
            self._own_trades.setdefault(product, []).append(own_trade)

    # ------------------------------------------------------------------
    # PnL snapshot – mark-to-market
    # ------------------------------------------------------------------

    def _build_pnl_state(self, timestamp: int) -> PnLState:
        """Build a point-in-time PnL snapshot.

        total_pnl = sum over products of (profit_loss[p] + position[p] * mid_price[p])
        """
        total_pnl = 0.0
        total_cash = sum(self._profit_loss.values())

        for product in self._positions:
            cash_pnl = self._profit_loss.get(product, 0.0)
            pos = self._positions.get(product, 0)
            mid = self._mid_prices.get(product, 0.0)
            product_pnl = cash_pnl + pos * mid
            total_pnl += product_pnl

        return PnLState(
            timestamp=timestamp,
            realized_pnl=total_cash,  # Cash PnL (all realized trades)
            unrealized_pnl=total_pnl - total_cash,  # Position mark-to-market
            total_pnl=total_pnl,
            inventory={p: q for p, q in self._positions.items()},
            cash=total_cash,
        )

    # ------------------------------------------------------------------
    # Debug frame
    # ------------------------------------------------------------------

    def _build_debug_frame(
        self,
        timestamp: int,
        product: str,
        book: VisibleOrderBook,
        orders: list[StrategyOrder],
        fills: list[FillEvent],
        raw_orders: Any,
    ) -> DebugFrame:
        """Build a debug frame capturing state at this timestamp."""
        last_pnl = self._pnl_history[-1] if self._pnl_history else None

        return DebugFrame(
            timestamp=timestamp,
            product=product,
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
                "realized": last_pnl.realized_pnl if last_pnl else 0.0,
                "unrealized": last_pnl.unrealized_pnl if last_pnl else 0.0,
                "total": last_pnl.total_pnl if last_pnl else 0.0,
                "cash": last_pnl.cash if last_pnl else 0.0,
            },
            warnings=[],
        )

    # ------------------------------------------------------------------
    # Metrics computation
    # ------------------------------------------------------------------

    def _compute_performance_metrics(self) -> PerformanceMetrics:
        """Compute aggregate performance metrics from the completed run."""
        last_pnl = self._pnl_history[-1] if self._pnl_history else None
        total_pnl = last_pnl.total_pnl if last_pnl else 0.0
        total_realized = last_pnl.realized_pnl if last_pnl else 0.0
        total_unrealized = last_pnl.unrealized_pnl if last_pnl else 0.0

        # Per-product PnL
        pnl_by_product: dict[str, float] = {}
        for product in self._positions:
            cash = self._profit_loss.get(product, 0.0)
            pos = self._positions.get(product, 0)
            mid = self._mid_prices.get(product, 0.0)
            pnl_by_product[product] = cash + pos * mid

        # Trade-level analysis (group fills into round trips)
        trade_pnls = self._compute_trade_pnls()
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        num_trades = len(trade_pnls)

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        win_rate = len(wins) / num_trades if num_trades > 0 else 0.0
        turnover = sum(f.price * f.quantity for f in self._fills)
        return_per_trade = total_pnl / num_trades if num_trades > 0 else 0.0

        max_dd, dd_duration = self._compute_max_drawdown()
        sharpe, vol = self._compute_sharpe()

        # Inventory stats
        inventory_values = [
            sum(abs(v) for v in snap.inventory.values())
            for snap in self._pnl_history
        ]
        avg_inventory = sum(inventory_values) / len(inventory_values) if inventory_values else 0.0
        max_inventory = max(inventory_values) if inventory_values else 0.0

        # Profit factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0
            else 999.0 if gross_profit > 0
            else 0.0
        )

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

        aggressive_fills = [f for f in self._fills if f.is_aggressive]
        passive_fills = [f for f in self._fills if not f.is_aggressive]
        aggressive_vol = sum(f.quantity for f in aggressive_fills)
        passive_vol = sum(f.quantity for f in passive_fills)
        total_vol = aggressive_vol + passive_vol

        pa_ratio = (
            passive_vol / aggressive_vol if aggressive_vol > 0
            else float("inf") if passive_vol > 0
            else 0.0
        )
        avg_fill_size = total_vol / fill_count if fill_count > 0 else 0.0

        return ExecutionMetrics(
            num_orders=num_orders,
            fill_count=fill_count,
            full_fill_rate=0.0,
            partial_fill_rate=0.0,
            cancel_count=0,
            reject_count=0,
            avg_fill_delay=0.0,
            effective_spread_captured=0.0,
            passive_aggressive_ratio=pa_ratio,
            estimated_slippage=0.0,
            avg_fill_size=avg_fill_size,
            total_volume_traded=total_vol,
            maker_volume=passive_vol,
            taker_volume=aggressive_vol,
        )

    def _compute_trade_pnls(self) -> list[float]:
        """Approximate per-trade PnL using FIFO round-trip pairing."""
        open_entries: dict[str, list[tuple[float, int, OrderSide]]] = {}
        trade_pnls: list[float] = []

        for fill in self._fills:
            product = fill.product
            entries = open_entries.setdefault(product, [])

            if not entries or entries[0][2] == fill.side:
                entries.append((fill.price, fill.quantity, fill.side))
            else:
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

                if remaining_close > 0:
                    entries.append((fill.price, remaining_close, fill.side))

        return trade_pnls

    def _compute_max_drawdown(self) -> tuple[float, int]:
        """Compute max drawdown and its duration from PnL history."""
        if not self._pnl_history:
            return 0.0, 0

        peak = self._pnl_history[0].total_pnl
        max_dd = 0.0
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
        """Compute annualized Sharpe ratio and PnL volatility."""
        if len(self._pnl_history) < 2:
            return 0.0, 0.0

        returns = [
            self._pnl_history[i].total_pnl - self._pnl_history[i - 1].total_pnl
            for i in range(1, len(self._pnl_history))
        ]

        if not returns:
            return 0.0, 0.0

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(variance) if variance > 0 else 0.0

        if std_ret == 0:
            return 0.0, 0.0

        ticks_per_year = 1000 * 252
        sharpe = (mean_ret / std_ret) * math.sqrt(ticks_per_year)
        return sharpe, std_ret

    @staticmethod
    def _compute_consecutive(trade_pnls: list[float]) -> tuple[int, int]:
        max_wins = max_losses = current_wins = current_losses = 0
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
                current_wins = current_losses = 0
        return max_wins, max_losses

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_debug_frames(self) -> list[DebugFrame]:
        return list(self._debug_frames)

    def get_pnl_history(self) -> list[PnLState]:
        return list(self._pnl_history)

    def get_fills(self) -> list[FillEvent]:
        return list(self._fills)


# =====================================================================
# Module-level helpers
# =====================================================================

def _sanitize_floats(obj):
    """Replace NaN/Inf floats with 0.0 for JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj
