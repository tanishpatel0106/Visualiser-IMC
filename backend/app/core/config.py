"""Application configuration using pydantic-settings."""

from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global settings for the IMC Prosperity trading terminal backend."""

    data_directory: str = "sample_data"
    storage_path: str = "storage/app.db"
    max_replay_speed: float = 100.0
    default_position_limit: int = 20
    strategy_timeout: float = 1.0
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        """Allow IMC_CORS_ORIGINS to be provided as comma-separated string."""
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @field_validator("data_directory", "storage_path", mode="after")
    @classmethod
    def _resolve_project_relative_paths(cls, value: str) -> str:
        """Resolve relative paths from the repository root.

        This keeps paths stable regardless of where uvicorn is started from
        (repo root, backend/, systemd unit, etc.).
        """
        path = Path(value).expanduser()
        if path.is_absolute():
            return str(path)
        repo_root = Path(__file__).resolve().parents[3]
        return str((repo_root / path).resolve())

    model_config = {"env_prefix": "IMC_"}


settings = Settings()
