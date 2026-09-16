"""Application settings, loaded from environment variables.

Variable names follow docs/ARCHITECTURE.md §10. Missing required values make the
application refuse to start; nothing here has a secret default.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: AppEnv
    app_name: str = "SokoWise API"
    api_host: str = "0.0.0.0"  # noqa: S104 — the container binds all interfaces by design
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = "INFO"
    # NoDecode: read the raw env string; the validator below splits it on commas.
    cors_origins: Annotated[list[str], NoDecode]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string (as set in .env) as well as a list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process. Tests call `get_settings.cache_clear()`."""
    return Settings()
