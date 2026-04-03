"""Application configuration using pydantic-settings."""

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

    model_config = {"env_prefix": "IMC_"}


settings = Settings()
