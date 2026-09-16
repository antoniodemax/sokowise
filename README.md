# SokoWise

AI-powered business copilot for Kenyan small businesses — dukas, mini-shops, boutiques, salons, small restaurants, electronics shops. Record sales, stock, customer credit and expenses on a phone in seconds, then ask your business questions like "what sold most this week?" or "who owes me money?".

**Status:** Phase 0 (product discovery and architecture) complete. No application code yet. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Documentation

| Document | Purpose |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Product requirements: vision, users, MVP scope, functional/non-functional requirements, business rules, roles, acceptance criteria, risks, AI requirements |
| [docs/DATA_MAPPING.md](docs/DATA_MAPPING.md) | Entities, fields, relationships, constraints, tenant isolation, financial integrity |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Backend/frontend/database/auth/AI architecture, error handling, config, testing, deployment, security boundaries |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Sequential phases with tasks, dependencies and completion criteria |
| [CLAUDE.md](CLAUDE.md) | Engineering rules for anyone (human or AI) working on the codebase |

## Planned stack

- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, shadcn/ui — deployed on Vercel
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic, Pydantic — deployed on Railway
- **Database:** PostgreSQL (Railway)
- **Auth:** JWT access tokens + rotating refresh tokens, Argon2id password hashing
- **AI:** Anthropic Claude API, server-side only, read-only tool access to validated business data
- **Ops:** Docker Compose (local), GitHub Actions (CI/CD), Sentry (errors)

## Repository layout

```
docs/          product and engineering documentation (source of truth)
backend/       FastAPI service (Phase 1+)
frontend/      React app (Phase 1 moves the current root Vite scaffold here)
docker/        local development helpers
scripts/       repo-level scripts
.github/       CI workflows
```

The Vite/React scaffold currently at the repository root (`src/`, `index.html`, `package.json`) is the initial frontend and will be relocated to `frontend/` in Phase 1.

## Local development

Nothing to run yet beyond the scaffold:

```bash
npm install
npm run dev
```

Phase 1 adds `docker compose up` (PostgreSQL) and the backend. Environment variables are documented in `.env.example`; copy it to `.env` locally and never commit `.env`.

## Contributing

Read `CLAUDE.md` before making changes. Commits follow `type: summary` (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`).
