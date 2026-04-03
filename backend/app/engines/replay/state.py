"""Full replay state tracker built on top of the order-book engine.

Processes each event emitted by :class:`ReplayEngine` and maintains the
reconstructed world state (books, trades, orders, positions, PnL) at the
current point in time.
"""

from __future__ import annotations

from typing import Optional

from app.engines.orderbook.book import OrderBookEngine
from app.engines.orderbook.metrics import BookMetrics
from app.models.events import Event, EventType
from app.models.market import MarketSnapshot, TradePrint, VisibleOrderBook
from app.models.trading import (
    FillEvent,
    InventoryState,
    PnLState,
    PositionState,
    StrategyOrder,
)


class ReplayState:
    """Maintains the full reconstructed state at the current replay cursor.

    Designed to be driven event-by-event from a :class:`ReplayEngine`.
    Each call to :meth:`process_event` mutates internal state and returns
    a change-set dict describing what was updated so that downstream
    consumers (e.g. WebSocket broadcaster) can push minimal diffs.
    """

    # Maximum number of trades kept in the rolling tape.
    MAX_TAPE_LENGTH = 500

    def __init__(self) -> None:
        self._book_engine = OrderBookEngine()
        self._book_metrics = BookMetrics()

        # Order books: product -> VisibleOrderBook
        self._books: dict[str, VisibleOrderBook] = {}

        # Trade tape (most recent last)
        self._trade_tape: list[TradePrint] = []

        # Active orders: order_id -> StrategyOrder
        self._active_orders: dict[str, StrategyOrder] = {}

        # Positions / inventory: product -> PositionState
        self._positions: dict[str, PositionState] = {}

        # PnL history (append-only)
        self._pnl_history: list[PnLState] = []

        # Debug / diagnostic frames emitted by strategy
        self._debug_frames: list[dict] = []

        # Running cash balance
        self._cash: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_event(self, event: Event) -> dict:
        """Process a single event and return a dict of state changes.

        The returned dict always contains ``"event_type"`` and
        ``"timestamp"``; additional keys depend on the event kind.
        """
        changes: dict = {
            "event_type": event.event_type.value,
            "timestamp": event.timestamp,
            "product": event.product,
        }

        handler = _EVENT_HANDLERS.get(event.event_type)
        if handler is not None:
            handler(self, event, changes)

        return changes

    def get_state_snapshot(self) -> dict:
        """Return a full snapshot of all tracked state."""
        return {
            "books": {
                product: book.model_dump() for product, book in self._books.items()
            },
            "trade_tape": [t.model_dump() for t in self._trade_tape[-50:]],
            "active_orders": {
                oid: o.model_dump() for oid, o in self._active_orders.items()
            },
            "positions": {
                p: pos.model_dump() for p, pos in self._positions.items()
            },
            "pnl_history": [s.model_dump() for s in self._pnl_history[-200:]],
            "inventory": self._build_inventory().model_dump(),
            "debug_frames": self._debug_frames[-100:],
            "trade_count": len(self._trade_tape),
            "active_order_count": len(self._active_orders),
        }

    def reset(self) -> None:
        """Reset all internal state to initial values."""
        self._book_engine.reset()
        self._books.clear()
        self._trade_tape.clear()
        self._active_orders.clear()
        self._positions.clear()
        self._pnl_history.clear()
        self._debug_frames.clear()
        self._cash = 0.0

    # ------------------------------------------------------------------
    # Accessors (for external consumers that prefer typed objects)
    # ------------------------------------------------------------------

    @property
    def books(self) -> dict[str, VisibleOrderBook]:
        return dict(self._books)

    @property
    def trade_tape(self) -> list[TradePrint]:
        return list(self._trade_tape)

    @property
    def active_orders(self) -> dict[str, StrategyOrder]:
        return dict(self._active_orders)

    @property
    def positions(self) -> dict[str, PositionState]:
        return dict(self._positions)

    @property
    def pnl_history(self) -> list[PnLState]:
        return list(self._pnl_history)

    # ------------------------------------------------------------------
    # Event handlers (private, registered in _EVENT_HANDLERS)
    # ------------------------------------------------------------------

    def _handle_book_snapshot(self, event: Event, changes: dict) -> None:
        """Reconstruct a ``VisibleOrderBook`` from the event payload."""
        data = event.data
        snapshot = MarketSnapshot(
            day=data.get("day", 0),
            timestamp=event.timestamp,
            product=event.product or data.get("product", "UNKNOWN"),
            bid_prices=data.get("bid_prices", []),
            bid_volumes=data.get("bid_volumes", []),
            ask_prices=data.get("ask_prices", []),
            ask_volumes=data.get("ask_volumes", []),
            mid_price=data.get("mid_price"),
            profit_and_loss=data.get("profit_and_loss"),
        )

        book = self._book_engine.update_from_snapshot(snapshot)
        product = snapshot.product
        self._books[product] = book

        # Compute metrics (include previous book for quote-stability).
        history = self._book_engine.get_book_history(product)
        previous = history[-2] if len(history) >= 2 else None
        spread_stats = self._book_metrics.rolling_spread_stats(history, window=20)
        metrics = self._book_metrics.compute(
            book,
            previous=previous,
            rolling_mean_spread=spread_stats.get("mean"),
            rolling_std_spread=spread_stats.get("std"),
        )

        # Mark-to-market open positions against the new mid.
        self._mark_position(product, book.mid_price)

        changes["book"] = book.model_dump()
        changes["metrics"] = metrics

    def _handle_trade_print(self, event: Event, changes: dict) -> None:
        """Append a trade to the tape."""
        data = event.data
        trade = TradePrint(
            timestamp=event.timestamp,
            buyer=data.get("buyer", ""),
            seller=data.get("seller", ""),
            symbol=event.product or data.get("symbol", "UNKNOWN"),
            currency=data.get("currency", "SEASHELLS"),
            price=data.get("price", 0.0),
            quantity=data.get("quantity", 0),
            aggressor_side=data.get("aggressor_side"),
        )

        self._trade_tape.append(trade)
        # Cap tape length.
        if len(self._trade_tape) > self.MAX_TAPE_LENGTH:
            self._trade_tape = self._trade_tape[-self.MAX_TAPE_LENGTH:]

        changes["trade"] = trade.model_dump()

    def _handle_fill(self, event: Event, changes: dict) -> None:
        """Update positions and PnL from a fill event."""
        data = event.data
        fill = FillEvent(
            order_id=data.get("order_id", ""),
            product=event.product or data.get("product", "UNKNOWN"),
            side=data.get("side", "BUY"),
            price=data.get("price", 0.0),
            quantity=data.get("quantity", 0),
            timestamp=event.timestamp,
            is_aggressive=data.get("is_aggressive", False),
        )

        self._apply_fill(fill)

        # Update the linked order if it exists.
        order = self._active_orders.get(fill.order_id)
        if order is not None:
            order.filled_quantity += fill.quantity
            order.avg_fill_price = (
                (order.avg_fill_price * (order.filled_quantity - fill.quantity)
                 + fill.price * fill.quantity)
                / order.filled_quantity
                if order.filled_quantity > 0 else fill.price
            )
            order.updated_at = event.timestamp
            if order.filled_quantity >= order.quantity:
                order.status = _import_order_status("FILLED")
                del self._active_orders[fill.order_id]
            else:
                order.status = _import_order_status("PARTIAL_FILL")

        # Record PnL snapshot.
        pnl_snap = self._build_pnl_snapshot(event.timestamp)
        self._pnl_history.append(pnl_snap)

        changes["fill"] = fill.model_dump()
        changes["pnl"] = pnl_snap.model_dump()

    def _handle_strategy_submit(self, event: Event, changes: dict) -> None:
        """Track a newly submitted strategy order."""
        data = event.data
        order = StrategyOrder(
            order_id=data.get("order_id", ""),
            product=event.product or data.get("product", "UNKNOWN"),
            side=data.get("side", "BUY"),
            order_type=data.get("order_type", "LIMIT"),
            price=data.get("price", 0.0),
            quantity=data.get("quantity", 0),
            timestamp=event.timestamp,
            status=_import_order_status("ACTIVE"),
            created_at=event.timestamp,
            updated_at=event.timestamp,
        )
        self._active_orders[order.order_id] = order
        changes["order"] = order.model_dump()

    def _handle_strategy_cancel(self, event: Event, changes: dict) -> None:
        """Remove a cancelled order from active tracking."""
        order_id = event.data.get("order_id", "")
        order = self._active_orders.pop(order_id, None)
        if order is not None:
            order.status = _import_order_status("CANCELLED")
            order.updated_at = event.timestamp
            changes["cancelled_order"] = order.model_dump()
        changes["order_id"] = order_id

    # ------------------------------------------------------------------
    # Position / PnL helpers
    # ------------------------------------------------------------------

    def _apply_fill(self, fill: FillEvent) -> None:
        """Update the position for the filled product."""
        product = fill.product
        pos = self._positions.get(product)
        if pos is None:
            pos = PositionState(product=product)
            self._positions[product] = pos

        signed_qty = fill.quantity if fill.side == "BUY" else -fill.quantity
        old_qty = pos.quantity
        new_qty = old_qty + signed_qty

        if old_qty == 0:
            # Fresh position -- simple entry.
            pos.avg_entry_price = fill.price
        elif (old_qty > 0 and signed_qty > 0) or (old_qty < 0 and signed_qty < 0):
            # Adding to existing position -- update average.
            total_cost = pos.avg_entry_price * abs(old_qty) + fill.price * abs(signed_qty)
            pos.avg_entry_price = total_cost / abs(new_qty) if new_qty != 0 else 0.0
        else:
            # Reducing / flipping position -- realize PnL on closed portion.
            closed_qty = min(abs(signed_qty), abs(old_qty))
            if old_qty > 0:
                realized = (fill.price - pos.avg_entry_price) * closed_qty
            else:
                realized = (pos.avg_entry_price - fill.price) * closed_qty
            pos.realized_pnl += realized
            self._cash += realized

            # If flipping, the remainder starts at fill price.
            if abs(signed_qty) > abs(old_qty):
                pos.avg_entry_price = fill.price

        pos.quantity = new_qty
        # Re-mark with the fill price as an approximation.
        pos.mark_price = fill.price
        pos.unrealized_pnl = self._calc_unrealized(pos)

    def _mark_position(self, product: str, mid: Optional[float]) -> None:
        """Mark a position to the latest mid price."""
        pos = self._positions.get(product)
        if pos is None or mid is None:
            return
        pos.mark_price = mid
        pos.unrealized_pnl = self._calc_unrealized(pos)

    @staticmethod
    def _calc_unrealized(pos: PositionState) -> float:
        if pos.quantity == 0 or pos.mark_price == 0:
            return 0.0
        if pos.quantity > 0:
            return (pos.mark_price - pos.avg_entry_price) * pos.quantity
        return (pos.avg_entry_price - pos.mark_price) * abs(pos.quantity)

    def _build_pnl_snapshot(self, timestamp: int) -> PnLState:
        total_realized = sum(p.realized_pnl for p in self._positions.values())
        total_unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        return PnLState(
            timestamp=timestamp,
            realized_pnl=total_realized,
            unrealized_pnl=total_unrealized,
            total_pnl=total_realized + total_unrealized,
            inventory={p: pos.quantity for p, pos in self._positions.items()},
            cash=self._cash,
        )

    def _build_inventory(self) -> InventoryState:
        total_realized = sum(p.realized_pnl for p in self._positions.values())
        total_unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        return InventoryState(
            positions={p: pos for p, pos in self._positions.items()},
            cash=self._cash,
            total_realized_pnl=total_realized,
            total_unrealized_pnl=total_unrealized,
            total_pnl=total_realized + total_unrealized,
        )


# ------------------------------------------------------------------
# Handler dispatch table (avoids long if/elif chains)
# ------------------------------------------------------------------

def _import_order_status(name: str):
    """Lazy import to avoid circular dependency issues."""
    from app.models.market import OrderStatus
    return OrderStatus(name)


_EVENT_HANDLERS: dict[EventType, object] = {
    EventType.BOOK_SNAPSHOT: ReplayState._handle_book_snapshot,
    EventType.TRADE_PRINT: ReplayState._handle_trade_print,
    EventType.FILL: ReplayState._handle_fill,
    EventType.STRATEGY_SUBMIT: ReplayState._handle_strategy_submit,
    EventType.STRATEGY_CANCEL: ReplayState._handle_strategy_cancel,
}
