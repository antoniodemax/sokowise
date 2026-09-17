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

    # --- AI copilot (docs/ARCHITECTURE.md §6, PRD §20) ---
    # Unset → the copilot endpoints answer 503 AI_NOT_CONFIGURED; the rest of the app works.
    anthropic_api_key: SecretStr | None = None
    ai_model: str = "claude-opus-5"
    ai_max_output_tokens: int = Field(default=2000, ge=256, le=8000)
    ai_thinking: Literal["adaptive", "disabled"] = "adaptive"
    ai_request_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    # Bounded tool loop per user message (ARCHITECTURE §6.4).
    ai_max_tool_rounds: int = Field(default=6, ge=1, le=12)
    # Conversation window sent to the model.
    ai_history_messages: int = Field(default=20, ge=2, le=100)
    # Server-side quotas per business, counted from ai_messages rows with role='user'
    # (PRD AI-8). Operators set these; no API lets an owner change them.
    ai_daily_message_limit: int = Field(default=10, ge=1)
    ai_monthly_message_limit: int = Field(default=100, ge=1)
    # Per-user burst limit on the ask endpoint (in-process, like the auth limits).
    rate_limit_ai_messages_per_minute: int = Field(default=10, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string (as set in .env) as well as a list.

        Entries are normalised to what a browser actually sends in `Origin`
        (`scheme://host[:port]`): surrounding whitespace and a trailing slash are dropped,
        because `http://localhost:5173/` in .env would otherwise silently fail the exact
        Origin comparison in `require_trusted_origin` and lock every browser out of login.
        """
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list | tuple):
            return value
        return [cls._normalise_origin(item) for item in items if str(item).strip()]

    @staticmethod
    def _normalise_origin(origin: object) -> str:
        return str(origin).strip().rstrip("/")

    @field_validator("cors_origin_regex", "cookie_domain", "jwt_issuer", "jwt_audience")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        """`.env` files set optional values to an empty string; treat that as unset."""
        return value or None

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def blank_key_is_none(cls, value: object) -> object:
        return None if value == "" else value

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
