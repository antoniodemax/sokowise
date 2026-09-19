# syntax=docker/dockerfile:1.7
# Multi-stage build: dependencies are resolved with uv in the builder, the runtime image
# carries only the virtualenv and application code and runs as a non-root user.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Install dependencies first so this layer is cached until pyproject/uv.lock change.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
# The project itself is NOT installed into the venv: uv caches a built copy of the package
# by name and version, so a deploy that changes only app/*.py could keep serving the
# previous code from site-packages. The runtime imports the fresh /app/app via PYTHONPATH.
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/app /app/app
# Migrations ship with the image so `alembic upgrade head` can run as a release step.
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/alembic /app/alembic
# Migrate-then-serve entrypoint for hosts without a pre-deploy step (docs/OPERATIONS.md).
COPY --chown=app:app scripts/start.sh /app/scripts/start.sh
# Default receipt blob root for single-host/compose use. Production must point
# RECEIPT_STORAGE_DIR at a mounted volume (docs/OPERATIONS.md); the container disk is ephemeral.
RUN mkdir -p /app/var/receipts && chown -R app:app /app/var
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app PYTHONUNBUFFERED=1 API_HOST=0.0.0.0 API_PORT=8000
# Behind a platform proxy (Railway) set FORWARDED_ALLOW_IPS="*" in the service environment so
# uvicorn takes the client address from X-Forwarded-For; the per-IP rate limits and audit
# `ip` column depend on it. Left unset here because compose publishes the port directly.
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"API_PORT\"]}/health/live', timeout=2)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"$API_HOST\" --port \"$API_PORT\""]
