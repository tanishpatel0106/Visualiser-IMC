"""Execution engine for the IMC Prosperity trading terminal.

Simulates order execution against the visible order book. Supports three
execution models (conservative, balanced, optimistic) that govern how
passive (resting) orders are filled. Aggressive orders that cross the
book are filled immediately at available prices.

The engine maintains a synthetic resting order book for passive orders
and enforces position limits, fees, and slippage.
"""

import uuid
from typing import Optional

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
        recent_trades: list[TradePrint],
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
        """Check all resting passive orders for potential fills.

        The fill logic depends on the execution model:

        CONSERVATIVE -- Passive fills occur only when an actual trade
            print exists at a price equal to or better than the resting
            order price. This is the most realistic model because it
            requires evidence that liquidity was actually taken at that
            level.

        BALANCED -- Fills use a combination of trade-flow evidence and
            book movement heuristics. A resting order fills if (a) a
            trade print occurs at or through the price, OR (b) the
            opposing best quote moves through the resting price,
            suggesting the level was consumed.

        OPTIMISTIC -- Fills whenever the market price merely touches the
            resting level, regardless of actual trade evidence. This
            overstates fill probability and is useful for upper-bound
            estimates.
        """
        fills: list[FillEvent] = []
        filled_order_ids: list[str] = []

        for order_id, order in list(self._resting_orders.items()):
            if order.product != book.product:
                continue

            fill_qty = self._evaluate_passive_fill(order, book, trades)
            if fill_qty <= 0:
                continue

            fill_qty = min(fill_qty, order.remaining_quantity)

            fill = FillEvent(
                order_id=order.order_id,
                product=order.product,
                side=order.side,
                price=self._apply_fees(order.price, order.side),
                quantity=fill_qty,
                timestamp=book.timestamp,
                is_aggressive=False,
            )
            fills.append(fill)

            # Update the order state
            order.filled_quantity += fill_qty
            order.avg_fill_price = self._update_avg_price(
                order.avg_fill_price,
                order.filled_quantity - fill_qty,
                order.price,
                fill_qty,
            )
            order.updated_at = book.timestamp

            if order.remaining_quantity == 0:
                order.status = OrderStatus.FILLED
                filled_order_ids.append(order_id)
            else:
                order.status = OrderStatus.PARTIAL_FILL

        # Remove fully filled orders from resting book
        for oid in filled_order_ids:
            self._resting_orders.pop(oid, None)

        return fills

    # ------------------------------------------------------------------
    # Order cancellation
    # ------------------------------------------------------------------

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
    # Internal: passive fill evaluation
    # ------------------------------------------------------------------

    def _evaluate_passive_fill(
        self,
        order: StrategyOrder,
        book: VisibleOrderBook,
        trades: list[TradePrint],
    ) -> int:
        """Evaluate how many units of a resting order should fill,
        based on the current execution model.

        Returns the fill quantity (0 if no fill).
        """
        if self._execution_model == ExecutionModel.CONSERVATIVE:
            return self._eval_conservative(order, book, trades)
        elif self._execution_model == ExecutionModel.BALANCED:
            return self._eval_balanced(order, book, trades)
        else:  # OPTIMISTIC
            return self._eval_optimistic(order, book, trades)

    def _eval_conservative(
        self,
        order: StrategyOrder,
        book: VisibleOrderBook,
        trades: list[TradePrint],
    ) -> int:
        """CONSERVATIVE model: passive fills only when actual trade prints
        occur at or through the resting price.

        For a resting BUY at price P, a fill occurs only if a trade
        printed at price <= P (someone sold at or below our bid).
        For a resting SELL at price P, a fill occurs only if a trade
        printed at price >= P (someone bought at or above our ask).

        The fill quantity is capped at the total volume of qualifying
        trade prints (we can only capture volume that actually traded
        through our level).
        """
        qualifying_volume = 0

        for trade in trades:
            if trade.symbol != order.product:
                continue

            if order.side == OrderSide.BUY and trade.price <= order.price:
                qualifying_volume += trade.quantity
            elif order.side == OrderSide.SELL and trade.price >= order.price:
                qualifying_volume += trade.quantity

        return min(qualifying_volume, order.remaining_quantity)

    def _eval_balanced(
        self,
        order: StrategyOrder,
        book: VisibleOrderBook,
        trades: list[TradePrint],
    ) -> int:
        """BALANCED model: fills based on trade flow + book movement.

        A resting order fills if:
        (a) Trade prints occur at or through the resting price (same as
            conservative), OR
        (b) The opposing best quote has moved through the resting price,
            indicating the level was consumed by other participants.

        For condition (b), we fill the full remaining quantity since the
        price level was clearly traded through.
        """
        # First check trade-based fills (same as conservative)
        trade_volume = self._eval_conservative(order, book, trades)
        if trade_volume > 0:
            return trade_volume

        # Check book-movement heuristic: has the opposing side moved
        # through our resting price?
        if order.side == OrderSide.BUY:
            # If best ask has dropped to or below our bid, the level traded through
            if book.best_ask is not None and book.best_ask <= order.price:
                return order.remaining_quantity
        else:
            # If best bid has risen to or above our ask, the level traded through
            if book.best_bid is not None and book.best_bid >= order.price:
                return order.remaining_quantity

        return 0

    def _eval_optimistic(
        self,
        order: StrategyOrder,
        book: VisibleOrderBook,
        trades: list[TradePrint],
    ) -> int:
        """OPTIMISTIC model: fill when the market price touches the
        resting level.

        A resting BUY fills if the best ask <= resting price.
        A resting SELL fills if the best bid >= resting price.

        This is the most aggressive fill assumption and will overstate
        profitability for passive strategies. Useful as an upper bound.
        """
        if order.side == OrderSide.BUY:
            if book.best_ask is not None and book.best_ask <= order.price:
                return order.remaining_quantity
        else:
            if book.best_bid is not None and book.best_bid >= order.price:
                return order.remaining_quantity

        return 0

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
