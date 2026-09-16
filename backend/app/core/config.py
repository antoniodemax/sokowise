"""Application settings, loaded from environment variables.

Variable names follow docs/ARCHITECTURE.md §10. Missing required values make the
application refuse to start; nothing here has a secret default.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
CookieSameSite = Literal["lax", "strict", "none"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: AppEnv
    app_name: str = "SokoWise API"
    api_host: str = "0.0.0.0"  # noqa: S104 — the container binds all interfaces by design
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = "INFO"
    # NoDecode: read the raw env string; the validator below splits it on commas.
    cors_origins: Annotated[list[str], NoDecode]
    # Optional regex for origins that cannot be listed exactly, such as Vercel preview
    # deployments (`^https://sokowise-[a-z0-9-]+\.vercel\.app$`). ARCHITECTURE §5.1.
    cors_origin_regex: str | None = None
    # postgresql+asyncpg://user:password@host:port/database (docs/ARCHITECTURE.md §10).
    database_url: PostgresDsn

    # --- Authentication (docs/ARCHITECTURE.md §5) ---
    # HS256 signing key for access tokens; at least 32 characters, never defaulted.
    jwt_secret: SecretStr = Field(min_length=32)
    # Optional `iss` / `aud` claims; validated on every token when set.
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    # Refresh-token cookie. `Secure` is mandatory in production; `SameSite=None` (needed
    # only when the app and API are cross-site, e.g. Vercel previews) also requires it.
    cookie_domain: str | None = None
    cookie_secure: bool = True
    cookie_samesite: CookieSameSite = "lax"
    # Per-process counters; see ARCHITECTURE §5.2 for what that means with several workers.
    rate_limit_login_per_minute: int = Field(default=5, ge=1)
    rate_limit_register_per_minute: int = Field(default=5, ge=1)
    rate_limit_refresh_per_minute: int = Field(default=30, ge=1)
    rate_limit_password_change_per_minute: int = Field(default=5, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string (as set in .env) as well as a list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origin_regex", "cookie_domain", "jwt_issuer", "jwt_audience")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        """`.env` files set optional values to an empty string; treat that as unset."""
        return value or None

    @field_validator("database_url")
    @classmethod
    def require_asyncpg_driver(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme != "postgresql+asyncpg":
            msg = "DATABASE_URL must use the postgresql+asyncpg:// scheme"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def check_cookie_security(self) -> "Settings":
        if self.is_production and not self.cookie_secure:
            msg = "COOKIE_SECURE must be true in production"
            raise ValueError(msg)
        if self.cookie_samesite == "none" and not self.cookie_secure:
            msg = "COOKIE_SAMESITE=none requires COOKIE_SECURE=true (browsers reject it otherwise)"
            raise ValueError(msg)
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process. Tests call `get_settings.cache_clear()`."""
    return Settings()
