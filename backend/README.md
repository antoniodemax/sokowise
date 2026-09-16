# SokoWise backend

FastAPI service for SokoWise. Architecture, layering rules and conventions live in
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md); the phase plan is in
[`docs/ROADMAP.md`](../docs/ROADMAP.md).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Run locally

```bash
cp ../.env.example ../.env      # once; edit values as needed, never commit .env
uv sync                          # creates .venv and installs runtime + dev dependencies
uv run uvicorn app.main:app --reload --env-file ../.env
```

The API listens on http://localhost:8000. Health endpoints:

- `GET /health/live` — process is up (200)
- `GET /health/ready` — ready to serve traffic; returns 503 until the database is wired in Phase 2

## Checks

```bash
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # types
uv run pytest                # tests (no database needed in Phase 1)
```

## Layout

```
app/
├── main.py            application factory (create_app) and the `app` object uvicorn serves
├── core/              config (pydantic-settings), logging, error envelope
├── middleware/        request-ID middleware and access log
└── api/               HTTP routers (health now; versioned routers under api/v1 from Phase 3)
tests/                 pytest smoke tests
```

Settings are read from environment variables (see `../.env.example`). The app refuses to start
when a required value is missing.
