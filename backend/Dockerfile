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
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/app /app/app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 API_HOST=0.0.0.0 API_PORT=8000
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"API_PORT\"]}/health/live', timeout=2)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"$API_HOST\" --port \"$API_PORT\""]
