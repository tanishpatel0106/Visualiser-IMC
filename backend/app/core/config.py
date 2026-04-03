"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global settings for the IMC Prosperity trading terminal backend."""

    data_directory: str = "sample_data"
    storage_path: str = "storage/app.db"
    max_replay_speed: float = 100.0
    default_position_limit: int = 20
    strategy_timeout: float = 1.0
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_prefix": "IMC_"}


settings = Settings()
