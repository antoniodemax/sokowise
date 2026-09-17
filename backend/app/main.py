"""FastAPI application factory. Uvicorn serves `app.main:app`."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.provider import build_provider
from app.ai.receipts import build_receipt_provider
from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.ratelimit import RateLimiter
from app.db.session import create_engine, create_session_factory
from app.middleware.request_id import REQUEST_ID_HEADER, RequestIDMiddleware
from app.storage import LocalFileStorage

logger = logging.getLogger(__name__)


def expected_migration_head() -> str | None:
    """The newest Alembic revision shipped with this build, for the readiness check.

    None when the migration scripts are not next to the package (an unusual layout);
    the readiness check then reports the migration state as unknown rather than failing.
    """
    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not ini.is_file():
        return None
    config = AlembicConfig(str(ini))
    config.set_main_option("script_location", str(ini.parent / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def init_error_reporting(settings: Settings) -> None:
    """Sentry, only when SENTRY_DSN is set (docs/ARCHITECTURE.md §9).

    No PII by default, no request bodies ever; the request id is attached as a tag by
    the request-ID middleware so an error can be matched to its log lines.
    """
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """One engine per process; routes get sessions from `app.state.session_factory`."""
    engine = create_engine(app.state.settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    init_error_reporting(settings)
    if settings.is_production and not os.environ.get("FORWARDED_ALLOW_IPS"):
        logger.warning(
            "FORWARDED_ALLOW_IPS is not set: behind a proxy every client shares the proxy's "
            "address, so per-IP rate limits and audit ip values are wrong (docs/OPERATIONS.md)"
        )

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs stay off in production until an auth story exists for them.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    # Per-process counters for the auth endpoints (docs/ARCHITECTURE.md §5.2).
    app.state.rate_limiter = RateLimiter()
    # The copilot's model client; None until ANTHROPIC_API_KEY is configured (§6).
    app.state.ai_provider = build_provider(settings)
    # Supplier receipts: blob storage plus the image→structure provider (§6.7).
    storage = LocalFileStorage(settings.receipt_storage_dir)
    storage.ensure_ready()  # a bad RECEIPT_STORAGE_DIR fails here, not on the first upload
    app.state.receipt_storage = storage
    app.state.receipt_provider = build_receipt_provider(settings)
    app.state.migration_head = expected_migration_head()

    # Middleware order: the last one added is the outermost. CORS wraps the request-ID
    # layer so even the 500 envelope it produces carries CORS headers.
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    return app


app = create_app()
