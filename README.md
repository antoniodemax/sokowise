# SokoWise

AI-powered business copilot for Kenyan small businesses — dukas, mini-shops, boutiques, salons, small restaurants, electronics shops. Record sales, stock, customer credit and expenses on a phone in seconds, then ask your business questions like "what sold most this week?" or "who owes me money?".

**Status:** the business backend is complete for MVP; the frontend foundation, the core business workflows (sell, sales, products, inventory, customers, expenses, analytics, settings), the public homepage and the read-only AI copilot (needs `ANTHROPIC_API_KEY`) are in place. See [docs/ROADMAP.md](docs/ROADMAP.md) for the phase plan.

## Documentation

| Document | Purpose |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Product requirements: vision, users, MVP scope, functional/non-functional requirements, business rules, roles, acceptance criteria, risks, AI requirements |
| [docs/DATA_MAPPING.md](docs/DATA_MAPPING.md) | Entities, fields, relationships, constraints, tenant isolation, financial integrity |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Backend/frontend/database/auth/AI architecture, error handling, config, testing, deployment, security boundaries |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Sequential phases with tasks, dependencies and completion criteria |
| [CLAUDE.md](CLAUDE.md) | Engineering rules for anyone (human or AI) working on the codebase |

## Stack

- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, shadcn-style components on Radix, React Router, TanStack Query — deployed on Vercel
- **Backend:** Python 3.12, FastAPI, Pydantic, pydantic-settings, SQLAlchemy 2.x (async, asyncpg), Alembic — deployed on Railway
- **Database:** PostgreSQL 16 (Railway)
- **Auth:** JWT access tokens + rotating refresh tokens in an HttpOnly cookie, Argon2id, roles from the membership row on every request
- **AI:** Anthropic Claude API, server-side only, read-only tool access to validated business data (Phase 9)
- **Ops:** Docker Compose (local), GitHub Actions (CI), Sentry (errors)

## Repository layout

```
backend/        FastAPI service (uv, ruff, mypy, pytest) — see backend/README.md
frontend/       Vite + React + TypeScript app (npm) — public homepage, auth, dashboard, sell, sales, products, inventory, customers, expenses, analytics, settings, copilot
docs/           product and engineering documentation (source of truth)
docker/         local development helpers (empty until needed)
scripts/        repo-level scripts (empty until needed)
.github/        CI workflow: backend checks, frontend checks, compose validation
docker-compose.yml   PostgreSQL 16 + backend for local development
.env.example         every environment variable, placeholder values only
```

## Local development

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, Docker with Compose.

```bash
cp .env.example .env            # once; never commit .env
```

**Backend** (http://localhost:8000):

```bash
cd backend
uv sync
uv run --env-file ../.env alembic upgrade head      # apply migrations (needs PostgreSQL)
uv run uvicorn app.main:app --reload --env-file ../.env
curl localhost:8000/health/live     # {"status":"ok"}
curl localhost:8000/health/ready    # {"status":"ready","checks":{"database":"ok"}}
```

Set a real `JWT_SECRET` in `.env` (≥ 32 characters, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`);
the backend refuses to start without one. The auth endpoints are listed in `backend/README.md`.

**Frontend** (http://localhost:5173):

```bash
cd frontend
npm ci
npm run dev          # proxies /api to the backend on :8000; leave VITE_API_BASE_URL empty locally
npm test             # Vitest
```

**Docker Compose** (PostgreSQL 16, plus the backend in a container):

```bash
docker compose up -d postgres       # database only (also creates sokowise_test for the test suite)
docker compose up --build           # database + backend
docker compose run --rm backend alembic upgrade head
```

Without Docker, any PostgreSQL 16 works: create a role and the `sokowise` / `sokowise_test` databases, then point `DATABASE_URL` / `TEST_DATABASE_URL` at them.

## Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && TEST_DATABASE_URL=postgresql+asyncpg://sokowise:sokowise@localhost:5432/sokowise_test uv run pytest
cd frontend && npm run lint && npm test && npm run build
docker compose config --quiet
```

The same checks run in GitHub Actions on every push and pull request.

## Contributing

Read `CLAUDE.md` before making changes. Commits follow `type: summary` (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`).
