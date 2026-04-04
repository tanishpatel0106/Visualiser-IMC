"""Tests for application settings parsing."""

from pathlib import Path

from app.core.config import Settings


def test_default_cors_origins_include_common_local_ports():
    s = Settings()
    assert "http://localhost:3000" in s.cors_origins
    assert "http://localhost:5173" in s.cors_origins


def test_cors_origins_accept_comma_separated_string():
    s = Settings(cors_origins="http://a.local,http://b.local")
    assert s.cors_origins == ["http://a.local", "http://b.local"]


def test_relative_paths_are_resolved_from_repo_root():
    s = Settings(data_directory="sample_data", storage_path="storage/app.db")
    assert Path(s.data_directory).is_absolute()
    assert Path(s.storage_path).is_absolute()
    assert Path(s.data_directory).name == "sample_data"
    assert Path(s.storage_path).name == "app.db"
