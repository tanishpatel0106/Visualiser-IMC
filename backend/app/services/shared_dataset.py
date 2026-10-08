"""Atomic, shared CSV dataset replacements backed by private Vercel Blob."""

import json
import re
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from vercel.blob import BlobClient
from vercel.blob.errors import BlobNotFoundError

from app.core.config import settings
from app.engines.data.loader import DataLoader
from app.services.dataset_service import DatasetService

MAX_UPLOAD_BYTES = 3 * 1024 * 1024
DATASET_PATH = "imc/active-dataset.json"
CSV_NAME = re.compile(r"(?:prices|trades)_round_\d+_day_-?\d+\.csv")


def parse_files(files: dict[str, str]) -> tuple[DatasetService, dict]:
    """Validate every file before publishing any replacement."""
    if not files or len(files) > 32:
        raise ValueError("Upload between 1 and 32 CSV files.")
    if sum(len(content.encode("utf-8")) for content in files.values()) > MAX_UPLOAD_BYTES:
        raise ValueError("Combined CSV contents must be at most 3 MiB.")
    loader = DataLoader()
    with TemporaryDirectory(prefix="imc-data-") as directory:
        for name, content in files.items():
            if not CSV_NAME.fullmatch(name):
                raise ValueError("Use prices_round_N_day_D.csv or trades_round_N_day_D.csv filenames.")
            path = Path(directory) / name
            path.write_text(content, encoding="utf-8")
            # The normal service logs parsing errors; validate strictly here first.
            if name.startswith("prices_"):
                loader.load_price_csv(str(path))
            else:
                loader.load_trade_csv(str(path))
        service = DatasetService()
        summary = service.load_dataset(directory)
        if not summary["total_snapshots"]:
            raise ValueError("The replacement must contain nonempty price snapshots.")
    summary.pop("directory", None)
    summary["source"] = "blob"
    return service, summary


class SharedDataset:
    """Refresh per-instance snapshots using conditional, uncached Blob reads.

    The whole CSV collection is a single object, so readers never see a partially
    published upload. Concurrent admin uploads use last-completed-write wins.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._service = None
        self._etag = None
        self._source = None

    def load(self) -> DatasetService:
        with self._lock, BlobClient() as client:
            try:
                result = client.get(
                    DATASET_PATH, access="private", use_cache=False,
                    if_none_match=self._etag,
                )
            except BlobNotFoundError:
                if self._source != "repository":
                    service = DatasetService()
                    service.load_dataset(settings.data_directory)
                    self._service = service
                    self._source = "repository"
                    self._etag = None
                return self._service
            if result.status_code != 304:
                files = json.loads(result.content)
                service, _ = parse_files(files)
                self._service = service
                self._etag = result.etag
                self._source = "blob"
            return self._service

    def publish(self, files: dict[str, str]) -> dict:
        _, summary = parse_files(files)
        payload = json.dumps(files).encode("utf-8")
        with self._lock, BlobClient() as client:
            client.put(
                DATASET_PATH, payload, access="private", overwrite=True,
                add_random_suffix=False, content_type="application/json",
                cache_control_max_age=60,
            )
            # Reload from the shared source on the next request, including this instance.
            self._etag = None
        return summary

    def reset(self) -> None:
        with self._lock, BlobClient() as client:
            client.delete(DATASET_PATH)
            self._etag = None
            self._source = None


shared_dataset = SharedDataset()
