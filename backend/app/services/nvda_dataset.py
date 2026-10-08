"""NVDA-only datasets: metadata first, one bounded time range loaded on demand."""

import gzip
import io
import hashlib
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from vercel.blob import BlobClient
from vercel.blob.errors import BlobNotFoundError
from fastapi import HTTPException

from app.core.config import settings
from app.services.dataset_service import DatasetService

MANIFEST_PATH = "imc/nvda/active-manifest.json"
MAX_CHUNK_BYTES = 8 * 1024 * 1024


def validate_manifest(manifest):
    if manifest.get("version") != 1 or manifest.get("product") != "NVDA" or manifest.get("day") != 0:
        raise ValueError("Expected an NVDA day-0 manifest.")
    windows = manifest.get("windows", [])
    if not windows or len(windows) > 10000:
        raise ValueError("Invalid dataset ranges.")
    previous = -1
    for index, window in enumerate(windows):
        if window["id"] != index or window["start"] <= previous or window["end"] < window["start"]:
            raise ValueError("Dataset ranges must be ordered and non-overlapping.")
        previous = window["end"]
        for kind in ["prices", "trades"]:
            chunk = window[kind]
            path = PurePosixPath(chunk["path"])
            if path.is_absolute() or ".." in path.parts or not str(path).endswith(".csv.gz"):
                raise ValueError("Invalid chunk path.")
            if not re.fullmatch(r"[a-f0-9]{64}", chunk["sha256"]):
                raise ValueError("Invalid chunk checksum.")
            if not 0 < chunk["bytes"] <= MAX_CHUNK_BYTES or not 0 <= chunk["rows"] <= 50000:
                raise ValueError("Chunk exceeds supported size.")
    if "overview" in manifest:
        overview = manifest["overview"]
        path = PurePosixPath(overview["path"])
        if (path.is_absolute() or ".." in path.parts or not str(path).endswith(".json.gz")
                or not re.fullmatch(r"[a-f0-9]{64}", overview["sha256"])
                or not 0 < overview["bytes"] <= MAX_CHUNK_BYTES
                or not 0 < overview["rows"] <= 50000
                or overview["interval"] != 5000):
            raise ValueError("Invalid whole-day overview.")
    return manifest


class WholeDayDataset(DatasetService):
    """Metadata and exact aggregated chart data; raw ticks stay in bounded chunks."""

    def __init__(self, repository):
        super().__init__()
        import copy
        self.repository = NVDADataset()
        self.repository._manifest = copy.deepcopy(repository._manifest)
        self.repository._source = repository._source

    def get_products(self): return ["NVDA"]
    def get_days(self): return [0]

    def get_ohlcv(self, product, day, interval):
        if interval <= 0:
            raise HTTPException(status_code=400, detail="Interval must be positive.")
        descriptor = self.repository._manifest["overview"]
        base = descriptor["interval"]
        interval = max(base, (interval + base - 1) // base * base)
        if product != "NVDA" or day not in (None, 0):
            return [], interval
        if not hasattr(self, "bars"):
            compressed = self.repository._read_chunk(descriptor)
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:
                raw = f.read(MAX_CHUNK_BYTES + 1)
            if len(raw) > MAX_CHUNK_BYTES:
                raise HTTPException(status_code=503, detail="Overview exceeds supported size.")
            self.bars = json.loads(raw)
            if len(self.bars) != descriptor["rows"]:
                raise HTTPException(status_code=503, detail="Overview row count mismatch.")
        merged = {}
        for bar in self.bars:
            timestamp = bar["timestamp"] // interval * interval
            if timestamp not in merged:
                merged[timestamp] = dict(bar, timestamp=timestamp)
            else:
                target = merged[timestamp]
                target.update(high=max(target["high"], bar["high"]),
                              low=min(target["low"], bar["low"]), close=bar["close"])
                for key in ["volume", "buy_volume", "sell_volume"]:
                    target[key] += bar[key]
        return list(merged.values()), interval

    def get_snapshots(self, *args, **kwargs):
        raise HTTPException(status_code=400, detail="Select a shorter time range to fetch raw snapshots or trade lists.")

    get_trades = get_snapshots
    def get_event_stream(self, products, days):
        if "NVDA" not in products or 0 not in days:
            return []
        from app.services.nvda_events import ChunkedEvents
        return ChunkedEvents(self.repository)


class NVDADataset:
    def __init__(self):
        self._lock = threading.RLock()
        self._manifest = None
        self._etag = None
        self._source = None
        self._views = OrderedDict()

    def _refresh(self):
        manifest = None
        source = "repository"
        import os
        if os.environ.get("BLOB_READ_WRITE_TOKEN"):
            with BlobClient() as client:
                try:
                    result = client.get(MANIFEST_PATH, access="private", use_cache=False,
                                        if_none_match=self._etag)
                    if result.status_code == 304:
                        return
                    manifest = validate_manifest(json.loads(result.content))
                    source = "blob"
                    etag = result.etag
                except BlobNotFoundError:
                    pass
        if manifest is None:
            if self._source == "repository":
                return
            manifest = validate_manifest(json.loads(Path(settings.dataset_manifest).read_text()))
            etag = None
        self._manifest = manifest
        self._etag = etag
        self._source = source
        self._views.clear()

    def _read_chunk(self, chunk):
        if self._source == "blob":
            with BlobClient() as client:
                compressed = client.get("imc/nvda/" + chunk["path"], access="private").content
        else:
            root = Path(settings.dataset_manifest).parent.resolve()
            path = (root / chunk["path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Chunk escapes dataset directory.")
            compressed = path.read_bytes()
        if len(compressed) != chunk["bytes"] or hashlib.sha256(compressed).hexdigest() != chunk["sha256"]:
            raise ValueError("Dataset chunk failed integrity verification.")
        return compressed

    def load(self, window_id=0):
        with self._lock:
            self._refresh()
            if window_id == -1 and "overview" not in self._manifest:
                raise ValueError("Publish an updated dataset with a whole-day overview first.")
            if window_id != -1 and not 0 <= window_id < len(self._manifest["windows"]):
                raise ValueError("Unknown dataset time range.")
            if window_id not in self._views:
                if window_id == -1:
                    service = WholeDayDataset(self)
                else:
                    service = self._load_window(window_id)
                service.window_id = window_id
                service.windows = [{"id": w["id"], "start": w["start"], "end": w["end"]}
                                   for w in self._manifest["windows"]]
                service.dataset_source = self._source
                service.total_snapshots = self._manifest["total_snapshots"]
                service.total_trades = self._manifest["total_trades"]
                self._views[window_id] = service
                if len(self._views) > 2:
                    self._views.popitem(last=False)
            self._views.move_to_end(window_id)
            return self._views[window_id]

    def _load_window(self, window_id):
        window = self._manifest["windows"][window_id]
        with TemporaryDirectory(prefix="nvda-range-") as directory:
            for kind in ["prices", "trades"]:
                chunk = window[kind]
                compressed = self._read_chunk(chunk)
                with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:
                    raw = f.read(MAX_CHUNK_BYTES + 1)
                if len(raw) > MAX_CHUNK_BYTES:
                    raise ValueError("Decompressed chunk exceeds supported size.")
                (Path(directory) / f"{kind}_round_0_day_0.csv").write_bytes(raw)
            service = DatasetService()
            summary = service.load_dataset(directory)
            if (summary["products"] != ["NVDA"] or summary["days"] != [0]
                    or summary["total_snapshots"] != window["prices"]["rows"]
                    or summary["total_trades"] != window["trades"]["rows"]):
                raise ValueError("Dataset chunk contents do not match the manifest.")
        return service

    def publish(self, files):
        from app.services.nvda_preparation import prepare
        from app.services.shared_dataset import parse_files
        parse_files(files)  # strict schema and request-size validation before writes
        prices = files.get("prices_round_0_day_0.csv")
        if prices is None:
            raise ValueError("Include prices_round_0_day_0.csv with NVDA data.")
        trades = files.get("trades_round_0_day_0.csv", "timestamp;buyer;seller;symbol;currency;price;quantity\n")
        with TemporaryDirectory(prefix="nvda-upload-") as directory:
            root = Path(directory)
            (root / "prices.csv").write_text(prices)
            (root / "trades.csv").write_text(trades)
            output = root / "prepared"
            prepare(root / "prices.csv", root / "trades.csv", output)
            manifest = json.loads((output / "manifest.json").read_text())
            self.publish_prepared(output, manifest)
        return {"source": "blob", "products": ["NVDA"], "days": [0],
                "total_snapshots": manifest["total_snapshots"], "total_trades": manifest["total_trades"]}

    def publish_prepared(self, root, manifest):
        """Upload immutable chunks first; publish the manifest only after all succeed."""
        validate_manifest(manifest)
        version = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        published = json.loads(json.dumps(manifest))
        with BlobClient() as client:
            for original, window in zip(manifest["windows"], published["windows"]):
                for kind in ["prices", "trades"]:
                    chunk = original[kind]
                    payload = (root / chunk["path"]).read_bytes()
                    if hashlib.sha256(payload).hexdigest() != chunk["sha256"]:
                        raise ValueError("Dataset chunk failed integrity verification.")
                    path = f"datasets/{version}/{chunk['path']}"
                    client.put("imc/nvda/" + path, payload, access="private", overwrite=True,
                               add_random_suffix=False, content_type="application/gzip")
                    window[kind]["path"] = path
            if "overview" in manifest:
                descriptor = manifest["overview"]
                payload = (root / descriptor["path"]).read_bytes()
                if hashlib.sha256(payload).hexdigest() != descriptor["sha256"]:
                    raise ValueError("Overview failed integrity verification.")
                path = f"datasets/{version}/{descriptor['path']}"
                client.put("imc/nvda/" + path, payload, access="private", overwrite=True,
                           add_random_suffix=False, content_type="application/gzip")
                published["overview"]["path"] = path
            client.put(MANIFEST_PATH, json.dumps(published).encode(), access="private",
                       overwrite=True, add_random_suffix=False, content_type="application/json",
                       cache_control_max_age=60)
        with self._lock:
            self._etag = None
            self._source = None
            self._views.clear()

    def reset(self):
        with self._lock, BlobClient() as client:
            client.delete(MANIFEST_PATH)
            self._etag = None
            self._source = None
            self._views.clear()


nvda_dataset = NVDADataset()
