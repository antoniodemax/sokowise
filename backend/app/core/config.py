"""Application settings, loaded from environment variables.

Variable names follow docs/ARCHITECTURE.md §10. Missing required values make the
application refuse to start; nothing here has a secret default.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.schemas.identifiers import normalize_email, normalize_phone

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
CookieSameSite = Literal["lax", "strict", "none"]
SmsProvider = Literal["none", "console", "africastalking"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: AppEnv
    app_name: str = "SokoWise API"
    api_host: str = "0.0.0.0"  # noqa: S104 — the container binds all interfaces by design
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = "INFO"
    # Error reporting (docs/ARCHITECTURE.md §9). Unset → Sentry is not initialised.
    sentry_dsn: str | None = None
    # NoDecode: read the raw env string; the validator below splits it on commas.
    cors_origins: Annotated[list[str], NoDecode]
    # Optional regex for origins that cannot be listed exactly, such as Vercel preview
    # deployments (`^https://sokowise-[a-z0-9-]+\.vercel\.app$`). ARCHITECTURE §5.1.
    cors_origin_regex: str | None = None
    # postgresql+asyncpg://user:password@host:port/database (docs/ARCHITECTURE.md §10).
    database_url: PostgresDsn
    # Connection pool per process and the server-side statement timeout (§3.4). A stuck
    # statement (lock wait, runaway query) is cancelled instead of holding a connection.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_statement_timeout_ms: int = Field(default=30_000, ge=1_000, le=600_000)

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

    # --- Sign in with Google (docs/ARCHITECTURE.md §5.1) ---
    # The OAuth "Web application" client id whose ID tokens we accept. Unset → the Google
    # endpoints answer 503 GOOGLE_NOT_CONFIGURED and the frontend hides the button.
    google_client_id: str | None = None

    # --- SMS for password reset codes (docs/ARCHITECTURE.md §5.1) ---
    # `none` → reset endpoints answer 503; `console` logs the message (development only,
    # refused in production); `africastalking` sends through Africa's Talking.
    sms_provider: SmsProvider = "none"
    africastalking_username: str | None = None
    africastalking_api_key: SecretStr | None = None
    africastalking_sender_id: str | None = None
    rate_limit_password_reset_per_minute: int = Field(default=5, ge=1)
    rate_limit_password_reset_per_phone_per_minute: int = Field(default=3, ge=1)
    rate_limit_password_reset_confirm_per_phone_per_minute: int = Field(default=10, ge=1)

    # --- Platform admin (docs/ARCHITECTURE.md §5.4) ---
    # Phone numbers (any accepted form; normalised to E.164) of the people who may open the
    # operator dashboard at /api/v1/admin/*. Empty → those endpoints answer 404 for everyone.
    # Read on every request; never stored in the database or the token.
    platform_admin_phones: Annotated[list[str], NoDecode] = []
    # Same, by email (lower-cased). A user matches if either their phone or email is listed.
    platform_admin_emails: Annotated[list[str], NoDecode] = []

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

    # --- Supplier receipts (docs/ARCHITECTURE.md §6.7) ---
    # Where receipt images are kept. Local filesystem in development; an object-storage
    # backend is the production path (same key layout). Relative paths resolve from the
    # process working directory.
    receipt_storage_dir: str = "var/receipts"
    receipt_max_bytes: int = Field(default=8 * 1024 * 1024, ge=64 * 1024, le=32 * 1024 * 1024)
    receipt_max_pixels: int = Field(default=25_000_000, ge=1_000_000)
    receipt_min_side_px: int = Field(default=200, ge=32)

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

    @field_validator("platform_admin_phones", mode="before")
    @classmethod
    def split_admin_phones(cls, value: object) -> object:
        """Accept a comma-separated string; normalise each entry to E.164 (`+2547…`)."""
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list | tuple):
            return value
        return [normalize_phone(str(item)) for item in items if str(item).strip()]

    @field_validator("platform_admin_emails", mode="before")
    @classmethod
    def split_admin_emails(cls, value: object) -> object:
        """Accept a comma-separated string; normalise each entry (trimmed, lower-cased)."""
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list | tuple):
            return value
        return [normalize_email(str(item)) for item in items if str(item).strip()]

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origins(cls, value: list[str]) -> list[str]:
        """The allow-list doubles as the CSRF Origin check, so `*` can never be an entry."""
        if any(item == "*" or item.startswith("*") for item in value):
            msg = "CORS_ORIGINS must list exact origins; a wildcard is not allowed"
            raise ValueError(msg)
        return value

    @field_validator(
        "cors_origin_regex", "cookie_domain", "jwt_issuer", "jwt_audience", "sentry_dsn"
    )
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        """`.env` files set optional values to an empty string; treat that as unset."""
        return value or None

    @field_validator(
        "anthropic_api_key",
        "google_client_id",
        "africastalking_username",
        "africastalking_api_key",
        "africastalking_sender_id",
        mode="before",
    )
    @classmethod
    def blank_key_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("africastalking_username", "africastalking_sender_id", "google_client_id")
    @classmethod
    def strip_credentials(cls, value: str | None) -> str | None:
        """Values pasted into a hosting dashboard often carry a stray space or newline, which
        makes the HTTP client refuse the header (`LocalProtocolError`)."""
        return value.strip() if value is not None else None

    @field_validator("africastalking_api_key")
    @classmethod
    def strip_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        stripped = value.get_secret_value().strip()
        return SecretStr(stripped) if stripped else None

    @model_validator(mode="after")
    def check_sms_provider(self) -> "Settings":
        if self.sms_provider == "africastalking" and not (
            self.africastalking_username and self.africastalking_api_key
        ):
            msg = "SMS_PROVIDER=africastalking needs AFRICASTALKING_USERNAME and _API_KEY"
            raise ValueError(msg)
        if self.sms_provider == "console" and self.is_production:
            msg = "SMS_PROVIDER=console would log reset codes; not allowed in production"
            raise ValueError(msg)
        return self

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

    @model_validator(mode="after")
    def check_production_configuration(self) -> "Settings":
        """Refuse to start production with development placeholders (docs/OPERATIONS.md)."""
        if not self.is_production:
            return self
        if self.jwt_secret.get_secret_value().startswith("change-me"):
            msg = "JWT_SECRET still holds the .env.example placeholder"
            raise ValueError(msg)
        if self.cors_origin_regex in {".*", "^.*$", ".+", "^.+$"}:
            msg = "CORS_ORIGIN_REGEX must not match every origin"
            raise ValueError(msg)
        if not self.receipt_storage_dir.startswith("/"):
            msg = (
                "RECEIPT_STORAGE_DIR must be an absolute path to persistent storage in "
                "production (a mounted volume); the relative default is development-only"
            )
            raise ValueError(msg)
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process. Tests call `get_settings.cache_clear()`."""
    return Settings()
