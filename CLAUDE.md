# CLAUDE.md — SokoWise engineering rules

SokoWise is an AI-powered business copilot for Kenyan small businesses (dukas, boutiques, salons, small restaurants, electronics shops). Read `docs/PRD.md` for what we are building, `docs/DATA_MAPPING.md` for the data model, `docs/ARCHITECTURE.md` for how it is built, and `docs/ROADMAP.md` for what to build next. These documents are the source of truth; do not invent behaviour that is not in them — record the gap instead.

## Stack
Frontend: React 19 + TypeScript + Vite + Tailwind + shadcn/ui. Backend: Python 3.12 + FastAPI + SQLAlchemy 2.x (async) + Alembic + Pydantic. Database: PostgreSQL. Auth: JWT access tokens + rotating refresh tokens, Argon2id. AI: Anthropic Claude API (Python SDK, server-side only). Infra: Docker Compose locally; Vercel (frontend), Railway (backend + Postgres), GitHub Actions, Sentry.

## Current state
Phase 0 complete (documentation). No application code exists yet. The Vite scaffold at the repo root will move to `frontend/` in Phase 1. Check `docs/ROADMAP.md` for the active phase before starting work, and do not start a later phase without being asked.

## Rules
1. Read the relevant documentation before making architectural changes.
2. Inspect existing code before modifying it.
3. Do not invent requirements. If something is unspecified, say so and document it (PRD §19 or the phase notes) rather than guessing.
4. Do not rewrite working systems unnecessarily.
5. Keep the architecture simple: routers → schemas → services → repositories → models. No extra layers without a concrete reason.
6. Prefer small, testable changes.
7. Do not mix unrelated features into one change or commit.
8. Database changes require Alembic migrations, reviewed by hand. Never edit a migration that has been applied anywhere.
9. Never hardcode secrets. Configuration comes from environment variables via `pydantic-settings`.
10. Never commit `.env` files containing secrets. `.env.example` documents variables with placeholder values only.
11. Validate all external input with Pydantic (API) and zod (frontend). Trust nothing from the client, including IDs.
12. Enforce authorization in the backend on every request. The frontend only hides; it never protects.
13. Enforce business/tenant isolation: every tenant-scoped query is parameterised by the `business_id` from the authenticated context. Repositories must not expose unscoped lookups. Cross-tenant access returns 404.
14. Do not trust AI-generated financial or inventory data. Numbers come from backend tools; the model reports them.
15. AI responses must be validated (shape, length, allowed tool calls) before being stored, shown, or acted upon. In MVP the AI has no write path.
16. Add tests for meaningful business logic: sales, inventory, credit, analytics, auth, permissions, tenant isolation.
17. Run the appropriate tests after implementation (`uv run pytest` in `backend/`, `npm test` in `frontend/`) and report the actual result.
18. Preserve backward compatibility where practical (API response shapes, migration reversibility).
19. Do not change the visual design when working on backend functionality unless explicitly requested.
20. Do not add dependencies without explaining why they are necessary in the PR/commit.
21. Avoid premature optimization. Measure first.
22. Avoid unnecessary microservices. One backend service.
23. Avoid unnecessary state-management libraries. TanStack Query for server state; React context for auth; local state otherwise.
24. Keep secrets, credentials, and API keys out of source control, logs, and the frontend bundle.
25. Never expose internal errors, stack traces, database details, or secrets to users. Use the error envelope in `docs/ARCHITECTURE.md` §8.
26. Follow secure coding practices (OWASP ASVS L1 baseline): parameterised queries only, constant-time comparisons for tokens, rate limits on auth endpoints, secure cookie flags.
27. When uncertain about a requirement, stop and document the uncertainty instead of inventing behaviour.
28. Before declaring a phase complete, verify every completion criterion in `docs/ROADMAP.md` for that phase.
29. Do not claim something works unless it has actually been tested — say what was run and what happened.
30. Maintain documentation when architectural behaviour changes (`docs/ARCHITECTURE.md`, `docs/DATA_MAPPING.md`).

## Domain rules that are easy to get wrong
- Money is `Decimal`/`NUMERIC(14,2)`; never `float`. Quantities are `NUMERIC(12,3)`.
- Sales are immutable; corrections are voids that reverse stock and credit. Ledgers (`inventory_movements`, `credit_transactions`, `audit_logs`) are append-only.
- Restocks are stock-in, not expenses. Gross profit = revenue − COGS (from `sale_items.unit_cost` snapshots); net = gross − operating expenses. Lines with unknown cost contribute 0 to COGS and must be reported as `lines_missing_cost` / `products_missing_cost`; never hide them.
- Revenue is accrual (Σ `total_amount` of COMPLETED sales, credit included). Cash collected is CASH/MPESA tenders plus credit repayments. A CREDIT tender is a receivable, never cash received. Repayments are never revenue.
- Sale-level discounts are allocated to lines at sale time (`sale_items.discount_allocated`) so product profit reconciles to period profit.
- "Today" means the business's timezone (`businesses.timezone`), not UTC.
- Sale creation is idempotent on `(business_id, idempotency_key)`; the same key with a different payload is a 409, never a silent success.
- Role comes from the verified `business_memberships` row on every request, never from a token claim. `get_business_context` also rejects inactive businesses.
- AI quotas are server-side configuration (`AI_DAILY_MESSAGE_LIMIT`, `AI_MONTHLY_MESSAGE_LIMIT`). They are never stored in `businesses.settings` and no endpoint lets an owner change them.
- The `ai` module imports `analytics` and named read-only repository functions only; never `services`.
- Payment lines live in `payments` (CASH / MPESA / CREDIT). M-Pesa API integration is future work and must slot in via `payments.provider/status` without touching sales logic.

## Working conventions
- Backend: `ruff` for lint/format, `mypy` for types, `pytest` against a real PostgreSQL (never SQLite).
- Frontend: strict TypeScript, ESLint, Vitest.
- Definition of done for an endpoint: happy path, validation failure, permission denial, and cross-tenant access tests.
- Keep files focused; a module over ~400 lines is a signal to split by responsibility, not by layer.

## Git rules
Use clear, human-written commit messages in the form `type: summary`:
- `feat: add product management`
- `fix: handle duplicate inventory entries`
- `test: cover credit transactions`
- `docs: update database architecture`
- `chore: configure Docker development environment`
- `refactor: extract sale total calculation`

Do not use meaningless messages such as "stuff", "changes", "final", "updates", "fixed things". One logical change per commit. Do not commit generated artefacts, `node_modules`, `.env`, or local databases.
