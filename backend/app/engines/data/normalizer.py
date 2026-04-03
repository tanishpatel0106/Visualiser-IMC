"""Data normalization and event-stream construction for IMC Prosperity data."""

import logging
from typing import Optional

import pandas as pd

from app.models.events import Event, EventType
from app.models.market import (
    BookLevel,
    MarketSnapshot,
    OrderSide,
    TradePrint,
    VisibleOrderBook,
)

logger = logging.getLogger(__name__)


class DataNormalizer:
    """
    Normalizes raw loaded data and merges snapshots and trades into a
    unified, chronologically-ordered event stream.
    """

    # ------------------------------------------------------------------
    # Snapshot normalization
    # ------------------------------------------------------------------
    def normalize_snapshots(
        self, snapshots: list[MarketSnapshot]
    ) -> list[MarketSnapshot]:
        """
        Clean and normalize a list of market snapshots.

        - Strips whitespace from product names.
        - Recomputes ``mid_price`` when it is missing but bid/ask level-1
          prices are available.
        - Sorts by (day, timestamp, product).

        Returns a new list (does not mutate in place).
        """
        normalized: list[MarketSnapshot] = []

        for snap in snapshots:
            product = snap.product.strip()

            # Recompute mid_price if missing and level-1 prices exist
            mid = snap.mid_price
            if mid is None and snap.bid_prices and snap.ask_prices:
                bp1 = snap.bid_prices[0]
                ap1 = snap.ask_prices[0]
                if bp1 is not None and ap1 is not None:
                    mid = (bp1 + ap1) / 2.0

            normalized.append(
                MarketSnapshot(
                    day=snap.day,
                    timestamp=snap.timestamp,
                    product=product,
                    bid_prices=list(snap.bid_prices),
                    bid_volumes=list(snap.bid_volumes),
                    ask_prices=list(snap.ask_prices),
                    ask_volumes=list(snap.ask_volumes),
                    mid_price=mid,
                    profit_and_loss=snap.profit_and_loss,
                )
            )

        normalized.sort(key=lambda s: (s.day, s.timestamp, s.product))
        logger.info("Normalized %d snapshots", len(normalized))
        return normalized

    # ------------------------------------------------------------------
    # Trade normalization
    # ------------------------------------------------------------------
    def normalize_trades(self, trades: list[TradePrint]) -> list[TradePrint]:
        """
        Clean and normalize a list of trade prints.

        - Strips whitespace from string fields.
        - Sorts by timestamp.

        Returns a new list (does not mutate in place).
        """
        normalized: list[TradePrint] = []

        for t in trades:
            normalized.append(
                TradePrint(
                    timestamp=t.timestamp,
                    buyer=t.buyer.strip(),
                    seller=t.seller.strip(),
                    symbol=t.symbol.strip(),
                    currency=t.currency.strip(),
                    price=t.price,
                    quantity=t.quantity,
                    aggressor_side=t.aggressor_side,
                )
            )

        normalized.sort(key=lambda t: t.timestamp)
        logger.info("Normalized %d trades", len(normalized))
        return normalized

    # ------------------------------------------------------------------
    # Event stream construction
    # ------------------------------------------------------------------
    def merge_to_event_stream(
        self,
        snapshots: list[MarketSnapshot],
        trades: list[TradePrint],
    ) -> list[Event]:
        """
        Merge snapshots and trades into a single chronologically-ordered
        event stream.

        Each snapshot becomes an ``Event`` with type
        ``EventType.BOOK_SNAPSHOT`` and its data stored under the ``data``
        dict.  Each trade becomes ``EventType.TRADE_PRINT``.

        Events are assigned monotonically increasing ``sequence_num``
        values starting from 1.

        Parameters
        ----------
        snapshots : list[MarketSnapshot]
        trades : list[TradePrint]

        Returns
        -------
        list[Event]
            Chronologically ordered event list.
        """
        events: list[Event] = []

        for snap in snapshots:
            events.append(
                Event(
                    event_type=EventType.BOOK_SNAPSHOT,
                    timestamp=snap.timestamp,
                    product=snap.product,
                    data=snap.model_dump(),
                )
            )

        for trade in trades:
            events.append(
                Event(
                    event_type=EventType.TRADE_PRINT,
                    timestamp=trade.timestamp,
                    product=trade.symbol,
                    data=trade.model_dump(),
                )
            )

        # Sort chronologically; ties broken by type (snapshots first)
        events.sort(key=lambda e: (e.timestamp, 0 if e.event_type == EventType.BOOK_SNAPSHOT else 1))

        # Assign sequence numbers
        for seq, event in enumerate(events, start=1):
            event.sequence_num = seq

        logger.info(
            "Merged %d snapshots + %d trades into %d events",
            len(snapshots),
            len(trades),
            len(events),
        )
        return events

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def filter_by_product(self, events: list[Event], product: str) -> list[Event]:
        """Return only events matching the given product name."""
        return [e for e in events if e.product == product]

    def filter_by_day(self, events: list[Event], day: int) -> list[Event]:
        """
        Return only events whose underlying data has the given day.

        For BOOK_SNAPSHOT events, ``data["day"]`` is checked.
        For TRADE_PRINT events, they are included if *any* snapshots on
        that day share the same timestamp range.  As a simple heuristic,
        trade events are included when ``data.get("day") == day`` or when
        the ``day`` key is absent (trade CSVs don't carry a day column,
        so they are typically associated with the file they came from).
        """
        filtered: list[Event] = []
        for e in events:
            event_day = e.data.get("day")
            if event_day is not None:
                if int(event_day) == day:
                    filtered.append(e)
            else:
                # Trade prints without a day field: include them
                filtered.append(e)
        return filtered

    # ------------------------------------------------------------------
    # Derived features
    # ------------------------------------------------------------------
    def compute_derived_features(
        self, snapshots: list[MarketSnapshot]
    ) -> pd.DataFrame:
        """
        Compute derived analytics columns from a list of snapshots.

        Returns a DataFrame with one row per snapshot and the following
        columns:

        - day, timestamp, product
        - bid_price_1, ask_price_1, bid_volume_1, ask_volume_1
        - mid : simple mid price
        - spread : ask_1 - bid_1
        - microprice : volume-weighted mid using level-1 quantities
        - imbalance : (bid_vol_1 - ask_vol_1) / (bid_vol_1 + ask_vol_1)
        - total_bid_depth, total_ask_depth
        - book_pressure : total_bid_depth / (total_bid_depth + total_ask_depth)
        - profit_and_loss
        """
        rows: list[dict] = []

        for snap in snapshots:
            bp1 = snap.bid_prices[0] if snap.bid_prices else None
            ap1 = snap.ask_prices[0] if snap.ask_prices else None
            bv1 = snap.bid_volumes[0] if snap.bid_volumes else None
            av1 = snap.ask_volumes[0] if snap.ask_volumes else None

            # Mid
            mid: Optional[float] = None
            if bp1 is not None and ap1 is not None:
                mid = (bp1 + ap1) / 2.0

            # Spread
            spread: Optional[float] = None
            if bp1 is not None and ap1 is not None:
                spread = ap1 - bp1

            # Microprice
            microprice: Optional[float] = None
            if bp1 is not None and ap1 is not None and bv1 is not None and av1 is not None:
                total_vol = bv1 + av1
                if total_vol > 0:
                    microprice = (bp1 * av1 + ap1 * bv1) / total_vol

            # Imbalance
            imbalance: Optional[float] = None
            if bv1 is not None and av1 is not None:
                total_vol = bv1 + av1
                if total_vol > 0:
                    imbalance = (bv1 - av1) / total_vol

            # Depth sums
            total_bid = sum(v for v in snap.bid_volumes if v is not None)
            total_ask = sum(v for v in snap.ask_volumes if v is not None)

            # Book pressure
            book_pressure: Optional[float] = None
            total_depth = total_bid + total_ask
            if total_depth > 0:
                book_pressure = total_bid / total_depth

            rows.append(
                {
                    "day": snap.day,
                    "timestamp": snap.timestamp,
                    "product": snap.product,
                    "bid_price_1": bp1,
                    "ask_price_1": ap1,
                    "bid_volume_1": bv1,
                    "ask_volume_1": av1,
                    "mid": mid,
                    "spread": spread,
                    "microprice": microprice,
                    "imbalance": imbalance,
                    "total_bid_depth": total_bid,
                    "total_ask_depth": total_ask,
                    "book_pressure": book_pressure,
                    "profit_and_loss": snap.profit_and_loss,
                }
            )

        df = pd.DataFrame(rows)
        logger.info(
            "Computed derived features for %d snapshots (%d columns)",
            len(df),
            len(df.columns),
        )
        return df
