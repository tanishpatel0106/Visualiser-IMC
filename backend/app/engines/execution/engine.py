"""Execution engine for the IMC Prosperity trading terminal.

Simulates order execution against the visible order book. Supports three
execution models (conservative, balanced, optimistic) that govern how
passive (resting) orders are filled. Aggressive orders that cross the
book are filled immediately at available prices.

The engine maintains a synthetic resting order book for passive orders
and enforces position limits, fees, and slippage.
"""

import uuid

from app.models.backtest import ExecutionModel
from app.models.market import (
    BookLevel,
    OrderSide,
    OrderStatus,
    OrderType,
    TradePrint,
    VisibleOrderBook,
)
from app.models.trading import FillEvent, StrategyOrder


class ExecutionEngine:
    """Core simulation component that processes strategy orders against
    market data and produces realistic fill events.

    Aggressive orders (those that cross the current best bid/ask) are
    matched immediately against the visible book, consuming liquidity
    level-by-level. Passive orders are placed on an internal resting
    book and filled later according to the configured execution model.

    Parameters
    ----------
    execution_model:
        Governs how passive fills are determined.
    position_limits:
        Maps product -> max absolute position. Orders that would breach
        the limit are rejected.
    fees:
        Per-unit fee applied to every fill.
    slippage:
        Additional per-unit adverse price adjustment on aggressive fills.
    """

    def __init__(
        self,
        execution_model: ExecutionModel,
        position_limits: dict[str, int],
        fees: float = 0.0,
        slippage: float = 0.0,
    ) -> None:
        self._execution_model = execution_model
        self._position_limits = position_limits
        self._fees = fees
        self._slippage = slippage

        # order_id -> StrategyOrder for all orders that are resting passively
        self._resting_orders: dict[str, StrategyOrder] = {}

        # Tracks current net position per product (updated externally via
        # update_position or internally when fills happen).
        self._positions: dict[str, int] = {}

        # All orders ever submitted (for auditing / lookups)
        self._all_orders: dict[str, StrategyOrder] = {}

    # ------------------------------------------------------------------
    # Position tracking helpers
    # ------------------------------------------------------------------

    def update_position(self, product: str, quantity: int) -> None:
        """Set the current net position for *product*."""
        self._positions[product] = quantity

    def get_position(self, product: str) -> int:
        """Return current net position for *product* (default 0)."""
        return self._positions.get(product, 0)

    # ------------------------------------------------------------------
    # Order submission
    # ------------------------------------------------------------------

    def process_order(
        self,
        order: StrategyOrder,
        book: VisibleOrderBook,
    ) -> list[FillEvent]:
        """Process a new order against the current visible book.

        Steps:
        1. Validate the order and check position limits.
        2. Determine whether the order is aggressive (crosses the book)
           or passive (rests in the book).
        3. For aggressive orders, walk through book levels to generate
           fills, applying slippage.
        4. For passive orders, insert into the internal resting book.
        5. Apply fees to all generated fills.

        Returns a list of FillEvent objects (may be empty if the order
        rests passively or is rejected).
        """
        self._all_orders[order.order_id] = order

        # --- Position limit check ---
        if not self._check_position_limit(order):
            order.status = OrderStatus.REJECTED
            return []

        fills: list[FillEvent] = []

        # Determine aggressiveness
        is_aggressive = self._is_aggressive(order, book)

        if is_aggressive:
            fills = self._match_aggressive(order, book)
        else:
            # Passive order: insert into resting book
            order.status = OrderStatus.ACTIVE
            self._resting_orders[order.order_id] = order

        # If a market order got no fills at all, reject it
        if order.order_type == OrderType.MARKET and not fills and is_aggressive:
            order.status = OrderStatus.REJECTED

        # If partially filled aggressive order has remaining qty, rest it
        if fills and order.remaining_quantity > 0 and order.order_type == OrderType.LIMIT:
            order.status = OrderStatus.PARTIAL_FILL
            self._resting_orders[order.order_id] = order
        elif fills and order.remaining_quantity == 0:
            order.status = OrderStatus.FILLED

        # Apply fees to all fills
        for fill in fills:
            fill.price = self._apply_fees(fill.price, fill.side)

        return fills

    # ------------------------------------------------------------------
    # Passive fill checking
    # ------------------------------------------------------------------

    def check_passive_fills(
        self,
        book: VisibleOrderBook,
        trades: list[TradePrint],
    ) -> list[FillEvent]:
        """Allocate each trade print's quantity globally across eligible
        resting orders using price-time priority.

        This method processes passive fills conservatively:
        - A trade print can only be consumed once.
        - Total passive fill quantity from one trade never exceeds the
          printed trade quantity.
        - If aggressor_side is known, side direction is enforced.
        - If aggressor_side is missing, fallback is conservative
          price-based eligibility.
        """
        fills: list[FillEvent] = []
        for trade in trades:
            fills.extend(self._allocate_passive_fills_for_trade(book, trade))
        return fills

    # ------------------------------------------------------------------
    # Order cancellation
    # ------------------------------------------------------------------

    def cancel_all_resting(self, products: list[str]) -> None:
        """Cancel all resting orders for the given products.

        In IMC Prosperity, each strategy tick's output replaces all
        previous resting orders — there is no persistent order book
        between ticks. This method implements that semantic.
        """
        to_remove = [
            oid for oid, o in self._resting_orders.items()
            if o.product in products
        ]
        for oid in to_remove:
            order = self._resting_orders.pop(oid, None)
            if order is not None:
                order.status = OrderStatus.CANCELLED

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a resting order. Returns True if the order was found
        and cancelled, False otherwise."""
        order = self._resting_orders.pop(order_id, None)
        if order is not None:
            order.status = OrderStatus.CANCELLED
            return True

        # Also check the master list in case it exists but is not resting
        order = self._all_orders.get(order_id)
        if order is not None and order.status in (OrderStatus.PENDING, OrderStatus.ACTIVE, OrderStatus.PARTIAL_FILL):
            order.status = OrderStatus.CANCELLED
            return True

        return False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active_orders(self, product: str) -> list[StrategyOrder]:
        """Return all resting orders for *product*."""
        return [
            o for o in self._resting_orders.values()
            if o.product == product
        ]

    def get_all_active_orders(self) -> list[StrategyOrder]:
        """Return all resting orders across all products."""
        return list(self._resting_orders.values())

    def reset(self) -> None:
        """Clear all internal state."""
        self._resting_orders.clear()
        self._all_orders.clear()
        self._positions.clear()

    # ------------------------------------------------------------------
    # Internal: aggressiveness detection
    # ------------------------------------------------------------------

    def _is_aggressive(self, order: StrategyOrder, book: VisibleOrderBook) -> bool:
        """Determine whether an order would cross the current book.

        A buy order is aggressive if its price >= best ask.
        A sell order is aggressive if its price <= best bid.
        Market orders are always aggressive.
        """
        if order.order_type == OrderType.MARKET:
            return True

        if order.side == OrderSide.BUY:
            if book.best_ask is not None and order.price >= book.best_ask:
                return True
        else:
            if book.best_bid is not None and order.price <= book.best_bid:
                return True

        return False

    # ------------------------------------------------------------------
    # Internal: aggressive matching
    # ------------------------------------------------------------------

    def _match_aggressive(
        self, order: StrategyOrder, book: VisibleOrderBook
    ) -> list[FillEvent]:
        """Walk the book and generate fills for an aggressive order.

        For a BUY order, consume ask levels from best (lowest) upward.
        For a SELL order, consume bid levels from best (highest) downward.
        Slippage is applied to each fill price.
        """
        fills: list[FillEvent] = []
        remaining = order.quantity

        if order.side == OrderSide.BUY:
            levels = list(book.asks)  # ascending by price
        else:
            levels = list(book.bids)  # descending by price

        for level in levels:
            if remaining <= 0:
                break

            # For limit orders, do not fill beyond the limit price
            if order.order_type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and level.price > order.price:
                    break
                if order.side == OrderSide.SELL and level.price < order.price:
                    break

            fill_qty = min(remaining, level.volume)
            fill_price = self._apply_slippage(level.price, order.side)

            fill = FillEvent(
                order_id=order.order_id,
                product=order.product,
                side=order.side,
                price=fill_price,
                quantity=fill_qty,
                timestamp=order.timestamp,
                is_aggressive=True,
            )
            fills.append(fill)

            remaining -= fill_qty

        # Update order state
        total_filled = sum(f.quantity for f in fills)
        if total_filled > 0:
            weighted_price = sum(f.price * f.quantity for f in fills) / total_filled
            order.filled_quantity += total_filled
            order.avg_fill_price = self._update_avg_price(
                order.avg_fill_price,
                order.filled_quantity - total_filled,
                weighted_price,
                total_filled,
            )
            order.updated_at = order.timestamp

        return fills

    # ------------------------------------------------------------------
    # Internal: passive fill allocation
    # ------------------------------------------------------------------
    def _allocate_passive_fills_for_trade(
        self,
        book: VisibleOrderBook,
        trade: TradePrint,
    ) -> list[FillEvent]:
        """Allocate a single trade print across eligible resting orders."""
        if trade.symbol != book.product or trade.quantity <= 0:
            return []

        candidates = self._eligible_resting_orders_for_trade(trade)
        if not candidates:
            return []

        remaining_trade_qty = trade.quantity
        fills: list[FillEvent] = []
        fully_filled_order_ids: list[str] = []

        for order in candidates:
            if remaining_trade_qty <= 0:
                break

            fill_qty = min(order.remaining_quantity, remaining_trade_qty)
            fill_qty = self._apply_passive_position_limits(order, fill_qty)
            if fill_qty <= 0:
                continue

            fill = FillEvent(
                order_id=order.order_id,
                product=order.product,
                side=order.side,
                price=self._apply_fees(order.price, order.side),
                quantity=fill_qty,
                timestamp=trade.timestamp,
                is_aggressive=False,
            )
            fills.append(fill)

            self._apply_order_fill(order, fill_qty, trade.timestamp)
            self._apply_position_delta(order.product, order.side, fill_qty)
            remaining_trade_qty -= fill_qty

            if order.remaining_quantity == 0:
                fully_filled_order_ids.append(order.order_id)

        for order_id in fully_filled_order_ids:
            self._resting_orders.pop(order_id, None)

        return fills

    def _eligible_resting_orders_for_trade(
        self,
        trade: TradePrint,
    ) -> list[StrategyOrder]:
        """Return eligible resting orders sorted by strict price-time
        priority with deterministic tie-breaks."""
        eligible = [
            order
            for order in self._resting_orders.values()
            if order.product == trade.symbol
            and order.remaining_quantity > 0
            and self._trade_can_fill_order(trade, order)
        ]

        if not eligible:
            return []

        if self._target_order_side_for_trade(trade) == OrderSide.BUY:
            # Better BUY price is higher.
            eligible.sort(key=lambda o: (-o.price, o.timestamp, o.order_id))
        elif self._target_order_side_for_trade(trade) == OrderSide.SELL:
            # Better SELL price is lower.
            eligible.sort(key=lambda o: (o.price, o.timestamp, o.order_id))
        else:
            # Unknown side fallback: keep deterministic by price-time.
            eligible.sort(key=lambda o: (o.timestamp, o.order_id))

        return eligible

    @staticmethod
    def _target_order_side_for_trade(trade: TradePrint) -> str | None:
        if trade.aggressor_side == OrderSide.SELL:
            return OrderSide.BUY
        if trade.aggressor_side == OrderSide.BUY:
            return OrderSide.SELL
        return None

    def _trade_can_fill_order(self, trade: TradePrint, order: StrategyOrder) -> bool:
        """Check side + price compatibility between one trade and one order."""
        target_side = self._target_order_side_for_trade(trade)
        if target_side is not None and order.side != target_side:
            return False

        if order.side == OrderSide.BUY:
            return trade.price <= order.price
        return trade.price >= order.price

    def _apply_passive_position_limits(self, order: StrategyOrder, qty: int) -> int:
        """Cap passive fill size so positions remain within limits."""
        limit = self._position_limits.get(order.product)
        if limit is None:
            return qty

        current_pos = self.get_position(order.product)
        if order.side == OrderSide.BUY:
            max_qty = max(0, limit - current_pos)
        else:
            max_qty = max(0, limit + current_pos)

        return min(qty, max_qty)

    def _apply_position_delta(self, product: str, side: OrderSide, qty: int) -> None:
        current_pos = self.get_position(product)
        if side == OrderSide.BUY:
            self._positions[product] = current_pos + qty
        else:
            self._positions[product] = current_pos - qty

    def _apply_order_fill(
        self,
        order: StrategyOrder,
        fill_qty: int,
        timestamp: int,
    ) -> None:
        previous_filled = order.filled_quantity
        order.filled_quantity += fill_qty
        order.avg_fill_price = self._update_avg_price(
            order.avg_fill_price,
            previous_filled,
            order.price,
            fill_qty,
        )
        order.updated_at = timestamp
        if order.remaining_quantity == 0:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL_FILL

    # ------------------------------------------------------------------
    # Internal: position limit enforcement
    # ------------------------------------------------------------------

    def _check_position_limit(self, order: StrategyOrder) -> bool:
        """Return True if the order is within position limits.

        Checks whether filling the entire order quantity would cause
        the net position to exceed the configured limit for the product.
        If no limit is configured for the product, the order is allowed.
        """
        limit = self._position_limits.get(order.product)
        if limit is None:
            return True

        current_pos = self.get_position(order.product)

        if order.side == OrderSide.BUY:
            projected = current_pos + order.quantity
        else:
            projected = current_pos - order.quantity

        return abs(projected) <= limit

    # ------------------------------------------------------------------
    # Internal: fee and slippage adjustments
    # ------------------------------------------------------------------

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """Apply slippage to an aggressive fill price.

        Slippage makes the fill price worse for the trader:
        - BUY: price increases (pay more)
        - SELL: price decreases (receive less)
        """
        if side == OrderSide.BUY:
            return price + self._slippage
        else:
            return price - self._slippage

    def _apply_fees(self, price: float, side: OrderSide) -> float:
        """Apply per-unit fees to a fill price.

        Fees make the effective price worse for the trader:
        - BUY: price increases
        - SELL: price decreases
        """
        if side == OrderSide.BUY:
            return price + self._fees
        else:
            return price - self._fees

    # ------------------------------------------------------------------
    # Internal: utility
    # ------------------------------------------------------------------

    @staticmethod
    def _update_avg_price(
        current_avg: float,
        current_qty: int,
        new_price: float,
        new_qty: int,
    ) -> float:
        """Compute a running weighted-average fill price."""
        total_qty = current_qty + new_qty
        if total_qty == 0:
            return 0.0
        return (current_avg * current_qty + new_price * new_qty) / total_qty
