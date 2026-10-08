"""Shared dataset validation, admin access, and persistence across instances."""

import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from vercel.blob.errors import BlobNotFoundError

from app.core.config import settings
from app.main import app
from app.services import shared_dataset as module

NAME = "prices_round_0_day_1.csv"
HEADER = "day;timestamp;product;bid_price_1;bid_volume_1;ask_price_1;ask_volume_1;mid_price\n"
REPOSITORY = HEADER + "1;0;ORIGINAL;99;10;101;10;100\n"
REPLACEMENT = HEADER + "1;0;REPLACEMENT;199;10;201;10;200\n"


@pytest.fixture
def blob(monkeypatch, tmp_path):
    state = {"payload": None, "version": 0, "writes": 0}

    class FakeBlob:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, path, **kwargs):
            assert path == module.DATASET_PATH
            assert kwargs["access"] == "private" and kwargs["use_cache"] is False
            if state["payload"] is None:
                raise BlobNotFoundError()
            etag = str(state["version"])
            return SimpleNamespace(
                status_code=304 if kwargs.get("if_none_match") == etag else 200,
                content=state["payload"], etag=etag,
            )

        def put(self, path, content, **kwargs):
            assert kwargs["access"] == "private"
            assert kwargs["overwrite"] and not kwargs["add_random_suffix"]
            state["payload"] = content
            state["version"] += 1
            state["writes"] += 1

        def delete(self, path):
            state["payload"] = None

    (tmp_path / NAME).write_text(REPOSITORY)
    monkeypatch.setattr(settings, "data_directory", str(tmp_path))
    monkeypatch.setattr(settings, "dataset_manifest", "")
    monkeypatch.setattr(module, "BlobClient", FakeBlob)
    monkeypatch.setattr(module, "shared_dataset", module.SharedDataset())
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-only-blob-token")
    monkeypatch.setenv("IMC_DATA_ADMIN_TOKEN", "test-only-admin")
    return state


def test_upload_is_visible_to_existing_and_new_instances(blob):
    first = module.SharedDataset()
    second = module.SharedDataset()
    assert first.load().get_products() == ["ORIGINAL"]
    assert second.load().get_products() == ["ORIGINAL"]
    first.publish({NAME: REPLACEMENT})
    assert first.load().get_products() == ["REPLACEMENT"]
    assert second.load().get_products() == ["REPLACEMENT"]
    assert module.SharedDataset().load().get_products() == ["REPLACEMENT"]
    assert second.load().get_products() == ["REPLACEMENT"]  # conditional 304


def test_reset_restores_repository_on_all_instances(blob):
    first, second = module.SharedDataset(), module.SharedDataset()
    first.publish({NAME: REPLACEMENT})
    assert second.load().get_products() == ["REPLACEMENT"]
    first.reset()
    assert first.load().get_products() == ["ORIGINAL"]
    assert second.load().get_products() == ["ORIGINAL"]


@pytest.mark.parametrize("files", [
    {}, {"../" + NAME: REPLACEMENT}, {NAME: "invalid schema"},
    {NAME: HEADER}, {NAME: REPLACEMENT, "trades_round_0_day_1.csv": "invalid"},
])
def test_invalid_upload_never_overwrites_valid_dataset(blob, files):
    shared = module.SharedDataset()
    shared.publish({NAME: REPLACEMENT})
    with pytest.raises(ValueError):
        shared.publish(files)
    assert blob["writes"] == 1
    assert shared.load().get_products() == ["REPLACEMENT"]


def test_public_reads_and_admin_only_upload_and_reset(blob):
    client = TestClient(app)
    assert client.get("/api/products").json()["products"] == ["ORIGINAL"]
    files = [("files", (NAME, REPLACEMENT, "text/csv"))]
    assert client.post("/api/datasets/upload", files=files).status_code == 401
    assert client.post("/api/datasets/reset").status_code == 401
    headers = {"Authorization": "Bearer test-only-admin"}
    response = client.post("/api/datasets/upload", files=files, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "blob"
    assert client.get("/api/products").json()["products"] == ["REPLACEMENT"]
    assert client.post("/api/datasets/reset", headers=headers).status_code == 200
    assert client.get("/api/products").json()["products"] == ["ORIGINAL"]


def test_duplicate_and_oversize_files_are_rejected(blob):
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-only-admin"}
    file = ("files", (NAME, REPLACEMENT, "text/csv"))
    assert client.post("/api/datasets/upload", files=[file, file], headers=headers).status_code == 400
    big = ("files", (NAME, b"a" * (module.MAX_UPLOAD_BYTES + 1), "text/csv"))
    assert client.post("/api/datasets/upload", files=[big], headers=headers).status_code == 413
    assert blob["writes"] == 0


def test_missing_credentials_fail_closed(blob, monkeypatch):
    client = TestClient(app)
    files = [("files", (NAME, REPLACEMENT, "text/csv"))]
    monkeypatch.delenv("IMC_DATA_ADMIN_TOKEN")
    assert client.post("/api/datasets/upload", files=files).status_code == 503
    monkeypatch.setenv("IMC_DATA_ADMIN_TOKEN", "test-only-admin")
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN")
    assert client.post("/api/datasets/upload", files=files,
                       headers={"Authorization": "Bearer test-only-admin"}).status_code == 503


def test_directory_loading_disabled_with_shared_storage(blob):
    response = TestClient(app).post("/api/datasets/load", json={"directory": "/tmp"})
    assert response.status_code == 403


def test_storage_failure_does_not_silently_serve_stale_data(blob, monkeypatch):
    def unavailable(self):
        raise RuntimeError("storage unavailable")
    monkeypatch.setattr(module.SharedDataset, "load", unavailable)
    response = TestClient(app).get("/api/products")
    assert response.status_code == 503
