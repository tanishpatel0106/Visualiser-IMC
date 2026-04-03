"""Book-level analytics computed from visible order book snapshots.

Provides rolling statistics and regime classification on top of the
per-snapshot metrics already exposed by ``VisibleOrderBook``.
"""

import math
from typing import Optional

from app.models.market import VisibleOrderBook


class BookMetrics:
    """Stateless metric calculator that operates on ``VisibleOrderBook`` instances.

    All class methods are pure functions except for ``compute``, which also
    compares against an optional *previous* book to derive quote-stability.
    """

    # Spread-regime thresholds expressed as multiples of the rolling mean spread.
    TIGHT_THRESHOLD = 0.75
    WIDE_THRESHOLD = 1.5

    # ------------------------------------------------------------------
    # Single-book metrics
    # ------------------------------------------------------------------

    @staticmethod
    def compute(
        book: VisibleOrderBook,
        previous: Optional[VisibleOrderBook] = None,
        rolling_mean_spread: Optional[float] = None,
        rolling_std_spread: Optional[float] = None,
    ) -> dict:
        """Return a full dict of metrics for a single book snapshot.

        Parameters
        ----------
        book:
            The current order book.
        previous:
            The immediately preceding book for this product (used for
            quote-stability computation).  May be ``None``.
        rolling_mean_spread:
            Rolling mean spread used for spread-regime classification.
        rolling_std_spread:
            Rolling std-dev of the spread (unused today but kept for
            forward compatibility).
        """
        metrics: dict = {}

        # --- prices ---
        metrics["spread"] = book.spread
        metrics["mid"] = book.mid_price
        metrics["weighted_mid"] = book.weighted_mid
        metrics["microprice"] = book.microprice

        # --- depth ---
        metrics["total_bid_depth"] = book.total_bid_depth
        metrics["total_ask_depth"] = book.total_ask_depth

        # --- imbalance ---
        metrics["top_level_imbalance"] = book.top_level_imbalance
        metrics["top3_imbalance"] = book.top3_imbalance

        # --- pressure / skew ---
        metrics["book_pressure"] = book.book_pressure
        metrics["depth_skew"] = book.depth_skew

        # --- spread regime ---
        metrics["spread_regime"] = BookMetrics._classify_spread_regime(
            book.spread, rolling_mean_spread
        )

        # --- quote stability ---
        metrics["quote_stability"] = BookMetrics._quote_stability(book, previous)

        return metrics

    # ------------------------------------------------------------------
    # Rolling / window statistics
    # ------------------------------------------------------------------

    @staticmethod
    def rolling_spread_stats(
        books: list[VisibleOrderBook], window: int
    ) -> dict:
        """Compute rolling spread statistics over the last *window* books.

        Returns a dict with ``mean``, ``std``, ``min``, ``max``, and the
        raw ``values`` list (which may be shorter than *window* if not
        enough books have valid spreads).
        """
        tail = books[-window:] if len(books) >= window else books
        spreads: list[float] = [
            b.spread for b in tail if b.spread is not None
        ]
        return BookMetrics._describe(spreads, "spread")

    @staticmethod
    def rolling_depth_stats(
        books: list[VisibleOrderBook], window: int
    ) -> dict:
        """Compute rolling depth statistics over the last *window* books.

        Returns dicts for ``bid_depth`` and ``ask_depth`` each containing
        ``mean``, ``std``, ``min``, ``max``.
        """
        tail = books[-window:] if len(books) >= window else books
        bid_depths = [float(b.total_bid_depth) for b in tail]
        ask_depths = [float(b.total_ask_depth) for b in tail]
        return {
            "bid_depth": BookMetrics._describe(bid_depths, "bid_depth"),
            "ask_depth": BookMetrics._describe(ask_depths, "ask_depth"),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_spread_regime(
        spread: Optional[float],
        rolling_mean: Optional[float],
    ) -> str:
        """Classify the current spread as ``tight``, ``normal``, or ``wide``.

        Uses *rolling_mean* as the baseline.  Falls back to ``"normal"`` if
        insufficient data is available.
        """
        if spread is None or rolling_mean is None or rolling_mean <= 0:
            return "normal"
        ratio = spread / rolling_mean
        if ratio <= BookMetrics.TIGHT_THRESHOLD:
            return "tight"
        if ratio >= BookMetrics.WIDE_THRESHOLD:
            return "wide"
        return "normal"

    @staticmethod
    def _quote_stability(
        current: VisibleOrderBook,
        previous: Optional[VisibleOrderBook],
    ) -> dict:
        """Measure how much the best bid / ask changed relative to previous.

        Returns a dict with ``bid_change``, ``ask_change``, and
        ``stable`` (True if neither side moved).
        """
        if previous is None:
            return {"bid_change": 0.0, "ask_change": 0.0, "stable": True}

        bid_change = _safe_diff(current.best_bid, previous.best_bid)
        ask_change = _safe_diff(current.best_ask, previous.best_ask)
        stable = bid_change == 0.0 and ask_change == 0.0
        return {
            "bid_change": bid_change,
            "ask_change": ask_change,
            "stable": stable,
        }

    @staticmethod
    def _describe(values: list[float], label: str) -> dict:
        """Return basic descriptive statistics for a numeric list."""
        if not values:
            return {
                "mean": None,
                "std": None,
                "min": None,
                "max": None,
                "count": 0,
                "values": [],
            }
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(variance)
        return {
            "mean": mean,
            "std": std,
            "min": min(values),
            "max": max(values),
            "count": n,
            "values": values,
        }


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _safe_diff(a: Optional[float], b: Optional[float]) -> float:
    """Return ``a - b``, treating None as 0."""
    if a is None or b is None:
        return 0.0
    return a - b
