"""Tests for data loading, normalization, and aggregation."""

import os
import tempfile

import pandas as pd
import pytest

from backend.app.engines.data.loader import DataLoader
from backend.app.engines.data.normalizer import DataNormalizer
from backend.app.engines.data.aggregator import DataAggregator
from backend.app.models.events import EventType
from backend.app.models.market import MarketSnapshot, OrderSide, TradePrint


# ======================================================================
# Fixtures / helpers
# ======================================================================

@pytest.fixture
def loader():
    return DataLoader()


@pytest.fixture
def normalizer():
    return DataNormalizer()


@pytest.fixture
def aggregator():
    return DataAggregator()


def _write_csv(path: str, content: str, sep: str = ";"):
    """Write CSV content to a file."""
    with open(path, "w") as f:
        f.write(content)


# ======================================================================
# DataLoader.discover_datasets
# ======================================================================

class TestDiscoverDatasets:
    def test_discovers_price_and_trade_files(self, loader):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "prices_round_1_day_0.csv"), "w").close()
            open(os.path.join(d, "prices_round_1_day_1.csv"), "w").close()
            open(os.path.join(d, "trades_round_1_day_0.csv"), "w").close()
            open(os.path.join(d, "unrelated.txt"), "w").close()

            datasets = loader.discover_datasets(d)
            assert "prices_round_1_day_0" in datasets
            assert "prices_round_1_day_1" in datasets
            assert "trades_round_1_day_0" in datasets
            assert len(datasets) == 3

    def test_nonexistent_directory_raises(self, loader):
        with pytest.raises(FileNotFoundError):
            loader.discover_datasets("/nonexistent/path/xyz")

    def test_empty_directory(self, loader):
        with tempfile.TemporaryDirectory() as d:
            datasets = loader.discover_datasets(d)
            assert datasets == {}

    def test_negative_day(self, loader):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "prices_round_2_day_-1.csv"), "w").close()
            datasets = loader.discover_datasets(d)
            assert "prices_round_2_day_-1" in datasets


# ======================================================================
# DataLoader.load_price_csv
# ======================================================================

class TestLoadPriceCsv:
    def test_basic_parse(self, loader):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "prices.csv")
            _write_csv(path, (
                "day;timestamp;product;bid_price_1;bid_volume_1;"
                "ask_price_1;ask_volume_1;mid_price\n"
                "1;100;EMERALDS;99.0;10;101.0;15;100.0\n"
                "1;200;EMERALDS;98.5;12;101.5;18;100.0\n"
            ))
            snaps = loader.load_price_csv(path)
            assert len(snaps) == 2
            assert snaps[0].day == 1
            assert snaps[0].timestamp == 100
            assert snaps[0].product == "EMERALDS"
            assert snaps[0].bid_prices[0] == 99.0
            assert snaps[0].ask_volumes[0] == 15

    def test_missing_level_3(self, loader):
        """Level 3 columns absent -- should fill with None."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "prices.csv")
            _write_csv(path, (
                "day;timestamp;product;bid_price_1;bid_volume_1;"
                "ask_price_1;ask_volume_1;mid_price\n"
                "1;100;EMERALDS;99.0;10;101.0;15;100.0\n"
            ))
            snaps = loader.load_price_csv(path)
            assert len(snaps) == 1
            # Level 2 and 3 should be None
            assert snaps[0].bid_prices[1] is None
            assert snaps[0].bid_prices[2] is None
            assert snaps[0].ask_prices[2] is None

    def test_file_not_found(self, loader):
        with pytest.raises(FileNotFoundError):
            loader.load_price_csv("/nonexistent/file.csv")

    def test_with_pnl_column(self, loader):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "prices.csv")
            _write_csv(path, (
                "day;timestamp;product;bid_price_1;bid_volume_1;"
                "ask_price_1;ask_volume_1;mid_price;profit_and_loss\n"
                "1;100;EMERALDS;99.0;10;101.0;15;100.0;42.5\n"
            ))
            snaps = loader.load_price_csv(path)
            assert snaps[0].profit_and_loss == pytest.approx(42.5)


# ======================================================================
# DataLoader.load_trade_csv
# ======================================================================

class TestLoadTradeCsv:
    def test_basic_parse(self, loader):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "trades.csv")
            _write_csv(path, (
                "timestamp;buyer;seller;symbol;currency;price;quantity\n"
                "100;Alice;Bob;EMERALDS;SEASHELLS;99.5;3\n"
                "200;Carol;Dave;EMERALDS;SEASHELLS;100.5;7\n"
            ))
            trades = loader.load_trade_csv(path)
            assert len(trades) == 2
            assert trades[0].buyer == "Alice"
            assert trades[0].price == 99.5
            assert trades[1].quantity == 7

    def test_file_not_found(self, loader):
        with pytest.raises(FileNotFoundError):
            loader.load_trade_csv("/nonexistent/trades.csv")


# ======================================================================
# Schema validation
# ======================================================================

class TestSchemaValidation:
    def test_price_schema_missing_columns(self, loader):
        df = pd.DataFrame({"day": [1], "timestamp": [100]})
        with pytest.raises(ValueError, match="missing required columns"):
            loader.validate_price_schema(df)

    def test_price_schema_valid(self, loader):
        cols = {
            "day": [1], "timestamp": [100], "product": ["X"],
            "bid_price_1": [99.0], "bid_volume_1": [10],
            "ask_price_1": [101.0], "ask_volume_1": [15],
            "mid_price": [100.0],
        }
        df = pd.DataFrame(cols)
        assert loader.validate_price_schema(df) is True

    def test_trade_schema_missing_columns(self, loader):
        df = pd.DataFrame({"timestamp": [1]})
        with pytest.raises(ValueError, match="missing required columns"):
            loader.validate_trade_schema(df)

    def test_trade_schema_valid(self, loader):
        cols = {
            "timestamp": [1], "buyer": ["A"], "seller": ["B"],
            "symbol": ["X"], "currency": ["S"], "price": [1.0], "quantity": [1],
        }
        df = pd.DataFrame(cols)
        assert loader.validate_trade_schema(df) is True


# ======================================================================
# DataNormalizer.merge_to_event_stream
# ======================================================================

class TestMergeToEventStream:
    def test_chronological_ordering(self, normalizer):
        snaps = [
            MarketSnapshot(day=1, timestamp=200, product="X",
                           bid_prices=[99.0], bid_volumes=[10],
                           ask_prices=[101.0], ask_volumes=[15], mid_price=100.0),
            MarketSnapshot(day=1, timestamp=100, product="X",
                           bid_prices=[98.0], bid_volumes=[10],
                           ask_prices=[102.0], ask_volumes=[15], mid_price=100.0),
        ]
        trades = [
            TradePrint(timestamp=150, buyer="A", seller="B",
                       symbol="X", price=100.0, quantity=5),
        ]
        events = normalizer.merge_to_event_stream(snaps, trades)

        assert len(events) == 3
        assert events[0].timestamp == 100
        assert events[1].timestamp == 150
        assert events[2].timestamp == 200

    def test_sequence_numbers_assigned(self, normalizer):
        snaps = [
            MarketSnapshot(day=1, timestamp=100, product="X",
                           bid_prices=[99.0], bid_volumes=[10],
                           ask_prices=[101.0], ask_volumes=[15], mid_price=100.0),
        ]
        trades = [
            TradePrint(timestamp=100, buyer="A", seller="B",
                       symbol="X", price=100.0, quantity=5),
        ]
        events = normalizer.merge_to_event_stream(snaps, trades)

        assert events[0].sequence_num == 1
        assert events[1].sequence_num == 2

    def test_snapshots_before_trades_at_same_timestamp(self, normalizer):
        snaps = [
            MarketSnapshot(day=1, timestamp=100, product="X",
                           bid_prices=[99.0], bid_volumes=[10],
                           ask_prices=[101.0], ask_volumes=[15], mid_price=100.0),
        ]
        trades = [
            TradePrint(timestamp=100, buyer="A", seller="B",
                       symbol="X", price=100.0, quantity=5),
        ]
        events = normalizer.merge_to_event_stream(snaps, trades)

        assert events[0].event_type == EventType.BOOK_SNAPSHOT
        assert events[1].event_type == EventType.TRADE_PRINT

    def test_empty_inputs(self, normalizer):
        events = normalizer.merge_to_event_stream([], [])
        assert events == []


# ======================================================================
# DataNormalizer.filter_by_product
# ======================================================================

class TestFilterByProduct:
    def test_filters_correctly(self, normalizer):
        from backend.app.models.events import Event, EventType

        events = [
            Event(event_type=EventType.BOOK_SNAPSHOT, timestamp=100, product="X"),
            Event(event_type=EventType.BOOK_SNAPSHOT, timestamp=200, product="Y"),
            Event(event_type=EventType.TRADE_PRINT, timestamp=300, product="X"),
        ]
        filtered = normalizer.filter_by_product(events, "X")
        assert len(filtered) == 2
        assert all(e.product == "X" for e in filtered)


# ======================================================================
# DataAggregator OHLC
# ======================================================================

class TestAggregatorOHLC:
    def test_basic_ohlc(self, aggregator):
        snaps = [
            MarketSnapshot(day=1, timestamp=0, product="X",
                           bid_prices=[99.0], bid_volumes=[10],
                           ask_prices=[101.0], ask_volumes=[15], mid_price=100.0),
            MarketSnapshot(day=1, timestamp=10, product="X",
                           bid_prices=[100.0], bid_volumes=[10],
                           ask_prices=[104.0], ask_volumes=[15], mid_price=102.0),
            MarketSnapshot(day=1, timestamp=20, product="X",
                           bid_prices=[97.0], bid_volumes=[10],
                           ask_prices=[99.0], ask_volumes=[15], mid_price=98.0),
            MarketSnapshot(day=1, timestamp=110, product="X",
                           bid_prices=[95.0], bid_volumes=[10],
                           ask_prices=[97.0], ask_volumes=[15], mid_price=96.0),
        ]
        bars = aggregator.aggregate_ohlc(snaps, interval=100)
        assert len(bars) == 2

        bar0 = bars[0]
        assert bar0["timestamp"] == 0
        assert bar0["open"] == 100.0
        assert bar0["high"] == 102.0
        assert bar0["low"] == 98.0
        assert bar0["close"] == 98.0

        bar1 = bars[1]
        assert bar1["timestamp"] == 100
        assert bar1["open"] == 96.0

    def test_empty_snapshots(self, aggregator):
        assert aggregator.aggregate_ohlc([], interval=100) == []

    def test_invalid_interval_raises(self, aggregator):
        with pytest.raises(ValueError):
            aggregator.aggregate_ohlc([], interval=0)
        with pytest.raises(ValueError):
            aggregator.aggregate_ohlc([], interval=-1)

    def test_volume_aggregation(self, aggregator):
        trades = [
            TradePrint(timestamp=50, buyer="A", seller="B",
                       symbol="X", price=100.0, quantity=10,
                       aggressor_side=OrderSide.BUY),
            TradePrint(timestamp=60, buyer="A", seller="B",
                       symbol="X", price=100.0, quantity=5,
                       aggressor_side=OrderSide.SELL),
        ]
        buckets = aggregator.aggregate_volume(trades, interval=100)
        assert len(buckets) == 1
        assert buckets[0]["volume"] == 15
        assert buckets[0]["buy_volume"] == 10
        assert buckets[0]["sell_volume"] == 5
