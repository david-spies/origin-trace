"""
Centralized, environment-driven configuration.

Every tunable knob for the service lives here so that deployment behavior
(CORS, rate limiting, payload ceilings) is never hard-coded in route logic.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OT_", env_file=".env", extra="ignore")

    env: str = "production"
    app_name: str = "Origin Trace"
    log_level: str = "INFO"

    host: str = "127.0.0.1"
    port: int = 8000

    allowed_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    max_text_length: int = 500_000
    rate_limit_per_minute: int = 60
    max_upload_size_mb: int = 15

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — avoids re-parsing the environment per request."""
    return Settings()
