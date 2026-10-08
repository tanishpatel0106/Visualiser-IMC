"""Compute exact full-day OHLCV without retaining raw snapshots in memory."""

import csv
import gzip
import hashlib
import json

INTERVAL = 5000


def build_overview(root, manifest):
    bars = {}
    for window in manifest["windows"]:
        with gzip.open(root / window["prices"]["path"], "rt") as f:
            for row in csv.DictReader(f, delimiter=";"):
                timestamp = int(row["timestamp"]) // INTERVAL * INTERVAL
                mid = float(row["mid_price"]) if row["mid_price"] else (
                    float(row["bid_price_1"]) + float(row["ask_price_1"])) / 2
                if timestamp not in bars:
                    bars[timestamp] = {"timestamp": timestamp, "product": "NVDA",
                                       "open": mid, "high": mid, "low": mid, "close": mid,
                                       "volume": 0, "buy_volume": 0, "sell_volume": 0}
                else:
                    bar = bars[timestamp]
                    bar.update(high=max(bar["high"], mid), low=min(bar["low"], mid), close=mid)
    # Aggregate trades after all OHLC buckets exist, including chunk boundaries.
    for window in manifest["windows"]:
        with gzip.open(root / window["trades"]["path"], "rt") as f:
            for row in csv.DictReader(f, delimiter=";"):
                timestamp = int(row["timestamp"]) // INTERVAL * INTERVAL
                if timestamp in bars:
                    quantity = int(row["quantity"])
                    bars[timestamp]["volume"] += quantity
                    bars[timestamp]["buy_volume"] += quantity
    payload = json.dumps([bars[t] for t in sorted(bars)], separators=(",", ":")).encode()
    compressed = gzip.compress(payload, mtime=0)
    (root / "overview.json.gz").write_bytes(compressed)
    manifest["overview"] = {"path": "overview.json.gz", "sha256": hashlib.sha256(compressed).hexdigest(),
                            "bytes": len(compressed), "rows": len(bars), "interval": INTERVAL}
    return manifest
