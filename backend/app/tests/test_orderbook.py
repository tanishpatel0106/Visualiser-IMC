"""Tests for OrderBookEngine and BookMetrics."""

import math

import pytest

from backend.app.engines.orderbook.book import OrderBookEngine
from backend.app.engines.orderbook.metrics import BookMetrics
from backend.app.models.market import (
    BookLevel,
    MarketSnapshot,
    OrderSide,
    VisibleOrderBook,
)


# ======================================================================
# Fixtures / helpers
# ======================================================================

@pytest.fixture
def engine():
    return OrderBookEngine()


def _snap(product, timestamp, bid_prices, bid_volumes, ask_prices, ask_volumes):
    return MarketSnapshot(
        day=1,
        timestamp=timestamp,
        product=product,
        bid_prices=bid_prices,
        bid_volumes=bid_volumes,
        ask_prices=ask_prices,
        ask_volumes=ask_volumes,
    )


def _make_book(bids, asks, product="X", timestamp=100):
    return VisibleOrderBook(
        product=product,
        timestamp=timestamp,
        bids=[BookLevel(price=p, volume=v, side=OrderSide.BUY) for p, v in bids],
        asks=[BookLevel(price=p, volume=v, side=OrderSide.SELL) for p, v in asks],
    )


# ======================================================================
# OrderBookEngine.update_from_snapshot
# ======================================================================

class TestOrderBookEngineUpdate:
    def test_single_level_book(self, engine):
        snap = _snap("EMERALDS", 100,
                      bid_prices=[99.0], bid_volumes=[10],
                      ask_prices=[101.0], ask_volumes=[15])
        book = engine.update_from_snapshot(snap)

        assert book.product == "EMERALDS"
        assert len(book.bids) == 1
        assert len(book.asks) == 1
        assert book.best_bid == 99.0
        assert book.best_ask == 101.0

    def test_two_level_book(self, engine):
        snap = _snap("EMERALDS", 100,
                      bid_prices=[99.0, 98.0], bid_volumes=[10, 20],
                      ask_prices=[101.0, 102.0], ask_volumes=[15, 25])
        book = engine.update_from_snapshot(snap)

        assert len(book.bids) == 2
        assert len(book.asks) == 2
        # Bids sorted descending
        assert book.bids[0].price == 99.0
        assert book.bids[1].price == 98.0
        # Asks sorted ascending
        assert book.asks[0].price == 101.0
        assert book.asks[1].price == 102.0

    def test_three_level_book(self, engine):
        snap = _snap("EMERALDS", 100,
                      bid_prices=[99.0, 98.0, 97.0], bid_volumes=[10, 20, 30],
                      ask_prices=[101.0, 102.0, 103.0], ask_volumes=[15, 25, 35])
        book = engine.update_from_snapshot(snap)

        assert len(book.bids) == 3
        assert len(book.asks) == 3
        assert book.total_bid_depth == 60
        assert book.total_ask_depth == 75

    def test_nan_levels_skipped(self, engine):
        snap = _snap("EMERALDS", 100,
                      bid_prices=[99.0, float("nan"), None],
                      bid_volumes=[10, None, None],
                      ask_prices=[101.0, None, float("nan")],
                      ask_volumes=[15, None, None])
        book = engine.update_from_snapshot(snap)

        # Only the valid level-1 should appear
        assert len(book.bids) == 1
        assert len(book.asks) == 1
        assert book.bids[0].price == 99.0
        assert book.asks[0].price == 101.0

    def test_history_accumulated(self, engine):
        snap1 = _snap("X", 100, [99.0], [10], [101.0], [15])
        snap2 = _snap("X", 200, [98.0], [12], [102.0], [18])

        engine.update_from_snapshot(snap1)
        engine.update_from_snapshot(snap2)

        history = engine.get_book_history("X")
        assert len(history) == 2
        assert history[0].timestamp == 100
        assert history[1].timestamp == 200

    def test_current_book_updated(self, engine):
        snap1 = _snap("X", 100, [99.0], [10], [101.0], [15])
        snap2 = _snap("X", 200, [98.0], [12], [102.0], [18])

        engine.update_from_snapshot(snap1)
        engine.update_from_snapshot(snap2)

        current = engine.get_current_book("X")
        assert current is not None
        assert current.timestamp == 200
        assert current.best_bid == 98.0

    def test_unknown_product_returns_none(self, engine):
        assert engine.get_current_book("UNKNOWN") is None

    def test_reset_clears_state(self, engine):
        snap = _snap("X", 100, [99.0], [10], [101.0], [15])
        engine.update_from_snapshot(snap)

        engine.reset()
        assert engine.get_current_book("X") is None
        assert engine.get_book_history("X") == []

    def test_multiple_products(self, engine):
        snap_a = _snap("A", 100, [50.0], [5], [52.0], [8])
        snap_b = _snap("B", 100, [200.0], [3], [202.0], [4])

        engine.update_from_snapshot(snap_a)
        engine.update_from_snapshot(snap_b)

        book_a = engine.get_current_book("A")
        book_b = engine.get_current_book("B")
        assert book_a is not None and book_a.best_bid == 50.0
        assert book_b is not None and book_b.best_bid == 200.0


# ======================================================================
# BookMetrics
# ======================================================================

class TestBookMetrics:
    def test_compute_basic_metrics(self):
        book = _make_book(
            bids=[(99.0, 10), (98.0, 20)],
            asks=[(101.0, 15), (102.0, 25)],
        )
        metrics = BookMetrics.compute(book)

        assert metrics["spread"] == pytest.approx(2.0)
        assert metrics["mid"] == pytest.approx(100.0)
        assert metrics["total_bid_depth"] == 30
        assert metrics["total_ask_depth"] == 40

    def test_spread_regime_tight(self):
        book = _make_book(bids=[(99.5, 10)], asks=[(100.0, 10)])
        metrics = BookMetrics.compute(book, rolling_mean_spread=2.0)
        # spread=0.5, ratio=0.25 < TIGHT_THRESHOLD=0.75
        assert metrics["spread_regime"] == "tight"

    def test_spread_regime_wide(self):
        book = _make_book(bids=[(95.0, 10)], asks=[(105.0, 10)])
        metrics = BookMetrics.compute(book, rolling_mean_spread=2.0)
        # spread=10, ratio=5.0 >= WIDE_THRESHOLD=1.5
        assert metrics["spread_regime"] == "wide"

    def test_spread_regime_normal(self):
        book = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        metrics = BookMetrics.compute(book, rolling_mean_spread=2.0)
        # spread=2, ratio=1.0 (between 0.75 and 1.5)
        assert metrics["spread_regime"] == "normal"

    def test_spread_regime_no_baseline(self):
        book = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        metrics = BookMetrics.compute(book, rolling_mean_spread=None)
        assert metrics["spread_regime"] == "normal"

    def test_quote_stability_no_previous(self):
        book = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        metrics = BookMetrics.compute(book, previous=None)
        assert metrics["quote_stability"]["stable"] is True
        assert metrics["quote_stability"]["bid_change"] == 0.0

    def test_quote_stability_with_movement(self):
        prev = _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)])
        curr = _make_book(bids=[(100.0, 10)], asks=[(102.0, 10)])
        metrics = BookMetrics.compute(curr, previous=prev)
        assert metrics["quote_stability"]["bid_change"] == pytest.approx(1.0)
        assert metrics["quote_stability"]["ask_change"] == pytest.approx(1.0)
        assert metrics["quote_stability"]["stable"] is False

    def test_imbalance_metrics(self):
        book = _make_book(
            bids=[(99.0, 30), (98.0, 20), (97.0, 10)],
            asks=[(101.0, 10), (102.0, 20), (103.0, 30)],
        )
        metrics = BookMetrics.compute(book)
        # top_level: (30-10)/(30+10) = 0.5
        assert metrics["top_level_imbalance"] == pytest.approx(0.5)
        # top3: (60-60)/(60+60) = 0.0
        assert metrics["top3_imbalance"] == pytest.approx(0.0)


# ======================================================================
# BookMetrics rolling stats
# ======================================================================

class TestBookMetricsRolling:
    def test_rolling_spread_stats(self):
        books = [
            _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)], timestamp=i)
            for i in range(5)
        ]
        stats = BookMetrics.rolling_spread_stats(books, window=3)
        assert stats["count"] == 3
        assert stats["mean"] == pytest.approx(2.0)
        assert stats["std"] == pytest.approx(0.0)  # all same spread
        assert stats["min"] == pytest.approx(2.0)
        assert stats["max"] == pytest.approx(2.0)

    def test_rolling_spread_stats_varying(self):
        books = [
            _make_book(bids=[(99.0, 10)], asks=[(101.0, 10)], timestamp=0),  # spread=2
            _make_book(bids=[(98.0, 10)], asks=[(102.0, 10)], timestamp=1),  # spread=4
            _make_book(bids=[(99.5, 10)], asks=[(100.5, 10)], timestamp=2),  # spread=1
        ]
        stats = BookMetrics.rolling_spread_stats(books, window=10)
        assert stats["count"] == 3
        assert stats["mean"] == pytest.approx((2 + 4 + 1) / 3)
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(4.0)

    def test_rolling_depth_stats(self):
        books = [
            _make_book(bids=[(99.0, 10)], asks=[(101.0, 20)]),
            _make_book(bids=[(99.0, 30)], asks=[(101.0, 40)]),
        ]
        stats = BookMetrics.rolling_depth_stats(books, window=10)
        assert stats["bid_depth"]["mean"] == pytest.approx(20.0)
        assert stats["ask_depth"]["mean"] == pytest.approx(30.0)

    def test_empty_books_rolling(self):
        stats = BookMetrics.rolling_spread_stats([], window=5)
        assert stats["count"] == 0
        assert stats["mean"] is None
