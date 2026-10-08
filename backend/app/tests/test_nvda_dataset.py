"""Lossless NVDA extraction, bounded loading, and shared Blob publication."""

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from vercel.blob.errors import BlobNotFoundError

from app.core.config import settings
from app.main import app
from app.services import nvda_dataset as module
from app.services.nvda_preparation import prepare

PRICE_HEADER = "day;timestamp;product;bid_price_1;bid_volume_1;ask_price_1;ask_volume_1;mid_price\n"
TRADE_HEADER = "timestamp;buyer;seller;symbol;currency;price;quantity\n"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    prices = tmp_path / "prices.csv"
    trades = tmp_path / "trades.csv"
    prices.write_text(PRICE_HEADER + "0;0;AMZN;99;10;101;10;100\n" +
                      "0;1;NVDA;99;10;101;10;100\n" +
                      "0;1;NVDA;99;10;101;10;100\n" +
                      "0;10;NVDA;100;10;102;10;101\n" +
                      "0;20;NVDA;101;10;103;10;102\n")
    trades.write_text(TRADE_HEADER + "0;;;NVDA;USD;100;1\n" +
                      "5;;;NVDA;USD;101;2\n" + "10;;;AMZN;USD;200;3\n" +
                      "20;;;NVDA;USD;102;3\n")
    root = tmp_path / "prepared"
    prepare(prices, trades, root, max_rows=2)
    monkeypatch.setattr(settings, "dataset_manifest", str(root / "manifest.json"))
    monkeypatch.setattr(module, "nvda_dataset", module.NVDADataset())
    return root


def test_lossless_filter_and_timestamp_boundaries(prepared):
    manifest = json.loads((prepared / "manifest.json").read_text())
    assert manifest["total_snapshots"] == 4
    assert manifest["total_trades"] == 3
    assert len(manifest["windows"]) == 2
    assert manifest["windows"][0]["start"] == 0  # includes trade before first snapshot
    first = module.nvda_dataset.load(0)
    second = module.nvda_dataset.load(1)
    assert first.get_products() == second.get_products() == ["NVDA"]
    assert [s.timestamp for s in first.get_snapshots("NVDA", 0)] == [1, 1]
    assert [s.timestamp for s in second.get_snapshots("NVDA", 0)] == [10, 20]
    assert [t.timestamp for t in first.get_trades("NVDA", 0)] == [0, 5]
    assert [t.timestamp for t in second.get_trades("NVDA", 0)] == [20]


def test_metadata_and_selected_range_routes(prepared):
    client = TestClient(app)
    data = client.get("/api/datasets").json()
    assert data["products"] == ["NVDA"] and data["days"] == [0] and data["loaded"]
    assert len(data["windows"]) == 2
    snapshots = client.get("/api/snapshots?product=NVDA&day=0&window=1").json()
    assert [s["timestamp"] for s in snapshots["snapshots"]] == [10, 20]
    assert client.get("/api/datasets?window=99").status_code == 400
    bars = client.get("/api/ohlcv?product=NVDA&day=0&window=1&interval=1").json()
    assert bars["count"] > 0
    session = client.post("/api/replay/start?window=1", json={"products": ["NVDA"], "days": [0]})
    assert session.status_code == 200 and session.json()["total_events"] == 3


def test_chunk_integrity_failure_is_detected(prepared):
    manifest = json.loads((prepared / "manifest.json").read_text())
    path = prepared / manifest["windows"][0]["prices"]["path"]
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        module.nvda_dataset.load()


def test_cache_is_bounded_and_unselected_chunks_are_not_loaded(prepared, monkeypatch):
    original = Path.read_bytes
    reads = []
    def tracked(path):
        reads.append(str(path))
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", tracked)
    module.nvda_dataset.load(0)
    assert len(reads) == 2
    module.nvda_dataset.load(0)
    assert len(reads) == 2
    module.nvda_dataset.load(1)
    assert len(reads) == 4 and len(module.nvda_dataset._views) <= 2


def test_rejects_lfs_pointer(tmp_path):
    prices = tmp_path / "prices.csv"
    prices.write_text("version https://git-lfs.github.com/spec/v1\n")
    with pytest.raises(ValueError, match="LFS"):
        prepare(prices, tmp_path / "trades.csv", tmp_path / "output")


def test_blob_manifest_is_published_last_and_seen_by_new_instances(prepared, monkeypatch):
    objects = {}
    writes = []
    class FakeBlob:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def put(self, path, body, **kwargs):
            assert kwargs["access"] == "private"
            objects[path] = body
            writes.append(path)
        def get(self, path, **kwargs):
            if path not in objects: raise BlobNotFoundError()
            return SimpleNamespace(content=objects[path], etag="version-1", status_code=200)
        def delete(self, path): objects.pop(path, None)
    monkeypatch.setattr(module, "BlobClient", FakeBlob)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-only")
    manifest = json.loads((prepared / "manifest.json").read_text())
    publisher = module.NVDADataset()
    publisher.publish_prepared(prepared, manifest)
    assert writes[-1] == module.MANIFEST_PATH and len(writes) == 6
    independent = module.NVDADataset()
    assert independent.load(1).dataset_source == "blob"
    assert len(independent.load(1).get_snapshots("NVDA", 0)) == 2
    publisher.reset()
    assert independent.load(0).dataset_source == "repository"


def test_real_bundle_counts_and_only_nvda():
    root = Path(__file__).resolve().parents[3] / "data/nvda"
    manifest = module.validate_manifest(json.loads((root / "manifest.json").read_text()))
    assert manifest["total_snapshots"] == sum(w["prices"]["rows"] for w in manifest["windows"])
    assert manifest["total_trades"] == sum(w["trades"]["rows"] for w in manifest["windows"])
    assert max(w["prices"]["rows"] for w in manifest["windows"]) < 11000


def test_admin_upload_replaces_nvda_ranges_and_excludes_other_stocks(prepared, monkeypatch):
    objects = {}
    class FakeBlob:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def put(self, path, body, **kwargs): objects[path] = body
        def get(self, path, **kwargs):
            if path not in objects: raise BlobNotFoundError()
            return SimpleNamespace(content=objects[path], etag="upload-1", status_code=200)
        def delete(self, path): objects.pop(path, None)
    monkeypatch.setattr(module, "BlobClient", FakeBlob)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-only")
    monkeypatch.setenv("IMC_DATA_ADMIN_TOKEN", "test-only-admin")
    client = TestClient(app)
    csv = PRICE_HEADER + "0;100;NVDA;199;10;201;10;200\n0;100;AMZN;99;10;101;10;100\n"
    files = [("files", ("prices_round_0_day_0.csv", csv, "text/csv"))]
    assert client.post("/api/datasets/upload", files=files).status_code == 401
    assert not objects
    response = client.post("/api/datasets/upload", files=files,
                           headers={"Authorization": "Bearer test-only-admin"})
    assert response.status_code == 200, response.text
    data = client.get("/api/datasets").json()
    assert data["products"] == ["NVDA"] and data["total_snapshots"] == 1
    assert data["source"] == "blob"
    snapshots = client.get("/api/snapshots?product=NVDA&window=0").json()
    assert snapshots["snapshots"][0]["mid_price"] == 200


def test_whole_day_is_default_and_chart_matches_all_raw_ticks(prepared):
    from app.engines.data.aggregator import DataAggregator
    client = TestClient(app)
    metadata = client.get("/api/datasets").json()
    assert metadata["window_id"] == -1
    response = client.get("/api/ohlcv?product=NVDA&day=0&interval=500").json()
    snapshots, trades = [], []
    for window in [0, 1]:
        ds = module.nvda_dataset.load(window)
        snapshots += ds.get_snapshots("NVDA", 0)
        trades += ds.get_trades("NVDA", 0)
    expected = DataAggregator().aggregate_ohlcv(snapshots, trades, 5000)
    assert response["bars"] == expected
    assert response["interval"] == 5000


def test_full_day_replay_crosses_chunks_and_seeks_without_materializing_all_events(prepared):
    from app.engines.replay.engine import ReplayEngine
    events = module.nvda_dataset.load(-1).get_event_stream(["NVDA"], [0])
    assert len(events) == 7 and not events.cache
    engine = ReplayEngine()
    engine.load_events(events)
    assert engine.events is events and not events.cache
    timestamps = [engine.step_forward().timestamp for _ in range(len(events))]
    assert timestamps == [0, 1, 1, 5, 10, 20, 20]
    assert engine.seek(20).timestamp == 20 and engine.current_index == 6
    assert engine.seek(5).timestamp == 5 and engine.current_index == 3
    assert len(events.cache) <= 2


def test_whole_day_backtest_matches_materialized_exact_execution(prepared):
    from app.engines.backtest.engine import BacktestEngine
    from app.models.backtest import BacktestConfig
    class Trader:
        def run(self, state):
            from app.engines.sandbox.adapter import Order
            orders = []
            if state.order_depths.get("NVDA"):
                depth = state.order_depths["NVDA"]
                orders = [Order("NVDA", max(depth.sell_orders), 1)]
            return {"NVDA": orders}, 0, ""
    events = module.nvda_dataset.load(-1).get_event_stream(["NVDA"], [0])
    config = BacktestConfig(strategy_id="full_day_test", products=["NVDA"], days=[0])
    streamed_engine, list_engine = BacktestEngine(config), BacktestEngine(config)
    streamed = streamed_engine.run(events, Trader())
    materialized = list_engine.run(list(events), Trader())
    assert streamed.status == materialized.status == "completed"
    assert streamed.metrics["performance"] == materialized.metrics["performance"]
    assert streamed.metrics["execution"] == materialized.metrics["execution"]
    assert streamed.metrics["pnl_history"] == materialized.metrics["pnl_history"]
    assert streamed.metrics["full_day"]["events_processed"] == 7
    assert not streamed_engine._book_engine.get_book_history("NVDA")
    assert [fill.model_dump() for fill in streamed_engine.get_fills()] == [fill.model_dump() for fill in list_engine.get_fills()]
