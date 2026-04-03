"""Order book reconstruction engine for IMC Prosperity trading terminal.

Builds and maintains visible order book state from flat market snapshots,
keeping a per-product history that supports both live and replay modes.
"""

from __future__ import annotations

import math
from typing import Optional, Union

from backend.app.models.market import (
    BookLevel,
    MarketSnapshot,
    OrderSide,
    VisibleOrderBook,
)


class OrderBookEngine:
    """Reconstructs and tracks order book state from market snapshots.

    Maintains an internal book per product and an append-only history
    so that callers can retrieve the current book or walk back through
    previous states.
    """

    def __init__(self) -> None:
        # product -> current VisibleOrderBook
        self._current_books: dict[str, VisibleOrderBook] = {}
        # product -> list of historical VisibleOrderBook snapshots
        self._book_history: dict[str, list[VisibleOrderBook]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_from_snapshot(self, snapshot: MarketSnapshot) -> VisibleOrderBook:
        """Build a ``VisibleOrderBook`` from a flat ``MarketSnapshot``.

        Handles NaN / None values in price/volume levels 2 and 3 gracefully
        by simply omitting those levels from the resulting book.
        """
        bids = self._build_levels(
            snapshot.bid_prices, snapshot.bid_volumes, OrderSide.BUY
        )
        asks = self._build_levels(
            snapshot.ask_prices, snapshot.ask_volumes, OrderSide.SELL
        )

        # Bids: descending by price (best bid first)
        bids.sort(key=lambda lvl: lvl.price, reverse=True)
        # Asks: ascending by price (best ask first)
        asks.sort(key=lambda lvl: lvl.price)

        book = VisibleOrderBook(
            product=snapshot.product,
            timestamp=snapshot.timestamp,
            bids=bids,
            asks=asks,
        )

        product = snapshot.product
        self._current_books[product] = book
        self._book_history.setdefault(product, []).append(book)

        return book

    def get_current_book(self, product: str) -> Optional[VisibleOrderBook]:
        """Return the latest book for *product*, or ``None`` if unseen."""
        return self._current_books.get(product)

    def get_book_history(self, product: str) -> list[VisibleOrderBook]:
        """Return the full chronological history for *product*."""
        return list(self._book_history.get(product, []))

    def reset(self) -> None:
        """Clear all internal state."""
        self._current_books.clear()
        self._book_history.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid(value: Optional[Union[float, int]]) -> bool:
        """Return True if *value* is a usable number (not None / NaN)."""
        if value is None:
            return False
        try:
            return not math.isnan(float(value))
        except (TypeError, ValueError):
            return False

    @classmethod
    def _build_levels(
        cls,
        prices: list[Optional[float]],
        volumes: list[Optional[int]],
        side: OrderSide,
    ) -> list[BookLevel]:
        """Zip prices and volumes into ``BookLevel`` objects, skipping invalid entries."""
        levels: list[BookLevel] = []
        for i in range(min(len(prices), len(volumes))):
            price = prices[i]
            volume = volumes[i]
            if cls._is_valid(price) and cls._is_valid(volume):
                levels.append(
                    BookLevel(price=float(price), volume=int(volume), side=side)  # type: ignore[arg-type]
                )
        return levels
