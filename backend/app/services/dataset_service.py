"""High-level dataset management service for the IMC Prosperity terminal."""

import logging
import re
from typing import Optional

from backend.app.engines.data.aggregator import DataAggregator
from backend.app.engines.data.loader import DataLoader
from backend.app.engines.data.normalizer import DataNormalizer
from backend.app.models.events import Event
from backend.app.models.market import MarketSnapshot, TradePrint

logger = logging.getLogger(__name__)

_KEY_PATTERN = re.compile(r"(prices|trades)_round_(\d+)_day_([-]?\d+)")


class DatasetService:
    """
    Manages loaded IMC Prosperity datasets.

    Provides a convenient facade over ``DataLoader``, ``DataNormalizer``,
    and ``DataAggregator`` with in-memory caching of parsed objects.
    """

    def __init__(self) -> None:
        self._loader = DataLoader()
        self._normalizer = DataNormalizer()
        self._aggregator = DataAggregator()

        # Cache: keyed by (product, day)
        self._snapshots: dict[tuple[str, int], list[MarketSnapshot]] = {}
        self._trades: dict[tuple[str, int], list[TradePrint]] = {}

        # Metadata
        self._products: set[str] = set()
        self._days: set[int] = set()
        self._loaded_directory: Optional[str] = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_dataset(self, directory: str) -> dict:
        """
        Discover, load, and normalize all CSV files in *directory*.

        Returns a summary dict with keys ``products``, ``days``,
        ``total_snapshots``, ``total_trades``, ``files``.
        """
        datasets = self._loader.discover_datasets(directory)

        total_snapshots = 0
        total_trades = 0

        for key, filepath in datasets.items():
            match = _KEY_PATTERN.match(key)
            if not match:
                logger.warning("Skipping unrecognized dataset key: %s", key)
                continue

            kind = match.group(1)  # prices or trades
            day = int(match.group(3))

            try:
                if kind == "prices":
                    raw_snaps = self._loader.load_price_csv(filepath)
                    snaps = self._normalizer.normalize_snapshots(raw_snaps)
                    for snap in snaps:
                        cache_key = (snap.product, snap.day)
                        self._snapshots.setdefault(cache_key, []).append(snap)
                        self._products.add(snap.product)
                        self._days.add(snap.day)
                    total_snapshots += len(snaps)

                elif kind == "trades":
                    raw_trades = self._loader.load_trade_csv(filepath)
                    trades = self._normalizer.normalize_trades(raw_trades)
                    for trade in trades:
                        cache_key = (trade.symbol, day)
                        self._trades.setdefault(cache_key, []).append(trade)
                        self._products.add(trade.symbol)
                        self._days.add(day)
                    total_trades += len(trades)

            except Exception as exc:
                logger.error("Failed to load %s: %s", filepath, exc)

        # De-duplicate and sort cached lists
        for cache_key in self._snapshots:
            self._snapshots[cache_key].sort(key=lambda s: s.timestamp)
        for cache_key in self._trades:
            self._trades[cache_key].sort(key=lambda t: t.timestamp)

        self._loaded_directory = directory

        summary = {
            "directory": directory,
            "files": len(datasets),
            "products": sorted(self._products),
            "days": sorted(self._days),
            "total_snapshots": total_snapshots,
            "total_trades": total_trades,
        }
        logger.info("Dataset loaded: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_products(self) -> list[str]:
        """Return sorted list of all product names found in loaded data."""
        return sorted(self._products)

    def get_days(self) -> list[int]:
        """Return sorted list of all day values found in loaded data."""
        return sorted(self._days)

    def get_snapshots(
        self, product: str, day: Optional[int] = None
    ) -> list[MarketSnapshot]:
        """
        Return snapshots for the given product.

        If *day* is specified only that day's snapshots are returned;
        otherwise all days are combined and sorted by timestamp.
        """
        if day is not None:
            return list(self._snapshots.get((product, day), []))

        result: list[MarketSnapshot] = []
        for (p, _d), snaps in self._snapshots.items():
            if p == product:
                result.extend(snaps)
        result.sort(key=lambda s: (s.day, s.timestamp))
        return result

    def get_trades(
        self, product: str, day: Optional[int] = None
    ) -> list[TradePrint]:
        """
        Return trades for the given product (symbol).

        If *day* is specified only that day's trades are returned;
        otherwise all days are combined and sorted by timestamp.
        """
        if day is not None:
            return list(self._trades.get((product, day), []))

        result: list[TradePrint] = []
        for (s, _d), trades in self._trades.items():
            if s == product:
                result.extend(trades)
        result.sort(key=lambda t: t.timestamp)
        return result

    def get_event_stream(
        self,
        products: list[str],
        days: list[int],
    ) -> list[Event]:
        """
        Build a merged, chronologically-ordered event stream for the
        given products and days.

        Parameters
        ----------
        products : list[str]
            Product names to include.
        days : list[int]
            Day values to include.

        Returns
        -------
        list[Event]
        """
        all_snaps: list[MarketSnapshot] = []
        all_trades: list[TradePrint] = []

        for product in products:
            for day in days:
                all_snaps.extend(self._snapshots.get((product, day), []))
                all_trades.extend(self._trades.get((product, day), []))

        return self._normalizer.merge_to_event_stream(all_snaps, all_trades)
