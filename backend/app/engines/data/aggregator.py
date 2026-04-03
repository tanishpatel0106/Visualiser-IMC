"""OHLCV aggregation engine for IMC Prosperity market data."""

import logging
from typing import Optional

from app.models.market import MarketSnapshot, TradePrint

logger = logging.getLogger(__name__)


class DataAggregator:
    """
    Aggregates raw tick-level market snapshots and trades into OHLCV
    bars for charting.
    """

    # ------------------------------------------------------------------
    # OHLC from mid-price snapshots
    # ------------------------------------------------------------------
    def aggregate_ohlc(
        self,
        snapshots: list[MarketSnapshot],
        interval: int,
    ) -> list[dict]:
        """
        Build OHLC bars from snapshot mid-prices.

        Parameters
        ----------
        snapshots : list[MarketSnapshot]
            Must be sorted by timestamp.  Only snapshots with a
            computable mid-price (level-1 bid and ask present) are used.
        interval : int
            Bar width in timestamp units (e.g. 100 for 100-tick bars).

        Returns
        -------
        list[dict]
            Each dict has keys: ``timestamp``, ``open``, ``high``,
            ``low``, ``close``, ``product``.
        """
        if interval <= 0:
            raise ValueError(f"Interval must be positive, got {interval}")

        if not snapshots:
            return []

        # Group by product first
        by_product: dict[str, list[MarketSnapshot]] = {}
        for snap in snapshots:
            by_product.setdefault(snap.product, []).append(snap)

        bars: list[dict] = []

        for product, snaps in by_product.items():
            snaps_sorted = sorted(snaps, key=lambda s: s.timestamp)
            current_bar: Optional[dict] = None

            for snap in snaps_sorted:
                mid = self._compute_mid(snap)
                if mid is None:
                    continue

                bar_ts = (snap.timestamp // interval) * interval

                if current_bar is None or current_bar["timestamp"] != bar_ts:
                    # Flush previous bar
                    if current_bar is not None:
                        bars.append(current_bar)
                    current_bar = {
                        "timestamp": bar_ts,
                        "open": mid,
                        "high": mid,
                        "low": mid,
                        "close": mid,
                        "product": product,
                    }
                else:
                    current_bar["high"] = max(current_bar["high"], mid)
                    current_bar["low"] = min(current_bar["low"], mid)
                    current_bar["close"] = mid

            if current_bar is not None:
                bars.append(current_bar)

        bars.sort(key=lambda b: (b["product"], b["timestamp"]))
        logger.info(
            "Aggregated %d OHLC bars (interval=%d) from %d snapshots",
            len(bars),
            interval,
            len(snapshots),
        )
        return bars

    # ------------------------------------------------------------------
    # Volume from trades
    # ------------------------------------------------------------------
    def aggregate_volume(
        self,
        trades: list[TradePrint],
        interval: int,
    ) -> list[dict]:
        """
        Aggregate trade volume into time buckets.

        Parameters
        ----------
        trades : list[TradePrint]
            Must be sorted by timestamp.
        interval : int
            Bucket width in timestamp units.

        Returns
        -------
        list[dict]
            Each dict has keys: ``timestamp``, ``symbol``, ``volume``,
            ``buy_volume``, ``sell_volume``.
        """
        if interval <= 0:
            raise ValueError(f"Interval must be positive, got {interval}")

        if not trades:
            return []

        # Group by symbol
        by_symbol: dict[str, list[TradePrint]] = {}
        for t in trades:
            by_symbol.setdefault(t.symbol, []).append(t)

        buckets: list[dict] = []

        for symbol, sym_trades in by_symbol.items():
            sym_trades_sorted = sorted(sym_trades, key=lambda t: t.timestamp)
            agg: dict[int, dict] = {}

            for t in sym_trades_sorted:
                bar_ts = (t.timestamp // interval) * interval
                if bar_ts not in agg:
                    agg[bar_ts] = {
                        "timestamp": bar_ts,
                        "symbol": symbol,
                        "volume": 0,
                        "buy_volume": 0,
                        "sell_volume": 0,
                    }
                agg[bar_ts]["volume"] += t.quantity

                # Heuristic: if aggressor_side is set, use it; otherwise
                # treat as buy volume (conservative default).
                if t.aggressor_side is not None:
                    if t.aggressor_side.value == "BUY":
                        agg[bar_ts]["buy_volume"] += t.quantity
                    else:
                        agg[bar_ts]["sell_volume"] += t.quantity
                else:
                    # Default: split evenly is not useful; mark as buy
                    agg[bar_ts]["buy_volume"] += t.quantity

            buckets.extend(sorted(agg.values(), key=lambda b: b["timestamp"]))

        buckets.sort(key=lambda b: (b["symbol"], b["timestamp"]))
        logger.info(
            "Aggregated %d volume buckets (interval=%d) from %d trades",
            len(buckets),
            interval,
            len(trades),
        )
        return buckets

    # ------------------------------------------------------------------
    # Combined OHLCV
    # ------------------------------------------------------------------
    def aggregate_ohlcv(
        self,
        snapshots: list[MarketSnapshot],
        trades: list[TradePrint],
        interval: int,
    ) -> list[dict]:
        """
        Build combined OHLCV bars by merging OHLC from snapshots with
        volume from trades.

        Each returned dict has keys: ``timestamp``, ``product``,
        ``open``, ``high``, ``low``, ``close``, ``volume``,
        ``buy_volume``, ``sell_volume``.

        If there are no trades for a bar the volume fields default to 0.
        If there are trades without a corresponding snapshot bar they are
        ignored (volume-only bars are not emitted).
        """
        ohlc_bars = self.aggregate_ohlc(snapshots, interval)
        vol_buckets = self.aggregate_volume(trades, interval)

        # Index volume by (symbol, timestamp)
        vol_index: dict[tuple[str, int], dict] = {}
        for vb in vol_buckets:
            vol_index[(vb["symbol"], vb["timestamp"])] = vb

        ohlcv: list[dict] = []
        for bar in ohlc_bars:
            key = (bar["product"], bar["timestamp"])
            vol = vol_index.get(key, {})
            ohlcv.append(
                {
                    "timestamp": bar["timestamp"],
                    "product": bar["product"],
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": vol.get("volume", 0),
                    "buy_volume": vol.get("buy_volume", 0),
                    "sell_volume": vol.get("sell_volume", 0),
                }
            )

        logger.info(
            "Aggregated %d OHLCV bars (interval=%d)",
            len(ohlcv),
            interval,
        )
        return ohlcv

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_mid(snap: MarketSnapshot) -> Optional[float]:
        """Return mid-price from level-1 bid/ask, or the stored mid."""
        if snap.mid_price is not None:
            return snap.mid_price
        if snap.bid_prices and snap.ask_prices:
            bp1 = snap.bid_prices[0]
            ap1 = snap.ask_prices[0]
            if bp1 is not None and ap1 is not None:
                return (bp1 + ap1) / 2.0
        return None
