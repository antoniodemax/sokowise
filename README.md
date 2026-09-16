# SokoWise

AI-powered business copilot for Kenyan small businesses — dukas, mini-shops, boutiques, salons, small restaurants, electronics shops. Record sales, stock, customer credit and expenses on a phone in seconds, then ask your business questions like "what sold most this week?" or "who owes me money?".

**Status:** Phase 1 (backend foundation) implemented. See [docs/ROADMAP.md](docs/ROADMAP.md) for the phase plan.

## Documentation

| Document | Purpose |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Product requirements: vision, users, MVP scope, functional/non-functional requirements, business rules, roles, acceptance criteria, risks, AI requirements |
| [docs/DATA_MAPPING.md](docs/DATA_MAPPING.md) | Entities, fields, relationships, constraints, tenant isolation, financial integrity |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Backend/frontend/database/auth/AI architecture, error handling, config, testing, deployment, security boundaries |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Sequential phases with tasks, dependencies and completion criteria |
| [CLAUDE.md](CLAUDE.md) | Engineering rules for anyone (human or AI) working on the codebase |

## Stack

- **Frontend:** React 19, TypeScript, Vite (Tailwind CSS and shadcn/ui are added in Phase 12) — deployed on Vercel
- **Backend:** Python 3.12, FastAPI, Pydantic, pydantic-settings; SQLAlchemy 2.x and Alembic arrive in Phase 2 — deployed on Railway
- **Database:** PostgreSQL 16 (Railway)
- **Auth:** JWT access tokens + rotating refresh tokens, Argon2id (Phase 3)
- **AI:** Anthropic Claude API, server-side only, read-only tool access to validated business data (Phase 9)
- **Ops:** Docker Compose (local), GitHub Actions (CI), Sentry (errors)

## Repository layout

```
backend/        FastAPI service (uv, ruff, mypy, pytest) — see backend/README.md
frontend/       Vite + React + TypeScript app (npm)
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
uv run uvicorn app.main:app --reload --env-file ../.env
curl localhost:8000/health/live     # {"status":"ok"}
curl localhost:8000/health/ready    # 503 until the database is wired in Phase 2
```

**Frontend** (http://localhost:5173):

```bash
cd frontend
npm ci
npm run dev
```

**Docker Compose** (PostgreSQL 16, plus the backend in a container):

```bash
docker compose up -d postgres       # database only
docker compose up --build           # database + backend
```

## Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd frontend && npm run lint && npm run build
docker compose config --quiet
```

The same checks run in GitHub Actions on every push and pull request.

## Contributing

Read `CLAUDE.md` before making changes. Commits follow `type: summary` (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`).
