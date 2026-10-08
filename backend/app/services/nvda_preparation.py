"""Stream real CSVs into lossless NVDA-only, bounded price/trade ranges.

Usage: python scripts/prepare_nvda.py --prices PATH --trades PATH --output data/nvda
Input files must be hydrated CSVs, not Git LFS pointers. No downsampling occurs.
"""

import bisect
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def writer(path, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.TextIOWrapper(gzip.GzipFile(filename="", fileobj=path.open("wb"), mode="wb", mtime=0), encoding="utf-8", newline="")
    result = csv.writer(stream, delimiter=";", lineterminator="\n")
    result.writerow(header)
    return stream, result


def prepare(prices, trades, output, max_rows=10000):
    if (output / "manifest.json").exists():
        raise ValueError("Output already contains a manifest; use a fresh output directory.")
    windows = []
    stream = None
    previous = -1
    with prices.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source, delimiter=";")
        header = next(reader)
        if not {"product", "timestamp", "day", "bid_price_1", "ask_price_1"}.issubset(header):
            raise ValueError("Invalid price schema or unhydrated LFS pointer.")
        product, timestamp, day = (header.index(n) for n in ["product", "timestamp", "day"])
        for row in reader:
            if row[product].strip() != "NVDA" or int(row[day]) != 0:
                continue
            t = int(row[timestamp])
            if t < previous:
                raise ValueError("NVDA prices must be sorted by timestamp.")
            if stream is None or (windows[-1]["prices"]["rows"] >= max_rows and t != previous):
                if stream:
                    stream.close()
                index = len(windows)
                path = f"chunks/{index:04d}/prices.csv.gz"
                stream, csv_writer = writer(output / path, header)
                windows.append({"id": index, "day": 0, "start": t, "end": t,
                                "prices": {"path": path, "rows": 0}})
            csv_writer.writerow(row)
            windows[-1]["prices"]["rows"] += 1
            windows[-1]["end"] = t
            previous = t
    if stream:
        stream.close()
    if not windows:
        raise ValueError("No NVDA day-0 prices found.")
    starts = [w["start"] for w in windows]
    with trades.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source, delimiter=";")
        header = next(reader)
        if not {"symbol", "timestamp", "price", "quantity"}.issubset(header):
            raise ValueError("Invalid trade schema or unhydrated LFS pointer.")
        symbol, timestamp = (header.index(n) for n in ["symbol", "timestamp"])
        # Bound open handles: trade rows may arrive out of order.
        grouped = {w["id"]: [] for w in windows}
        for row in reader:
            if row[symbol].strip() == "NVDA":
                index = max(0, bisect.bisect_right(starts, int(row[timestamp])) - 1)
                grouped[index].append(row)
        for window in windows:
            path = f"chunks/{window['id']:04d}/trades.csv.gz"
            stream, csv_writer = writer(output / path, header)
            csv_writer.writerows(grouped[window["id"]])
            stream.close()
            window["trades"] = {"path": path, "rows": len(grouped[window["id"]])}
            if grouped[window["id"]]:
                times = [int(row[timestamp]) for row in grouped[window["id"]]]
                window["start"] = min(window["start"], min(times))
                window["end"] = max(window["end"], max(times))
    for window in windows:
        for kind in ["prices", "trades"]:
            chunk = window[kind]
            chunk["sha256"] = digest(output / chunk["path"])
            chunk["bytes"] = (output / chunk["path"]).stat().st_size
    manifest = {"version": 1, "product": "NVDA", "day": 0, "windows": windows,
                "total_snapshots": sum(w["prices"]["rows"] for w in windows),
                "total_trades": sum(w["trades"]["rows"] for w in windows),
                "source_sha256": {"prices": digest(prices), "trades": digest(trades)}}
    from app.services.nvda_overview import build_overview
    build_overview(output, manifest)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"windows": len(windows), "snapshots": manifest["total_snapshots"],
                      "trades": manifest["total_trades"],
                      "compressed_bytes": sum(w[k]["bytes"] for w in windows for k in ["prices", "trades"])}))
