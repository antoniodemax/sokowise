# SokoWise — Architecture

| Field | Value |
|---|---|
| Status | Draft v0.2 — Phase 0 (architecture review fixes applied) |
| Last updated | 2026-09-16 |
| Related docs | [PRD.md](PRD.md) · [DATA_MAPPING.md](DATA_MAPPING.md) · [ROADMAP.md](ROADMAP.md) |

This document describes how SokoWise is built. Nothing described here is implemented yet; it is the target for the phases in ROADMAP.md. Keep it in sync when behaviour changes (CLAUDE.md rule 30).

---

## 1. System overview

```
┌──────────────┐  HTTPS/JSON   ┌──────────────────────┐   SQL    ┌────────────┐
│  React SPA   │ ────────────▶ │  FastAPI backend     │ ───────▶ │ PostgreSQL │
│  (Vercel)    │ ◀──────────── │  (Railway)           │ ◀─────── │ (Railway)  │
└──────────────┘  SSE stream   └──────────┬───────────┘          └────────────┘
                                          │ HTTPS (Anthropic SDK)
                                          ▼
                                 ┌──────────────────┐
                                 │  Claude API      │
                                 └──────────────────┘
```

- A single backend service (a "modular monolith"). No microservices, no message queue in MVP. Background work (nightly cache drift check, AI evals) runs as scheduled commands, not workers.
- The frontend is a static SPA that talks only to the backend. It never holds third-party secrets.
- The backend is the only component that talks to PostgreSQL and to Claude.

## 2. Repository layout (target)

```
sokowise/
├── backend/                 # FastAPI application (Python 3.12+)
│   ├── app/
│   │   ├── main.py          # app factory, middleware, router registration
│   │   ├── core/            # config, security (jwt, hashing), logging, errors, deps
│   │   ├── middleware/      # request-ID / access-log middleware
│   │   ├── db/              # engine/session, base model, alembic env helpers
│   │   ├── models/          # SQLAlchemy 2.x models (one module per aggregate)
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── repositories/    # data access, always business-scoped
│   │   ├── services/        # business logic and transactions
│   │   ├── api/
│   │   │   ├── deps.py      # get_current_user, get_business_context, require_role
│   │   │   └── v1/          # routers: auth, businesses, users, products, inventory,
│   │   │                    #          sales, customers, credit, expenses, analytics, ai
│   │   ├── analytics/       # read-only query functions used by API and AI tools
│   │   ├── ai/              # client, prompts, tools registry, guardrails, service
│   │   └── integrations/    # external providers; empty in MVP (mpesa/ later)
│   ├── alembic/             # migrations
│   ├── tests/               # pytest (unit + API tests against real Postgres)
│   ├── scripts/             # management commands (seed, recompute-caches)
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                # Vite + React + TS + Tailwind + shadcn/ui
│   └── (relocated from the current root scaffold in Phase 1)
├── docker/                  # compose helper files (postgres init, etc.)
├── docs/                    # this documentation
├── scripts/                 # repo-level scripts (dev bootstrap, CI helpers)
├── .github/workflows/       # CI/CD
├── docker-compose.yml       # local dev: postgres (+ backend, frontend optional)
├── .env.example             # documented environment variables, no secrets
├── CLAUDE.md
└── README.md
```

**Current state (after Phase 1):** the Vite scaffold lives in `frontend/`. `backend/` holds the application factory, settings, JSON logging, the error envelope, the request-ID middleware and the health endpoints; `models/`, `schemas/`, `repositories/`, `services/`, `analytics/`, `ai/`, `integrations/` and `api/v1/` do not exist yet and are created by the phases that need them. Middleware lives in `app/middleware/`.

## 3. Backend architecture

### 3.1 Layers

```
HTTP request
  → api/v1/<router>.py      parse path/query, call service, return schema
  → schemas/                Pydantic validation of input and output
  → services/               business rules, transactions, authorization details, audit
  → repositories/           SQLAlchemy queries, always parameterised by business_id
  → models/                 SQLAlchemy 2.x declarative models
  → PostgreSQL
```

Rules that keep this honest:

- **Routers are thin.** No business logic, no direct DB access. They resolve dependencies (`current_user`, `business_ctx`, `session`), call one service function, and return.
- **Services own transactions.** A service method receives a `Session`, does its work, and commits explicitly (`async with session.begin()`), so multi-step financial operations are visibly atomic. The request-scoped dependency only opens and closes the session; it never commits.
- **Repositories never accept an unscoped lookup.** `ProductRepository.get(session, business_id, product_id)`; there is no `get(product_id)`.
- **Models contain no business logic** beyond column definitions, relationships and simple properties.
- **Schemas are separate from models.** Never return ORM objects directly. Response schemas exclude internal fields (`password_hash`, `token_hash`).
- **No generic "base service"/"base repository" magic** beyond a small helper for scoped `get_or_404`. Duplication of ten trivial lines is preferred over an abstraction nobody can read.

### 3.2 Module boundaries

| Module | Responsibility | May import |
|---|---|---|
| `core` | settings, JWT, hashing, logging, error types | stdlib, libs |
| `db` | engine, session factory, `Base` | core |
| `models` | tables | db |
| `repositories` | queries | models, db |
| `services` | rules, transactions, audit | repositories, schemas, core, analytics |
| `analytics` | read-only aggregate queries | repositories, models |
| `ai` | Claude client, tools, prompts, guardrails | analytics, the read-only repository functions named in `ai/tools/registry.py`, schemas, core. Never `services` |
| `api` | HTTP | services, schemas, ai, core |
| `integrations` | providers (future M-Pesa) | core, schemas |

`ai` never imports `models` or `services`. Its data access is: `analytics` functions; an explicit list of repository read functions (`search_products`, `search_customers`, `get_customer_ledger`) imported by name in the tool registry; and the `ai_conversations` / `ai_messages` repository for its own persistence. Tool executions run inside a read-only transaction (`SET TRANSACTION READ ONLY`) so an accidental write from a tool fails at the database; conversation persistence uses the ordinary request session. When AI-proposed actions arrive post-MVP they go through the HTTP API like any client, never through `services` from inside `ai`.

### 3.3 Request lifecycle

1. `RequestIDMiddleware` assigns a `request_id`, starts a timer and binds the logging context. A client-supplied `X-Request-ID` is kept when it matches `[A-Za-z0-9._-]{1,64}`; otherwise a UUID4 is generated. The ID is returned in the `X-Request-ID` response header and written into every error envelope. The middleware is pure ASGI and sits inside CORS (the last middleware added is the outermost), so an unhandled exception becomes the 500 envelope while the ID is still bound and the response still carries CORS headers.
2. `get_current_user` validates the access JWT → loads `User` (must be active).
3. `get_business_context` reads `bid` from the JWT, loads the `Business` (must be `is_active`) and the user's `BusinessMembership` for it (must exist and be `is_active`), and returns `BusinessContext(business_id, user_id, role, timezone, settings)`. `role` comes from the membership row on every request; the token carries no role claim.
   3a. If `users.must_change_password` is true, only `POST /auth/change-password` and `POST /auth/logout` are allowed; everything else returns 403 `PASSWORD_CHANGE_REQUIRED`.
4. `require_role("OWNER")` (where needed) checks the role.
5. Router → service with `BusinessContext`. Every repository call receives `ctx.business_id`.
6. Response is serialised through the response schema; errors go through the global handlers (§8).

### 3.4 Concurrency and transactions

- One DB session per request (`SessionLocal` via dependency).
- Financial operations (sale create/void, restock, repayment) use `SELECT … FOR UPDATE` on the affected `products`/`customers` rows, locked in a deterministic order (sorted UUIDs) to avoid deadlocks.
- PostgreSQL default isolation (READ COMMITTED) plus row locks is sufficient; no serialisable transactions in MVP.
- Idempotent sale creation: insert with `idempotency_key`; on unique violation, re-read and return the existing sale.

### 3.5 Tooling

- Python 3.12 (pinned in `backend/.python-version` so `uv` does not pick a newer interpreter), dependency management with `uv` (fast, lockfile, no extra runtime dependency), `ruff` for lint+format, `mypy` in strict mode with the pydantic plugin, `pytest` + FastAPI's `TestClient` (httpx).
- FastAPI with async routes; SQLAlchemy 2.x with the **async** engine (`asyncpg`). Decision rationale: the AI endpoint streams and waits on network; async avoids tying up threads. All repositories are async.
- Alembic for migrations; autogenerate is a starting point, every migration is reviewed by hand.

Dependencies expected in Phase 1 (each must be justified in the PR that adds it): `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic`, `pydantic-settings`, `argon2-cffi`, `pyjwt`, `anthropic`, `httpx`, `structlog` (or stdlib logging with JSON formatter), `sentry-sdk`, `slowapi` or an in-house rate limiter (decide in Phase 3).

## 4. Frontend architecture direction

- **Stack:** Vite, React 19, TypeScript (strict), Tailwind CSS, shadcn/ui, React Router, TanStack Query for server state, react-hook-form + zod for forms. No Redux/Zustand/MobX — server state belongs to TanStack Query, auth state in a small context, UI state in components. Add a store only when a concrete problem demands it.
- **Structure (feature-based):**
  ```
  frontend/src/
  ├── app/            # router, providers, layout shells
  ├── components/ui/  # shadcn primitives
  ├── components/     # shared composites
  ├── features/
  │   ├── auth/  ├── sell/  ├── products/  ├── inventory/  ├── customers/
  │   ├── credit/ ├── expenses/ ├── analytics/ └── copilot/
  ├── lib/            # api client, auth token handling, formatting (KSh, dates)
  └── types/          # generated from the backend OpenAPI schema
  ```
- **API client:** a thin `fetch` wrapper that attaches the access token, retries once on 401 via the refresh endpoint, and maps the error envelope to typed errors. Types generated from `/openapi.json` (e.g. `openapi-typescript`) so backend and frontend cannot drift silently.
- **Mobile-first:** bottom navigation, Sell screen as the default route, large touch targets, numeric keypad inputs (`inputmode="decimal"`), optimistic UI only where safe (never for sale creation — show pending state until the server confirms).
- **Money formatting:** integers by default (`KSh 1,250`), decimals when non-zero.
- **PWA:** manifest + install prompt in Phase 12; offline queue is post-MVP.
- **Design:** keep the visual design decisions in the frontend phase; backend work never changes UI (CLAUDE.md rule 19).

## 5. Authentication and authorization

### 5.1 Tokens
- **Access token:** JWT (HS256 with a strong secret in MVP; RS256 if a second service ever needs to verify tokens). Claims: `sub` (user id), `bid` (active business id), `iat`, `exp` (15 min), `jti`. Signed with `JWT_SECRET`. The role is deliberately absent: it is read from the membership on every request (§3.3), so a demotion or deactivation takes effect immediately instead of at token expiry.
- **Refresh token:** 256-bit random opaque string; only its SHA-256 hash is stored (`refresh_tokens`). Lifetime 30 days, rotated on every use, family-revoked on reuse.
- **Transport:** access token in memory on the client (never localStorage) and sent as `Authorization: Bearer`. Refresh token in an `HttpOnly; Secure; SameSite=Lax` cookie scoped to the API origin, which requires the app and API to share a registrable domain in production (e.g. `app.sokowise.example` and `api.sokowise.example`). If separate domains are unavoidable, fall back to `SameSite=None` plus a CSRF double-submit header. Local dev uses the Vite proxy so cookies are same-origin.
- **Deferred decisions (Phase 3):** (1) Vercel preview deployments live on `*.vercel.app`, which is cross-site to the API, so `SameSite=Lax` refresh cookies will not be sent from previews. Phase 3 must choose between a `SameSite=None` + CSRF-header mode enabled only for allow-listed preview origins, a preview API environment on the same site, or accepting that previews use a non-persistent login. (2) Shared shop devices (PRD assumption A8): whether to add an idle timeout, a shorter refresh lifetime, or a "shared device" login mode. Neither decision is made here; until made, the defaults above apply.
- **CSRF:** refresh and logout endpoints require a custom header (`X-Requested-With: sokowise`) in addition to the cookie.

### 5.2 Passwords
- Argon2id via `argon2-cffi`. Start at the OWASP minimum (m=19 MiB, t=2, p=1) and raise `t` (then `m`) only after measuring on the deployed Railway instance, aiming for roughly 100–250 ms per hash without exhausting memory under concurrent logins (the container may have 512 MB and 1–2 vCPUs; ten concurrent 64 MiB hashes would not fit). Record the chosen parameters in Phase 3. Rehash on login when parameters change.
- Minimum 8 characters; check against a small deny-list of common passwords; no composition rules.
- Login and register endpoints are rate-limited per IP and per identifier. **Limitation:** the MVP limiter keeps counters in process memory, and the backend runs 2–4 uvicorn workers, so the effective limit is up to N× the configured value and resets on deploy. This is accepted for the pilot; a shared store (database table or Redis) is the upgrade path if abuse appears. The Argon2 cost is the second line of defence.

### 5.3 Authorization
- Role checks are FastAPI dependencies (`require_role`), applied per route.
- Object-level checks are implicit: everything is loaded through business-scoped repositories, so a resource from another business is simply not found (404).
- The permission matrix in PRD §16 is the specification; each row becomes at least one test.

### 5.4 Multi-tenancy
- Active business comes from the token (`bid`), not from the request body or query string. Switching business (future) means issuing a new token.
- Membership is re-verified on every request so revocation is immediate.
- Phase 11 evaluates Postgres row-level security (`SET LOCAL app.business_id`) as a second layer; it is not relied upon in MVP.

## 6. AI architecture

### 6.1 Flow

```
User question
  → POST /api/v1/ai/conversations/{id}/messages          (auth, role=OWNER, quota check)
  → AIService.ask(ctx, conversation, text)
      1. load recent messages (bounded window)
      2. build request: cached stable prefix (system prompt + tool definitions)
                         + volatile context (business name, tz, today's date, language hint)
                         + conversation history + new user message
      3. persist the user message; open the SSE response
      4. call Claude (Python SDK, streaming, adaptive thinking, max_tokens bounded)
      5. stream: forward text deltas to the client as they arrive and accumulate
         the full response server-side
      6. on stop_reason == "tool_use" (max 6 rounds per turn):
           - look up tool in ToolRegistry (allowlist)
           - validate input with the tool's Pydantic schema
           - execute tool(ctx, **input)  ← ctx supplies business_id; model cannot override it
           - bound the output rows, return as tool_result, go to 4
      7. on end_turn / max_tokens / refusal: run guardrails over the accumulated
         response (§6.4)
      8. persist the assistant message with tool-call records, usage, stop reason
         and guardrail outcome; if a guardrail failed, the stored message is
         flagged and the client receives a terminal SSE event carrying a notice
      9. close the stream
  → Client renders

The user has already seen streamed text by the time guardrails run, so guardrails
can flag, annotate or refuse to store a *clean* copy; they cannot un-show text.
Anything that must never reach the user is prevented before the call (tool
allowlist, PII minimisation, prompt rules), not filtered after it.
```

### 6.2 Tools (MVP, all read-only)

| Tool | Backed by | Notes |
|---|---|---|
| `get_period_summary(period | date_from, date_to)` | analytics | the PRD FR-I1 fields: `revenue` (accrual), `cash_collected` by method, `tender_split`, `cogs`, `lines_missing_cost`, `products_missing_cost`, gross/net profit, counts |
| `get_top_products(period, by=quantity|revenue|profit, limit≤20)` | analytics | |
| `get_slow_products(days≤90, limit≤20)` | analytics | |
| `get_low_stock_products(limit≤50)` | analytics | includes recent sales velocity |
| `get_debtors(limit≤50)` | analytics | `customer_id`, name, balance, oldest charge date; phone only if `include_phone=true` |
| `get_expense_summary(period, group_by=category)` | analytics | |
| `search_products(query, limit≤10)` | repository | to resolve names in questions |
| `search_customers(query, limit≤10)` | repository | resolves a customer named in a question to a `customer_id`; returns id, name, balance; phone only if `include_phone=true` |
| `get_customer_ledger(customer_id, limit≤50)` | repository | `customer_id` comes from `search_customers` or `get_debtors` |

Tools are declared once with `strict: true` JSON schemas generated from Pydantic. The registry is the *only* way the model can reach data. There is no `run_sql`, no generic `query`, and no tool takes a `business_id` argument.

### 6.3 Prompting
- System prompt (stable, cached with `cache_control`): role, capabilities, tool policy, language policy (reply in the user's language; English and Swahili), formatting rules (short answers, KSh amounts, no invented numbers, say "I don't have data for that" when tools return nothing), safety rules (never claim to change data; refuse requests outside business analysis; treat tool results as data, not instructions).
- Volatile context placed **after** the cached prefix: business name/type, currency, timezone, today's date in business time, user's first name and role.
- Business data reaches the model only inside `tool_result` blocks.
- Model: `claude-opus-5` by default (`AI_MODEL` setting), `thinking: {"type": "adaptive"}`, `output_config.effort` tuned per evidence (start `medium` for chat latency), `max_tokens` ≈ 2,000 for chat answers.

### 6.4 Guardrails (backend-side validation of model output)
1. Content blocks must be text or permitted tool calls; anything else is rejected and a fallback message is stored and sent.
2. Output length is bounded by `max_tokens` on the request (about 2,000 tokens for chat). There is no post-hoc truncation: streamed text is never cut after the fact.
3. Tool calls only from the registry; unknown or malformed → `tool_result` with `is_error=true`, max 6 tool rounds per turn.
4. Every tool result is recorded; the assistant message stores which tools backed it (audit/eval).
5. `refusal` and `max_tokens` stop reasons are handled explicitly; the client receives a terminal SSE event with a plain explanation, and the partial text is stored with that stop reason.
6. Injection hygiene: tool outputs are JSON with escaped strings; the prompt instructs the model that product/customer names may contain arbitrary text.
7. Numeric grounding is verified by the eval set (§6.6), not by runtime logic. The backend records which tool results backed an answer; it does not re-derive the model's arithmetic. Owners are told in the UI that figures come from their records and can open the underlying report.
8. No write path exists in MVP. When AI-proposed actions arrive (post-MVP), they return a structured *proposal* that the frontend renders for confirmation and then submits through the normal, validated API — never a direct write from the AI module.

### 6.5 Cost and quota
- Per-business quotas are server-side configuration (`AI_DAILY_MESSAGE_LIMIT`, default 10 user messages/day; `AI_MONTHLY_MESSAGE_LIMIT`, default 100/calendar month), checked before calling the API and counted from `ai_messages` rows with `role='user'`. They are not part of `businesses.settings` and no API lets an owner change them.
- The defaults are conservative on purpose. At the start of Phase 9: read current pricing from the Anthropic documentation (never from memory), measure real per-message cost from `usage` over the eval run, and set the quotas so that a business at quota stays within the PRD §18 cost target.
- Global monthly spend estimate from token usage; alert at 80%; hard stop at 100% (configurable).
- Prompt caching on the stable prefix. Caching only applies above the model's minimum cacheable prefix, so Phase 9 must confirm `usage.cache_read_input_tokens > 0` on the second and later requests; if it is 0, the prefix is either too short or something volatile sits inside it. Conversation window bounded (last N messages / token estimate).

### 6.6 Evaluation
- A fixture business with known answers; question→expected pairs for English and Swahili; injection and refusal cases.
- CI runs tool-level tests with recorded outputs (no model call). A nightly job runs the live eval and reports numeric accuracy.

### 6.7 Receipt intelligence (Phase 10)
- Input: pasted M-Pesa confirmation text or a photo of a supplier receipt (image content block).
- Output: structured draft (`output_config.format` with a Pydantic schema): kind (expense | restock | repayment), amount, date, reference, counterparty, line items with confidence.
- The draft is shown to the user for confirmation and then submitted via the normal expense/restock/repayment endpoints. The extraction never writes to the database.

## 7. External integrations (future: M-Pesa)

Designed now, built later:

- `integrations/mpesa/` will contain a Daraja client (OAuth token, STK push, C2B register/confirm) and a webhook router.
- `payments.provider = 'MPESA_DARAJA'`, `payments.status` transitions `PENDING → CONFIRMED | FAILED`, `sales.status` gains `PENDING`.
- New table `mpesa_transactions` (checkout_request_id, merchant_request_id, receipt_number, phone, amount, status, raw callback JSONB) linked from `payments` / `credit_transactions`.
- Webhook endpoints verify source (IP allowlist + shared secret) and are idempotent on `checkout_request_id`.
- Because payment lines are already a separate table with `status` and `provider`, no change to `sales`, `sale_items`, inventory or credit logic is needed.

## 8. Error handling

- One error envelope for all non-2xx responses:
  ```json
  { "error": { "code": "PRODUCT_NOT_FOUND", "message": "Product not found", "details": null, "request_id": "…" } }
  ```
- Domain exceptions (`NotFoundError`, `ValidationError`, `PermissionDeniedError`, `ConflictError`, `InsufficientStockError`, `CreditLimitExceededError`, `AIUnavailableError`) subclass `app.core.errors.AppError` (which carries `status_code`, `code`, a user-safe `message` and optional `details`) and are mapped to HTTP by the handlers in that module. Framework-level failures use fixed codes: `VALIDATION_ERROR` (422, with `details` = list of `{loc, msg, type}`), `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `UNAUTHORIZED`, `FORBIDDEN`, `CONFLICT`, `RATE_LIMITED`, `SERVICE_UNAVAILABLE`, `HTTP_ERROR` (other statuses) and `INTERNAL_ERROR` (500).
- Pydantic validation errors are reformatted into the envelope with field-level `details`.
- Unhandled exceptions → 500 with a generic message and `request_id`; full details go to logs and Sentry. Stack traces, SQL, and internal identifiers never reach the client (CLAUDE.md rule 25).
- Cross-tenant access → 404, never 403.

## 9. Logging and observability

- Structured JSON logs (`request_id`, `user_id`, `business_id`, route, status, duration_ms). No PII values (phone numbers, names) in log messages; identifiers only.
- Log levels: INFO for requests, WARNING for domain rejections that matter (credit limit, stock), ERROR for unexpected failures.
- Sentry: backend and frontend, with `request_id` as a tag; PII scrubbing enabled.
- AI calls log model, tokens, cache hits, latency, tool names (not tool outputs).
- Health endpoints: `/health/live` (process up → `{"status":"ok"}`) and `/health/ready` (`{"status":"ready"|"not_ready","checks":{...}}`; 503 with `checks.database = "not_configured"` until Phase 2 adds the real check).
- Log records are one JSON object per line with `timestamp`, `level`, `logger`, `message`, `request_id` when bound, and any `extra` fields. The access line (`logger = app.access`) carries `method`, `path`, `status`, `duration_ms`; uvicorn's own access log is disabled to avoid duplicates.

## 10. Configuration and environment variables

Configuration comes from environment variables loaded by `pydantic-settings`; the app refuses to start if required values are missing. `.env` files are local-only and git-ignored; `.env.example` documents every variable without secrets.

| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | yes | `development` / `test` / `production`; production disables `/docs` and `/openapi.json` |
| `APP_NAME` | no (`SokoWise API`) | OpenAPI title |
| `API_HOST`, `API_PORT` | no (`0.0.0.0`, `8000`) | bind address for the container `CMD`; Railway's `PORT` mapping is decided in Phase 15 |
| `DATABASE_URL` | yes | `postgresql+asyncpg://…` |
| `JWT_SECRET` | yes | ≥ 32 random bytes |
| `ACCESS_TOKEN_TTL_MINUTES` | no (15) | |
| `REFRESH_TOKEN_TTL_DAYS` | no (30) | |
| `CORS_ORIGINS` | yes | comma-separated frontend origins |
| `COOKIE_DOMAIN`, `COOKIE_SECURE` | prod | refresh cookie settings |
| `ANTHROPIC_API_KEY` | yes (AI) | server-side only |
| `AI_MODEL` | no (`claude-opus-5`) | |
| `AI_DAILY_MESSAGE_LIMIT` | no (10) | per-business user messages per day; operator-controlled |
| `AI_MONTHLY_MESSAGE_LIMIT` | no (100) | per-business user messages per calendar month; operator-controlled |
| `AI_MONTHLY_BUDGET_USD` | no | global hard cap |
| `SENTRY_DSN` | prod | |
| `LOG_LEVEL` | no (INFO) | |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | no (5) | |
| Frontend: `VITE_API_BASE_URL` | yes | |
| Frontend: `VITE_SENTRY_DSN` | prod | |

## 11. Database architecture

- PostgreSQL 16+. One database, one schema (`public`) in MVP.
- Conventions and constraints per DATA_MAPPING §2 and §6.
- Migrations: Alembic, one migration per logical change, reviewed, reversible where practical. CI runs `alembic upgrade head` on a fresh database and `alembic check` for drift.
- Indexes: every FK, `(business_id, <time column>)` on transactional tables, partial unique indexes for soft-deleted uniqueness.
- Backups: Railway daily snapshots plus a weekly `pg_dump` to object storage (Phase 15); restore tested before pilot.
- Seed/fixtures: a `seed` script creates a demo business used by tests, evals and demos.

## 12. Testing strategy

| Level | Tooling | Scope |
|---|---|---|
| Unit | pytest | pure functions: money rounding, period calculations in business tz, token utilities, guardrails |
| Service/API | pytest + httpx against a **real PostgreSQL** (Docker) with transaction rollback per test | every endpoint; financial flows; role matrix; **tenant isolation for every resource** |
| Migration | CI job | upgrade from empty, downgrade one step, autogenerate shows no drift |
| AI | pytest with recorded tool outputs; nightly live eval | tool schemas, registry allowlist, guardrails, fixture Q&A accuracy |
| Frontend | Vitest + React Testing Library | forms, money formatting, API client; Playwright for the core journeys (Phase 14) |
| Security | CI | dependency audit (`pip-audit`, `npm audit`), secret scanning, ruff security rules |

SQLite is not used for tests: NUMERIC semantics, partial indexes and `FOR UPDATE` differ.

Definition of done for a feature: tests for happy path, validation failure, permission denial, and cross-tenant access.

## 13. Deployment architecture

- **Frontend:** Vercel, static build, preview deployments per PR, production from `main`.
- **Backend:** Railway service from `backend/Dockerfile` (multi-stage, non-root user, `uvicorn` with 2–4 workers; see §5.2 for what multiple workers mean for the in-memory rate limiter). Migrations run as a release step (`alembic upgrade head`) before the new version receives traffic.
- **Database:** Railway PostgreSQL with private networking; connection via `DATABASE_URL` secret.
- **CI (GitHub Actions):** on PR — backend lint/type/test with a Postgres service container, frontend lint/type/test/build, migration check. On `main` — deploy backend to Railway, frontend to Vercel (Vercel's Git integration), and run a smoke test against `/health/ready`.
- **Secrets:** stored in Railway/Vercel/GitHub secrets only.
- **Environments:** `development` (docker-compose), `staging` (optional Railway environment, recommended before pilot), `production`.
- **Local development:** `docker-compose.yml` runs Postgres (and optionally the backend); the frontend runs with `npm run dev` and proxies `/api` to the backend.

## 14. Security boundaries

```
Internet ──▶ Vercel (static) ──▶ Browser
Browser  ──▶ api.<domain> (HTTPS only, CORS-restricted, rate-limited)
Backend  ──▶ Postgres (private network, least-privilege DB user; migrations use a separate role in production if Railway supports it)
Backend  ──▶ Claude API (outbound only; key in server env)
Claude   ──▶ nothing. It receives only tool results the backend chose to send.
```

Boundary rules:
1. All authorization decisions are made in the backend; the frontend is untrusted.
2. All tenant scoping is applied in repositories/analytics; the AI module cannot bypass it because it only calls those functions with the request's `BusinessContext`.
3. The model cannot name a business, user, or table; tool inputs are validated against strict schemas and `business_id` is never a parameter.
4. Secrets never appear in the repo, logs, error responses, or the frontend bundle.
5. Uploaded content (Phase 10) is size- and type-checked, stored outside the web root (object storage), and scanned for basic sanity before being sent to the model.
6. Dependencies are pinned via lockfiles and audited in CI.
