"""Execution engine for the IMC Prosperity trading terminal.

Implements the same order-matching semantics as the Prosperity exchange:

1. **Book matching** – orders are matched against the visible order depth,
   consuming volume level-by-level.  Buy orders fill at the *ask* price
   (price improvement for the buyer); sell orders fill at the *bid* price.

2. **Market-trade matching** – any remaining order quantity is matched
   against market trades that occurred at the same timestamp.  Fill price
   is the *order's* price (not the trade's price).

Three trade-matching modes control phase 2:
  ALL   – match trades at prices equal to or better than the order.
  WORSE – only match trades strictly better than the order price.
  NONE  – skip phase 2 entirely (book-only matching).

Position limits are enforced in two stages:
  • Aggregate pre-check: if any combination of pending orders could breach
    the limit, ALL orders for that product are cancelled.
  • Per-fill clamping: each individual fill is capped so that the position
    never exceeds the limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.backtest import TradeMatchingMode
from app.models.market import OrderSide, TradePrint
from app.models.trading import FillEvent, StrategyOrder


# ------------------------------------------------------------------
# MarketTrade wrapper – tracks consumed capacity
# ------------------------------------------------------------------

@dataclass
class MarketTrade:
    """Wraps a raw TradePrint with a single mutable capacity pool.

    ``remaining_quantity`` starts at the full trade quantity and is
    consumed by **any** strategy order that matches against this trade,
    regardless of whether the strategy order is a buy or a sell.  This
    prevents the same market-trade volume from being double-counted
    (e.g. filling both a buy *and* a sell for the full printed size).
    """

    symbol: str
    price: float
    quantity: int
    buyer: str = ""
    seller: str = ""
    timestamp: int = 0
    remaining_quantity: int = 0

    @classmethod
    def from_trade_print(cls, tp: TradePrint) -> "MarketTrade":
        return cls(
            symbol=tp.symbol,
            price=tp.price,
            quantity=tp.quantity,
            buyer=tp.buyer,
            seller=tp.seller,
            timestamp=tp.timestamp,
            remaining_quantity=tp.quantity,
        )


# ------------------------------------------------------------------
# Lightweight order-depth dict helpers
# ------------------------------------------------------------------
# The Prosperity OrderDepth uses:
#   buy_orders:  dict[int, int]  – price → positive volume  (bids)
#   sell_orders: dict[int, int]  – price → negative volume   (asks)
# We work directly with these dicts so the engine stays decoupled
# from the adapter's classes.


class ExecutionEngine:
    """Matches strategy orders against an order book and market trades.

    Parameters
    ----------
    trade_matching_mode:
        Controls whether and how market trades participate in matching.
    position_limits:
        Product → max absolute position.  Products not listed use
        *default_limit*.
    default_limit:
        Fallback position limit for unlisted products.
    """

    def __init__(
        self,
        trade_matching_mode: TradeMatchingMode = TradeMatchingMode.ALL,
        position_limits: dict[str, int] | None = None,
        default_limit: int = 50,
    ) -> None:
        self._mode = trade_matching_mode
        self._position_limits = position_limits or {}
        self._default_limit = default_limit

        # Current net position per product (updated externally or via fills)
        self._positions: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Position helpers
    # ------------------------------------------------------------------

    def get_position(self, product: str) -> int:
        return self._positions.get(product, 0)

    def update_position(self, product: str, quantity: int) -> None:
        self._positions[product] = quantity

    def get_limit(self, product: str) -> int:
        return self._position_limits.get(product, self._default_limit)

    # ------------------------------------------------------------------
    # Aggregate position-limit pre-check
    # ------------------------------------------------------------------

    def enforce_limits(
        self,
        orders_by_product: dict[str, list],
    ) -> dict[str, list]:
        """Cancel ALL orders for a product if the aggregate could breach limits.

        This mirrors the Prosperity exchange rule: if the sum of all buy
        quantities plus the current position exceeds the limit, *or* the
        sum of all sell quantities would push the position below the
        negative limit, every order for that product is dropped.

        Parameters
        ----------
        orders_by_product:
            Product → list of Prosperity Order objects (with .quantity;
            positive = buy, negative = sell).

        Returns
        -------
        A *new* dict with the same keys, where products that failed the
        check have an empty list.
        """
        result: dict[str, list] = {}
        for product, orders in orders_by_product.items():
            limit = self.get_limit(product)
            position = self.get_position(product)

            total_long = sum(o.quantity for o in orders if o.quantity > 0)
            total_short = sum(-o.quantity for o in orders if o.quantity < 0)

            if position + total_long > limit or position - total_short < -limit:
                result[product] = []
            else:
                result[product] = list(orders)

        return result

    # ------------------------------------------------------------------
    # Top-level matching entry point
    # ------------------------------------------------------------------

    def match_orders(
        self,
        product: str,
        orders: list,
        buy_orders: dict[int, int],
        sell_orders: dict[int, int],
        market_trades: list[MarketTrade],
        timestamp: int = 0,
    ) -> list[FillEvent]:
        """Match all orders for a single product.

        Parameters
        ----------
        product:
            The product symbol.
        orders:
            Prosperity Order objects (.symbol, .price, .quantity).
            Positive quantity = buy, negative = sell.
        buy_orders:
            Order-depth bids: price → positive volume.
        sell_orders:
            Order-depth asks: price → negative volume (Prosperity convention).
        market_trades:
            MarketTrade wrappers for this timestamp.
        timestamp:
            Current simulation timestamp (used in fill events).

        Returns
        -------
        List of FillEvent objects for all fills generated.
        """
        limit = self.get_limit(product)
        all_fills: list[FillEvent] = []

        for order in orders:
            qty = order.quantity
            if qty == 0:
                continue

            if qty > 0:
                fills = self._match_buy_order(
                    product=product,
                    order=order,
                    sell_orders=sell_orders,
                    market_trades=market_trades,
                    limit=limit,
                    timestamp=timestamp,
                )
            else:
                fills = self._match_sell_order(
                    product=product,
                    order=order,
                    buy_orders=buy_orders,
                    market_trades=market_trades,
                    limit=limit,
                    timestamp=timestamp,
                )

            all_fills.extend(fills)

        return all_fills

    # ------------------------------------------------------------------
    # Buy order matching
    # ------------------------------------------------------------------

    def _match_buy_order(
        self,
        product: str,
        order,
        sell_orders: dict[int, int],
        market_trades: list[MarketTrade],
        limit: int,
        timestamp: int,
    ) -> list[FillEvent]:
        """Match a buy order (positive quantity).

        Phase 1: against ask levels (sell_orders) with price <= order.price.
                 Fills at the ask price (price improvement for buyer).
        Phase 2: against market trades.
                 Fills at the order's price.
        """
        fills: list[FillEvent] = []
        remaining = order.quantity
        position = self.get_position(product)

        # Phase 1: match against order book asks
        # Sort ask prices ascending (best ask first)
        eligible_asks = sorted(
            [p for p in sell_orders if p <= order.price and sell_orders[p] != 0]
        )

        for ask_price in eligible_asks:
            if remaining <= 0:
                break

            max_buy = max(0, limit - position)
            if max_buy <= 0:
                break

            # sell_orders values are negative (Prosperity convention)
            available = abs(sell_orders[ask_price])
            fill_qty = min(remaining, available, max_buy)

            if fill_qty <= 0:
                continue

            fills.append(FillEvent(
                order_id="",
                product=product,
                side=OrderSide.BUY,
                price=float(ask_price),  # Fill at the book's price
                quantity=fill_qty,
                timestamp=timestamp,
                is_aggressive=True,
            ))

            position += fill_qty
            remaining -= fill_qty

            # Consume volume from the order depth
            sell_orders[ask_price] += fill_qty  # moves toward 0 (was negative)
            if sell_orders[ask_price] == 0:
                del sell_orders[ask_price]

        # Phase 2: match against market trades
        if remaining > 0 and self._mode != TradeMatchingMode.NONE:
            for mt in market_trades:
                if remaining <= 0:
                    break
                if mt.remaining_quantity <= 0:
                    continue
                if mt.price > order.price:
                    continue
                if self._mode == TradeMatchingMode.WORSE and mt.price == order.price:
                    continue

                max_buy = max(0, limit - position)
                if max_buy <= 0:
                    break

                fill_qty = min(remaining, mt.remaining_quantity, max_buy)
                if fill_qty <= 0:
                    continue

                fills.append(FillEvent(
                    order_id="",
                    product=product,
                    side=OrderSide.BUY,
                    price=float(order.price),  # Fill at the order's price
                    quantity=fill_qty,
                    timestamp=timestamp,
                    is_aggressive=False,
                ))

                position += fill_qty
                remaining -= fill_qty
                mt.remaining_quantity -= fill_qty

        # Update tracked position
        self._positions[product] = position
        return fills

    # ------------------------------------------------------------------
    # Sell order matching
    # ------------------------------------------------------------------

    def _match_sell_order(
        self,
        product: str,
        order,
        buy_orders: dict[int, int],
        market_trades: list[MarketTrade],
        limit: int,
        timestamp: int,
    ) -> list[FillEvent]:
        """Match a sell order (negative quantity).

        Phase 1: against bid levels (buy_orders) with price >= order.price.
                 Fills at the bid price (price improvement for seller).
        Phase 2: against market trades.
                 Fills at the order's price.
        """
        fills: list[FillEvent] = []
        remaining = abs(order.quantity)
        position = self.get_position(product)

        # Phase 1: match against order book bids
        # Sort bid prices descending (best bid first)
        sell_price = abs(order.price)
        eligible_bids = sorted(
            [p for p in buy_orders if p >= sell_price and buy_orders[p] > 0],
            reverse=True,
        )

        for bid_price in eligible_bids:
            if remaining <= 0:
                break

            max_sell = max(0, limit + position)
            if max_sell <= 0:
                break

            available = buy_orders[bid_price]
            fill_qty = min(remaining, available, max_sell)

            if fill_qty <= 0:
                continue

            fills.append(FillEvent(
                order_id="",
                product=product,
                side=OrderSide.SELL,
                price=float(bid_price),  # Fill at the book's price
                quantity=fill_qty,
                timestamp=timestamp,
                is_aggressive=True,
            ))

            position -= fill_qty
            remaining -= fill_qty

            # Consume volume from the order depth
            buy_orders[bid_price] -= fill_qty
            if buy_orders[bid_price] == 0:
                del buy_orders[bid_price]

        # Phase 2: match against market trades
        if remaining > 0 and self._mode != TradeMatchingMode.NONE:
            for mt in market_trades:
                if remaining <= 0:
                    break
                if mt.remaining_quantity <= 0:
                    continue
                if mt.price < sell_price:
                    continue
                if self._mode == TradeMatchingMode.WORSE and mt.price == sell_price:
                    continue

                max_sell = max(0, limit + position)
                if max_sell <= 0:
                    break

                fill_qty = min(remaining, mt.remaining_quantity, max_sell)
                if fill_qty <= 0:
                    continue

                fills.append(FillEvent(
                    order_id="",
                    product=product,
                    side=OrderSide.SELL,
                    price=float(abs(order.price)),  # Fill at the order's price
                    quantity=fill_qty,
                    timestamp=timestamp,
                    is_aggressive=False,
                ))

                position -= fill_qty
                remaining -= fill_qty
                mt.remaining_quantity -= fill_qty

        # Update tracked position
        self._positions[product] = position
        return fills

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all internal state."""
        self._positions.clear()
