# SokoWise — Architecture

| Field | Value |
|---|---|
| Status | Draft v0.11 — frontend foundation implemented (§4) |
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

**Current state (after the frontend foundation):** `frontend/` holds the React app foundation described in §4 — providers, router with lazy routes, the authenticated shell, auth screens, the dashboard foundation and the UI primitives — plus the dev proxy for `/api` (§5.1). `backend/` holds the application factory, settings, JSON logging, the error envelope, the request-ID middleware, the health endpoints, `app/db/` (base, engine, session dependency, `transaction()` helper), `app/models/` (the 16 MVP tables), `alembic/` (one migration, `b7a497cc6a27`), and the authentication slice: `app/core/passwords.py`, `app/core/tokens.py`, `app/core/ratelimit.py`, `app/core/context.py` (`BusinessContext`, `ClientInfo`), `app/schemas/auth.py` + `identifiers.py`, `app/repositories/{users,businesses,refresh_tokens}.py`, `app/services/auth.py`, `app/api/deps.py` and `app/api/v1/auth.py` (mounted at `/api/v1/auth`); and the Phase 4 tenant core: `app/schemas/{business,members}.py`, `app/repositories/audit_logs.py` (+ business-scoped member queries in `users.py`), `app/services/{audit,business,members}.py`, `app/api/v1/{business,users}.py`; and the Phase 5 catalogue: `app/schemas/catalog.py`, `app/repositories/{categories,products,inventory}.py`, `app/services/{categories,products,inventory}.py`, `app/api/v1/{categories,products}.py`; customers: `app/schemas/customers.py`, `app/repositories/customers.py`, `app/services/customers.py`, `app/api/v1/customers.py`; the credit ledger: `app/schemas/credit.py`, `app/repositories/credit.py`, `app/services/credit.py`, ledger routes in `api/v1/customers.py` and `api/v1/debtors.py`; migration `e73124c3e89a` (idempotency columns on `credit_transactions`); sales: `app/services/money.py`, `app/schemas/sales.py`, `app/repositories/sales.py`, `app/services/sales.py`, `app/api/v1/sales.py`; inventory operations: `app/schemas/inventory.py`, the operations in `app/services/inventory.py`, `app/api/v1/inventory.py`, `scripts/recompute_caches.py`; analytics: `app/analytics/{periods,queries}.py`, `app/schemas/analytics.py`, `app/api/v1/analytics.py`; expenses: `app/schemas/expenses.py`, `app/repositories/expenses.py`, `app/services/expenses.py`, `app/api/v1/expenses.py`. `ai/` and `integrations/` do not exist yet. Middleware lives in `app/middleware/`.

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
- **Services own transactions.** A service method receives a `Session`, does its work, and commits explicitly (`async with transaction(session)` from `app.db.session`), so multi-step financial operations are visibly atomic. The helper commits on success and rolls back on any exception; it joins the transaction that a request dependency's read (`get_current_user`) already autobegan, so there is exactly one transaction per request. The request-scoped dependency only opens and closes the session; it never commits. Bulk `UPDATE`s run with `synchronize_session=False` (the async-safe option); code must not read an ORM object it has just bulk-updated in the same session.
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
2. `get_access_claims` verifies the bearer JWT (signature, `exp`, `typ`, required claims, `iss`/`aud` when configured) → `get_current_user` loads the `User` (must exist and be active). Failures are a generic 401 `UNAUTHORIZED` with `WWW-Authenticate: Bearer`.
3. `get_business_context` reads `bid` from the JWT, loads the user's `BusinessMembership` for it (no membership, or no such business → 404 `NOT_FOUND`: a cross-tenant selector must not confirm that the other business exists; membership not `is_active` → 403 `MEMBERSHIP_INACTIVE`), loads the `Business` (not `is_active` → 403 `BUSINESS_INACTIVE`), and returns `BusinessContext(user_id, business_id, membership_id, role, timezone, settings)` (`app.core.context`). `role` comes from the membership row on every request; the token carries no role claim and `bid` is only a selector. A deactivation or demotion therefore takes effect on the next request, not at token expiry.
   3a. If `users.must_change_password` is true, `get_business_context` returns 403 `PASSWORD_CHANGE_REQUIRED`, which gates every business endpoint including `GET /auth/me`. The endpoints that need only `get_current_user` — `POST /auth/change-password`, `POST /auth/logout-all` — and the cookie-authenticated `POST /auth/refresh` and `POST /auth/logout` keep working, so the user can stay on the change-password screen and finish. Login and refresh responses carry `user.must_change_password` so the client knows to route there.
4. `require_role(MembershipRole.OWNER)` (where needed) checks the role; `require_owner` and `require_member` (OWNER or STAFF) are the two ready-made guards. OWNER satisfies every member check; STAFF never satisfies an owner check.
5. Router → service with `BusinessContext`. Every repository call receives `ctx.business_id`.
6. Response is serialised through the response schema; errors go through the global handlers (§8).

### 3.4 Concurrency and transactions

- One DB session per request: `app.db.session.get_session` yields an `AsyncSession` from the `async_sessionmaker` stored on `app.state` (engine created in the lifespan, disposed at shutdown). The factory uses `expire_on_commit=False` and `autoflush=False`; relationships are declared `lazy="raise"` so an accidental lazy load fails loudly instead of triggering hidden IO (`MissingGreenlet`). Load related rows explicitly (`selectinload`/`joinedload`) when a query needs them.
- Financial operations (sale create/void, restock, repayment) use `SELECT … FOR UPDATE` on the affected `products`/`customers` rows, locked in a deterministic order (sorted UUIDs) to avoid deadlocks.
- PostgreSQL default isolation (READ COMMITTED) plus row locks is sufficient; no serialisable transactions in MVP.
- Idempotent sale creation: insert with `idempotency_key`; on unique violation, re-read and return the existing sale.

- Engine settings (`app/db/session.py`): `pool_size`/`max_overflow` from `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` (5 + 5 per process), `pool_pre_ping`, `pool_recycle` 30 min, a 5 s connect timeout and a server-side `statement_timeout` (`DB_STATEMENT_TIMEOUT_MS`, 30 s) so a statement stuck on a lock is cancelled instead of pinning a pooled connection. `hide_parameters` is on in production.
- Cached columns and their repair: `products.stock_quantity` (Σ movements) and `customers.balance` (Σ credit ledger) are caches written only inside the ledger transaction (`apply_movement`, `post_entry`). `services.inventory.recompute_stock` and `services.credit.recompute_balances` compare each cache with its ledger under the row lock and, with `apply`, rewrite it and audit the repair (`inventory.recompute`, `credit.recompute`); exposed as OWNER-only `POST /inventory/recompute` and `POST /customers/recompute` and run for every business by `scripts/recompute_caches.py`.

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
  │   ├── auth/  ├── dashboard/  ├── sales/  ├── products/  ├── inventory/
  │   ├── customers/  ├── expenses/  ├── analytics/  ├── settings/  └── copilot/ (future)
  ├── lib/            # api client, session, formatting (KSh, dates), decimal cents, idempotency, query keys
  ├── test/           # render helpers, fetch mock, fixtures
  └── types/          # hand-written per feature today; OpenAPI generation is still a TODO
  ```
- **API client:** a thin `fetch` wrapper that attaches the access token, retries once on 401 via the refresh endpoint, and maps the error envelope to typed errors. Types generated from `/openapi.json` (e.g. `openapi-typescript`) so backend and frontend cannot drift silently.
- **Mobile-first:** bottom navigation, Sell screen as the default route, large touch targets, numeric keypad inputs (`inputmode="decimal"`), optimistic UI only where safe (never for sale creation — show pending state until the server confirms).
- **Money formatting:** integers by default (`KSh 1,250`), decimals when non-zero.
- **PWA:** manifest + install prompt in Phase 12; offline queue is post-MVP.
- **Design:** keep the visual design decisions in the frontend phase; backend work never changes UI (CLAUDE.md rule 19).
- **Foundation as built (frontend phase 1):** Tailwind CSS v4 (`@theme` tokens in `src/index.css`), shadcn-style primitives written into `components/ui/` on Radix (`radix-ui`) for dialog, sheet and dropdown, native `<select>`/checkbox for reliability on low-end Android, `lucide-react` icons, `sonner` toasts, React Router (`react-router`), TanStack Query, react-hook-form + zod, Vitest + Testing Library. The type system is **Inter** (variable, optical-size axis) self-hosted from `@fontsource-variable/inter` — no third-party request, `font-display: swap`, per-script subsets so a Latin page downloads ~72 kB — with the system UI stack as fallback; headings get tight tracking and balanced wrapping, running text `text-pretty`, and money uses tabular numerals (`.tabular`).
- **Brand:** the palette is taken from the official logo — primary green `#0b6e4f`, navy `#0f172a` (foreground/secondary), slate `#64748b` (muted text), gold `#f2a93b` kept for accents and warnings — with semantic tokens (`primary`, `secondary`, `background`, `card`, `muted`, `border`, `success`, `warning`, `destructive`, `info`). Assets in `frontend/public/brand/` are crops of the supplied brand file (`sokowise-lockup.png` on its own white background for auth screens; `sokowise-mark.png`, the rounded green square with only the outside corners made transparent, for the app header, favicon and touch icon). No variant was redrawn; a no-tagline wordmark, an SVG master and a dark-background version should come from the brand owner.
- **Session and transport:** the access token lives in memory (`lib/session.ts`); the refresh token is the HttpOnly cookie. Every request goes through `lib/api.ts` with `credentials: "include"`; the cookie endpoints (`/auth/refresh`, `/auth/logout`) get `X-Requested-With: sokowise`. On a 401 for an authenticated request the client refreshes **once through a single in-flight promise shared by all concurrent callers** and retries each request once; a refused refresh clears the session (the backend treats a second refresh of the same token as reuse, §5.1). On page load the app calls refresh first (`restoring` state) so a valid cookie restores the session without a login. `PASSWORD_CHANGE_REQUIRED` is handled by the route guards: a session with `must_change_password` can reach only `/change-password`, which then issues a fresh session.
- **Public site (frontend phase 2.5):** `/` is a public homepage (`features/marketing/`) rendered without a session and without any API call of its own — the header shows "Go to dashboard" when a session exists and sign in / get started otherwise. The authenticated app moved from `/` to `/dashboard`; every post-login redirect (`RedirectIfAuthenticated`, login `from`, register, password change, nav, 404) points there, and the guards are unchanged. The page uses the same tokens and primitives as the app (no separate design), the supplied brand assets only (`public/brand/`, plus `sokowise-og.png`, the 1200×630 brand file, for Open Graph), and real product screenshots in `public/marketing/` (WebP, 36–48 kB each) taken from the app with an explicitly named "Example Duka" business — the captions say so, and no demo data exists in the authenticated app. The AI copilot is shown as "Coming soon". SEO: static title/description/Open Graph/Twitter tags in `index.html`; `useDocumentMeta` sets the page title and, when `VITE_PUBLIC_URL` is configured, the canonical and absolute `og:url`/`og:image` (left unset until the domain is final). Known trade-off: the `AuthProvider`'s one-time session restore (`POST /auth/refresh`, a 401 for visitors without a cookie) still runs on the homepage; it is how the header knows whether to offer the dashboard, and it is the only request an anonymous visit makes.
- **Shell and navigation:** desktop sidebar (mark, business name, role, nav, account menu with sign out / sign out everywhere), mobile header with a drawer (Radix sheet), sections Dashboard · Sales · Products · Inventory · Customers · Expenses · Analytics · Settings; Expenses and Analytics are hidden from STAFF and guarded client-side (`RequireOwner`) purely for UX — the backend still enforces §16. Routes are lazy-loaded; the main bundle is ~132 kB gzipped (NFR-2 budget 300 kB).
- **Core workflows as built (frontend phase 2):** every section talks to the real API through per-feature `api.ts` modules (typed request/response shapes mirroring §5) and TanStack Query hooks keyed from `lib/query-keys.ts`, so a mutation invalidates exactly the lists it changes (a sale invalidates sales, products, inventory, customers and analytics). Forms are react-hook-form + zod with the backend's 409 codes mapped onto the offending field (`PRODUCT_NAME_EXISTS`, `SKU_EXISTS`, `CUSTOMER_PHONE_EXISTS`, …) and 422 details mapped through `lib/errors.ts`. **Sell** (`features/sales/SellPage.tsx`) keeps the cart in component state and does its arithmetic in integer cents (`lib/decimal.ts`, half-up like BR-9) only to drive the form — subtotal, discount, per-tender amounts and the "still to pay" figure; the backend re-validates everything. A single untouched tender auto-fills with the total; split tenders are added per method; a CREDIT tender requires a customer and shows the projected balance against the limit; an M-Pesa code is typed in and labelled as unverified. `Idempotency-Key` handling lives in `lib/idempotency.ts`: the key is derived per *payload* (same payload → same key on a retry, so the backend replays; any change to what is being submitted → a new key, so the backend never sees a reused key with a different body), renewed after success, and the submit button is disabled while the request is in flight. `CREDIT_LIMIT_EXCEEDED` with `owner_may_override` opens a confirmation for the OWNER and resubmits with `credit_limit_override: true`; STAFF get a message to ask the owner. The same key-per-payload rule is used for repayments and adjustments. Sales history honours the backend's STAFF scope (own sales, today) without pretending to filter; void is OWNER-only with a mandatory reason. **Analytics** renders the §5.11 endpoints with their real names (revenue is accrual, cash collected is tenders plus repayments, credit is "owed to you, not cash received"), never hides `lines_missing_cost` / `products_missing_cost`, and draws the time series as an inline SVG bar chart with a visually hidden data table for screen readers — no charting dependency. **Expenses** downloads the CSV with the bearer header (`fetch` → blob → `<a download>`), since the export endpoint is authenticated. **Settings** edits the business profile and `settings` (PATCH `/business`, then `sessionStore.updateBusiness` so the shell reflects the new name/timezone without a new login) and manages members (`/users`). Role UX only hides: the backend remains the authority, and a 403 from an endpoint the UI could not predict (e.g. STAFF restocking when `staff_can_restock` is off — the flag is not in the session payload) is explained in place. Component tests mock `fetch` at the network boundary (`src/test/render.tsx`) and assert on the exact request bodies and headers, not on internals.
- **Dashboard:** `GET /analytics/summary` for today / yesterday / this week / this month with skeleton, error (retry) and empty states, plus quick actions, a low-stock card (all members, `/inventory/low-stock`) and the top debtors (OWNER, `/debtors`); STAFF see a non-analytics welcome card. Money is formatted from the backend's decimal strings without floats (`lib/money.ts`); dates use the session's business timezone (`lib/dates.ts`).

## 5. Authentication and authorization

### 5.1 Tokens
- **Access token:** JWT, HS256 with `JWT_SECRET` (≥ 32 characters; RS256 if a second service ever needs to verify tokens). Claims: `sub` (user id), `bid` (the business the session was opened for), `jti` (random), `iat`, `exp` (`ACCESS_TOKEN_TTL_MINUTES`, default 15), `typ: "access"`, plus `iss`/`aud` when `JWT_ISSUER`/`JWT_AUDIENCE` are set (then they are verified on every token; unset by default). The algorithm list is pinned to HS256 and every claim above is required, so `alg: none`, missing-claim and wrong-`typ` tokens are rejected. The role is deliberately absent: it is read from the membership on every request (§3.3). `bid` is not an authorization claim either — the membership for `(sub, bid)` is re-verified every time, and a token naming a business the user has no membership in is a 401. Nothing the client sends (body, query, header) can change `business_id` or `role`; the request models forbid unknown fields, so a smuggled `role` is a 422.
- **Refresh token:** `secrets.token_urlsafe(32)` (256 bits, never a UUID); only its SHA-256 hex digest is stored in `refresh_tokens.token_hash`. Lifetime `REFRESH_TOKEN_TTL_DAYS` (default 30). Rotation is one atomic `UPDATE … WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > now() RETURNING *`: under READ COMMITTED two concurrent refreshes with the same token cannot both match, so exactly one gets a child token (same `family_id`, `parent_id` = the consumed row) and the other is treated as reuse. **Reuse detection:** presenting a token that is already revoked (rotated away, logged out, or consumed by a concurrent request) revokes every live token in its `family_id`, is logged as a warning with ids only, and returns 401 `INVALID_REFRESH_TOKEN`; that revocation is committed even though the request fails. Unknown and expired tokens are also 401 but revoke nothing. A refresh while the business or membership is inactive is a 403 whose transaction rolls back, so the token is not consumed and works again once the business is reactivated. The frontend must serialise refreshes (one in-flight refresh promise) because a benign double refresh is indistinguishable from theft and ends the session.
- **Logout:** `POST /auth/logout` revokes the whole family of the presented cookie server-side and clears the cookie; it is idempotent (unknown, already-revoked or missing cookie → 204) and needs no bearer token, so an expired access token cannot trap a user in a session. `POST /auth/logout-all` (bearer) revokes every refresh token of the user, on every device. Access tokens are not revocable and stay valid until `exp` (≤ 15 min); nothing in MVP needs a denylist.
- **Transport:** access token in memory on the client (never localStorage) and sent as `Authorization: Bearer`. Refresh token in the `sokowise_refresh` cookie: `HttpOnly`, `Secure` (mandatory in production — settings refuse to start otherwise), `SameSite` = `COOKIE_SAMESITE`, `Path=/api/v1/auth` (so no other endpoint ever receives it), `Max-Age` = the refresh lifetime, `Domain` = `COOKIE_DOMAIN` when set (host-only otherwise). The body never contains it. The cookie is deleted on logout, logout-all and on any refresh failure.
- **CSRF:** the cookie-consuming endpoints (`/auth/refresh`, `/auth/logout`) require `X-Requested-With: sokowise`. A cross-site form cannot set a custom header, and a cross-origin `fetch` that sets it triggers a CORS preflight that only the allow-listed origins pass; the check is independent of the cookie's `SameSite` value, so it is what protects the cross-site (preview) mode. On top of that, every auth `POST` (register, login, refresh, logout, change-password) rejects a browser `Origin` header that is neither in `CORS_ORIGINS` nor matched by `CORS_ORIGIN_REGEX` (403 `CSRF_REJECTED`; `null` is rejected; requests without an `Origin`, i.e. non-browser clients, pass). The Origin check on login/register is what stops login CSRF (a foreign page logging the victim into the attacker's account). Bearer-only endpoints need no CSRF protection: the token is not an ambient credential.
- **Environments (decision for the deferred Vercel-preview question):**
  | Environment | App origin | API origin | Cookie | CORS |
  |---|---|---|---|---|
  | Local development | `http://localhost:5173` | proxied through Vite (`/api` → `localhost:8000`, `frontend/vite.config.ts`) so the cookie is same-origin | `COOKIE_SECURE=false`, `SameSite=Lax` | `http://localhost:5173` |
  | Production | `app.<domain>` (Vercel, custom domain) | `api.<domain>` (Railway, custom domain) — same registrable domain | `Secure; SameSite=Lax` (default), host-only on the API host | exact `CORS_ORIGINS` |
  | Vercel previews | `https://sokowise-*.vercel.app` (cross-site to any API domain) | a **separate preview API environment** on Railway (its own database) with `COOKIE_SAMESITE=none`, `COOKIE_SECURE=true`, `CORS_ORIGIN_REGEX=^https://sokowise-[a-z0-9-]+\.vercel\.app$` | `Secure; SameSite=None` | regex + exact list |
  Production never runs with `SameSite=None`; the cross-site mode exists only where the app is genuinely cross-site, and its CSRF protection is the custom header + Origin check above. Previews therefore have persistent logins without weakening production. The frontend needs no code change for this: the API base URL is already per-environment (`VITE_API_BASE_URL`).
- **Shared shop devices (decision for PRD A8):** MVP keeps the standard 30-day rotating refresh token and relies on explicit `logout` (revokes that device's family) and `logout-all` (every device), both immediate server-side; no plaintext credentials or tokens are ever persisted by the client beyond the HttpOnly cookie. No idle timeout, shorter lifetime or "shared device" login mode is added until the pilot shows that staff actually share a device (A8 is an assumption to validate). Should it be needed, a per-login `remember` flag that shortens the refresh lifetime is the smallest change and needs no schema work.

- **Sign in with Google (2026-09-18):** the frontend loads Google Identity Services only when `VITE_GOOGLE_CLIENT_ID` is set and posts the ID token to `POST /auth/google`. `app/auth/google.py` verifies it with PyJWT against Google's JWKS (`RS256`, `aud` = `GOOGLE_CLIENT_ID`, `iss` ∈ accounts.google.com, `email_verified` true). The service looks the account up by `users.google_sub`, then by verified email (linking on first use), and issues a normal session. An unknown identity gets a **signup token** (HS256, `typ=google-signup`, 15 min, claims `sub`/`email`/`name`) instead of a session; `POST /auth/google/register` takes that token plus phone, business name and type and creates user + business + OWNER with `password_hash NULL` and `google_sub` set. The email can only come from the token. A Google-only account fails password login exactly like a wrong password (`no_password` in the log, same 401), so nothing reveals how it was created. Both endpoints answer 503 `GOOGLE_NOT_CONFIGURED` without a client id.
- **Password reset by SMS (2026-09-18, FR-B6):** `POST /auth/password-reset/request {phone}` always answers 202. When the phone belongs to an active user, earlier live codes are expired, a 6-digit code from the CSPRNG is stored as SHA-256 of `user_id:code` in `password_reset_codes` (10-minute expiry) and sent through `app/notifications/sms.py` (`SMS_PROVIDER`: `africastalking`, or `console` in development only). `POST /auth/password-reset/confirm {phone, code, new_password}` consumes the live code in one UPDATE (`used_at`), refusing expired, used or 5-times-guessed codes with the same 400 `RESET_CODE_INVALID`; a wrong guess is counted in its own transaction. Success hashes the new password, clears `must_change_password`, revokes every refresh token and writes `user.password_reset` to the audit log. Rate limits: per IP and per phone for each step (`RATE_LIMIT_PASSWORD_RESET_*`). Without a provider both endpoints answer 503 `PASSWORD_RESET_NOT_CONFIGURED`; an SMS the provider refuses is 503 `SMS_UNAVAILABLE`. Logs carry user ids only, never phones or codes.

### 5.2 Passwords
- Argon2id via `argon2-cffi`, parameters in `app/core/passwords.py` (the only module that knows about Argon2): **m = 19 MiB, t = 2, p = 1**, 32-byte hash, 16-byte salt — the OWASP minimum the architecture starts from. Measured at ~28 ms per verification on a development laptop (i7-10610U); the target of roughly 100–250 ms on the deployed Railway instance has not been measured yet (no Railway environment exists), so raise `t` (then `m`) there before the pilot, staying within memory under concurrent logins (512 MB / 1–2 vCPU containers). `needs_rehash` + rehash-on-login means changing the constants is enough; old hashes are replaced as users log in. Passwords are capped at 128 characters so a login cannot make the server hash megabytes.
- Verification is constant-time inside the library. A login for an unknown identifier still verifies the password against a dummy hash so timing does not reveal whether the account exists, and unknown identifier, wrong password and deactivated user all produce the same 401 `INVALID_CREDENTIALS`.
- Minimum 8 characters; a small deny-list of common passwords (`app/schemas/auth.py`); no composition rules. The change-password endpoint requires the current password and rejects an unchanged one.
- **Rate limiting** is an in-house sliding-window limiter (`app/core/ratelimit.py`, ~50 lines) rather than `slowapi`: it needs no dependency, keys on whatever the endpoint chooses, and returns the project's error envelope (429 `RATE_LIMITED` + `Retry-After`). Keys: login per IP *and* per identifier (counted whether or not the account exists, so a 429 says nothing about existence), register per IP, refresh per IP, change-password per user. Rejected attempts are not counted, so a blocked client is not blocked longer by retrying. **Limitation:** counters live in process memory, and the backend runs 2–4 uvicorn workers, so the effective limit is up to N times the configured value and resets on deploy. This is accepted for the pilot; a shared store (database table or Redis) is the upgrade path if abuse appears. The Argon2 cost is the second line of defence. Behind Railway's proxy the service must set `FORWARDED_ALLOW_IPS=*` (uvicorn trusts `X-Forwarded-For` only from loopback by default) so the per-IP key is the client's address; the app logs a warning at start-up in production when it is unset (docs/OPERATIONS.md §1). As built the image runs a single uvicorn worker, so within one container the counters are exact.

### 5.3 Authorization
- Role checks are FastAPI dependencies (`require_role`, with `require_owner` and `require_member` ready-made), applied per route. The role is the membership row's `role` as read on this request; the two roles are OWNER and STAFF and there is no third.
- Status codes are the tenant-isolation contract: **404** whenever the caller has no membership in the business a request names (token selector, path id, anything) — the response never reveals that another tenant or its data exists; **403** only inside the caller's own business, when the membership is inactive, the business is inactive, the password must be changed, or the role is insufficient; **401** only for a missing/invalid access token or a deactivated user.
- Object-level checks are implicit: everything is loaded through business-scoped repositories (`get_member(session, business_id=ctx.business_id, user_id=…)`, never `get_member(user_id)`), so a resource from another business is simply not found (404).
- The permission matrix in PRD §16 is the specification; each row becomes at least one test. Phase 4 rows: business settings (view and edit) and user management are OWNER-only; STAFF read their business basics from `GET /auth/me`.
- **Members** (`/api/v1/users`, OWNER-only): list, create STAFF (`must_change_password=true`, 409 `ACCOUNT_EXISTS` if the phone/email is taken — one business per user, PRD FR-A4), get, change role / (de)activate the *membership* (`business_memberships.is_active`, never `users.is_active`, which is global), and reset a STAFF password (sets `must_change_password`, revokes their sessions). Owners are peers: an owner cannot reset another owner's password (403) and resets their own through `/auth/change-password`. Deactivation revokes the user's refresh tokens; their access token dies at its next request.
- **Last-owner rule:** a business always keeps at least one active OWNER. A change that would demote or deactivate the last one is 409 `LAST_OWNER`. `services/members.update_member` locks the business row (`SELECT … FOR UPDATE`) before counting owners, so two concurrent step-downs serialise and exactly one succeeds (tested with real connections in `tests/db/test_members_concurrency.py`).

### 5.4 Multi-tenancy
- Active business comes from the token (`bid`), not from the request body or query string; `bid` is only a selector and the membership lookup is what authorises (§3.3). Switching business (future) means issuing a new token.
- Membership is re-verified on every request so revocation is immediate.
- Every tenant-scoped endpoint is registered with the isolation check in `backend/tests/db/isolation.py` (§12): an `IsolationCase` names how to create the resource in business B and which URLs read, list and mutate it; the check asserts that business A gets 404 on all of them and never sees the id in a listing, in both directions. A PR adding a tenant-scoped endpoint without a case is incomplete (ROADMAP Phase 4).
- Phase 11 evaluates Postgres row-level security (`SET LOCAL app.business_id`) as a second layer; it is not relied upon in MVP.
- **Platform admin (operator dashboard, 2026-09-18).** The one deliberate exception to tenant scoping. `PLATFORM_ADMIN_PHONES` / `PLATFORM_ADMIN_EMAILS` (comma-separated, normalised to E.164 / lower-case) name the people who may call `GET /api/v1/admin/overview`; `require_platform_admin` in `app/api/deps.py` checks the *current user's phone or email* against those lists on every request (nothing in the token or the database grants it) and answers **404** to anyone else, so the endpoint never confirms it exists. It builds on `get_current_user` only — no business context, no membership — and refuses users who must change their password (403). `app/analytics/platform.py` is the only module allowed to aggregate across businesses: counts and totals (businesses, users by role, products, customers, completed sales and revenue, expenses, deni outstanding, M-Pesa messages, receipts, copilot messages, applied proposals; 7- and 30-day activity; sign-ups per local day; one row per business with name, type, product and sale counts, last sale and last sign-in). It returns no phone, owner name, customer or per-business money. The session responses carry `is_platform_admin` so the frontend can show the `/admin` route and nav item; the backend re-checks regardless. **Deleting an account:** `DELETE /api/v1/admin/businesses/{id}` (`services/platform_admin.delete_business`) is the one cross-tenant write. In a single transaction it removes every tenant row (children before parents, a test asserts the list covers every table with `business_id`), the memberships and the business, then any user whose only membership it was (with their refresh tokens and reset codes; a person who also belongs to another business keeps their login), and finally the receipt images in storage. It refuses a business the admin belongs to (409 `OWN_BUSINESS`), needs a trusted Origin, and is logged with the admin's user id because the business's own audit rows go with it. The frontend asks the operator to type the business name before the button works.

### 5.5 Audit logging
- `services/audit.record(session, ctx, action=…, entity_type=…, entity_id=…, before=…, after=…, client=…)` adds an `audit_logs` row to the caller's open transaction and never commits: the row lands with the change it describes or rolls back with it (tested). Services call it after the mutation, inside their `transaction(session)` block; `actor_user_id` and `business_id` come from the verified context, `ip`/`user_agent` from the request.
- Actions are `<entity>.<verb>` in lower snake case, declared in `AuditAction` (`business.update`, `user.create`, `user.role_change`, `user.deactivate`, `user.reactivate`, `user.password_reset`); later phases add theirs there following DATA_MAPPING §3.16. `before`/`after` carry only the changed fields as JSON-safe values; a no-op change writes no row.
- Never audited: passwords, hashes, tokens, cookies, headers. `record` also strips a fixed set of secret-looking keys defensively, and the endpoint schemas that feed it carry none. Phone numbers and names are not put in payloads either; the entity id is enough.
- The table has no `request_id` column; `record` writes an `audit` log line (with `audit_id`) under the bound request ID, which is how a row is correlated with a request.

### 5.6 Catalogue: categories and products
- **Endpoints:** `/api/v1/categories` (list, create, get, patch, delete) and `/api/v1/products` (list/search, create, get, patch). OWNER and STAFF read (sale entry needs the catalogue); only OWNER writes (PRD §16 "Create / edit products, prices"). There is no delete for products: `PATCH {"is_active": false}` archives.
- **Tenant scoping:** every repository function takes `business_id` from the verified `BusinessContext`; there is no lookup by bare id. A product's `category_id` is resolved through the same business-scoped lookup, so a category of another business — or none at all — is a 404 `NOT_FOUND` on create and patch, and the composite FK `(category_id, business_id) → categories(id, business_id)` backs that in the database. Both resources are registered with the isolation helper (§5.4).
- **Uniqueness** is decided by the database and translated to 409s: category name per business, case-insensitive (`CATEGORY_EXISTS`); *active* product name per business, case-insensitive (`PRODUCT_NAME_EXISTS` — an archived product frees its name, and cannot be unarchived while another active product holds it); SKU and barcode per business when present (`SKU_EXISTS`, `BARCODE_EXISTS`; archived products keep theirs reserved). Two businesses may share any name, SKU or barcode. Races are settled by the indexes and tested.
- **Categories** are labels with no lifecycle (DATA_MAPPING §3.5); delete succeeds only while no product, active or archived, carries the label (409 `CATEGORY_IN_USE`, `details.products`), so history never loses one. No default categories are seeded.
- **Money and quantities** are `Decimal` end to end: request fields are validated to the column bounds (money 14,2; quantities 12,3; never negative), responses serialise them as strings (`"150.00"`, `"12.500"`), and nothing in the path uses `float`.
- **Stock:** `products.stock_quantity` is the ledger cache (BR-11) and is not a request field anywhere. Product creation may carry `opening_stock` (> 0) with `opening_unit_cost` (defaults to `cost_price`; one of the two is required because INITIAL movements carry a cost, DATA_MAPPING §3.7); the product and its `INITIAL` movement are written in one transaction through `services/inventory.apply_movement`, the single primitive that appends a movement and moves the cache under the product row lock. Untracked products (`track_inventory=false`, e.g. services) refuse opening stock (422), never get movements and stay at 0; tracking cannot be switched off while stock remains (409 `PRODUCT_HAS_STOCK`). Restock/adjust/initial endpoints, low-stock and the recompute script are the inventory phase.
- **Lifecycle:** archived products disappear from the default list (`include_archived=true` shows them) but stay readable by id with their stock and movements; later phases must still write `SALE_REVERSAL` rows for them on void. Nothing is ever hard-deleted.
- **History:** product rows hold *current* state only; sale lines snapshot price and cost at sale time (BR-5) and movements keep their own `unit_cost`, so repricing never rewrites history.
- **Audit:** `product.price_change` (before/after of `selling_price`/`cost_price` that changed, as strings), `product.archive`, `product.unarchive` — the PRD FR-K1 set. Creating, renaming or recategorising a product and any category change are not audited.
- **Search:** `GET /products?q=` is a case-insensitive prefix match on name, SKU or barcode (LIKE wildcards escaped), plus `category_id`, `include_archived` and `limit` (≤ 500, the default; catalogues are a few hundred products).

### 5.7 Customers
- **Endpoints (Phase 6 slice):** `GET /api/v1/customers?q=&include_archived=&limit=`, `POST /api/v1/customers`, `GET /api/v1/customers/{id}`. OWNER *and* STAFF read and create (PRD §16 "Create / edit customers, record repayment" is a member permission: an attendant opens the account a credit sale needs). Update, archive, PII scrub, repayments, adjustments, ledger and debtors are Phase 7.
- **Ownership and isolation:** `business_id` comes from the verified context only; every repository function is business-scoped; a customer of another business is a 404 identical to a missing one. Registered with the isolation helper (read, list, and list-by-exact-phone).
- **Identity:** `phone` is optional and normalised exactly like user phones (`schemas.identifiers.normalize_phone`, E.164) so one person is one row per business; the partial unique index `(business_id, phone) WHERE phone IS NOT NULL` decides duplicates → 409 `CUSTOMER_PHONE_EXISTS` (race-tested). The same phone may exist in other businesses; customers without a phone and duplicate names are allowed. `credit_limit` is optional, ≥ 0, NUMERIC(14,2).
- **Search** is the `q` parameter of the list (no `/customers/search` path that could collide with an id): a case-insensitive *substring* of the name ("njeri" finds "Mama Njeri"), or a phone typed in any local form — `07…`/`01…`, `254…`, `+254…`, with spaces/dashes — matched as a prefix of the stored E.164 value, and bare national digits (`712345678`) matched anywhere in it. Parameterised LIKE with wildcards escaped; ordered by lower(name), id; `limit` ≤ 500.
- **Balance:** `customers.balance` is returned read-only as the cache of the credit ledger (DATA_MAPPING §3.8) and is never a request field; only CHARGE/REPAYMENT/ADJUSTMENT/REVERSAL ledger writes (sales and credit phases) move it. Phase 6 does not compute or display anything else about credit.
- **Lifecycle:** archived customers (`is_active=false`, Phase 7 endpoint) are hidden from the default list, shown with `include_archived=true`, and always readable by id (BR-12).
- **Privacy:** name, phone and notes are personal data (NFR-7): no customer field is logged, put in an error message or written to `audit_logs`. Customer creation is not audited (FR-K1 audits manual balance adjustments, not records).

### 5.8 Customer credit ledger
- **One convention, one writer.** `credit_transactions.amount` is the *signed effect on the balance* (PRD BR-7): `CHARGE` +, `REPAYMENT` −, `REVERSAL` −, `ADJUSTMENT` ±; `balance_after` is the running balance in posting order. `customers.balance` is the cache of Σ `amount` (DATA_MAPPING §6.4) and is written by exactly one function, `services.credit.post_entry`, which runs under `SELECT … FOR UPDATE` on the customer row, computes `balance_after` from the locked cache, moves the cache and inserts the row in the caller's transaction. Every reader (customer response, ledger, debtors) uses the cache; `repositories.credit.sum_entries` recomputes it from the rows for verification and the future `recompute_caches` script. Sales will post `CHARGE`/`REVERSAL` through the same function.
- **Endpoints:** `GET /api/v1/customers/{id}/ledger?limit=` (balance, credit limit, entries newest first by `occurred_at`); `POST /api/v1/customers/{id}/repayments` (OWNER and STAFF, PRD §16 "record repayment"); `POST /api/v1/customers/{id}/adjustments` (OWNER only, "adjust customer balance manually"); `GET /api/v1/debtors?sort=balance|age&limit=` (members; its own path because `/customers/{id}` would swallow `/customers/debtors`). All business-scoped through the context; a foreign customer is a 404 on every one of them; registered with the isolation helper as `customer-accounts`.
- **Repayments** (FR-G3): against the customer, not a sale; `amount > 0`, `payment_method` CASH or MPESA (`MoneyReceivedMethod`; recorded, never verified — no Daraja), optional `reference` (M-Pesa code). A repayment larger than the balance is 409 `REPAYMENT_EXCEEDS_BALANCE` unless `allow_overpayment: true`, which records the prepayment and takes the balance negative — BR-7's "credit in favour", made explicit so a typo or a double entry cannot do it silently. Audited as `credit.repayment` (entry id, amount, method, balance after; no customer data).
- **Adjustments** (FR-G2): `amount > 0` + `direction` INCREASE/DECREASE + mandatory `reason` (also a DB CHECK); stored signed. A decrease may not take the balance below zero (409 `ADJUSTMENT_EXCEEDS_BALANCE`) — to give back an overpayment, increase. Audited as `credit.adjust` with before/after balance and the reason.
- **Concurrency:** the customer row lock serialises every write to one account; two concurrent 800 repayments against 1 000 end with one 201, one 409 and a balance of 200 (tested with real connections, as are six concurrent partial repayments and racing adjustments). The lock is per customer, so accounts do not contend with each other.
- **Idempotency:** repayments and adjustments accept an optional `Idempotency-Key` header (UUID, client-generated). The key and a SHA-256 of `{operation, customer_id, payload}` are stored on the entry (`credit_transactions.idempotency_key/idempotency_hash`, unique per business when present — the `sales` pattern). Same key + same hash → 200 with the original entry and no write; same key + different payload, other customer or other operation → 409 `IDEMPOTENCY_CONFLICT`. The lookup happens under the customer lock, so concurrent retries post once; keys are per business.
- **Debtors** (FR-G4): `customers.balance > 0`, one aggregate query — a window-function subquery pays positive entries off FIFO by `occurred_at` against the total of negative entries to find `oldest_unpaid_charge_at` (positive `ADJUSTMENT`s count as charges). Sorted by balance (largest first) or age (oldest unpaid first); ties by name, id.
- **Credit limit** (FR-G5): `credit_limit` NULL = unlimited, 0 = no credit, exactly at the limit allowed. `services.credit.evaluate_credit_limit(customer, charge)` returns balance/limit/projected/exceeded; `enforce_credit_limit(customer, charge, role=…, owner_override=…)` raises 409 `CREDIT_LIMIT_EXCEEDED` (details carry the numbers and `owner_may_override`) for STAFF always and for OWNER unless they override — the "warned but may proceed" flow. Nothing in Phase 7 charges a customer; the sales phase calls these before posting a `CHARGE`.
- **Money:** `Decimal` throughout, quantised to 0.01 at posting; responses serialise as strings.

### 5.9 Sales and payments
- **Endpoints:** `POST /api/v1/sales` (members; `Idempotency-Key` header required), `GET /api/v1/sales?date_from=&date_to=&customer_id=&limit=` and `GET /api/v1/sales/{id}` (members — STAFF see only their own sales from today in the business timezone, OWNER everything; PRD §16), `POST /api/v1/sales/{id}/void` (OWNER, reason required). Registered with the isolation helper as `sales`.
- **One transaction, fixed order** (DATA_MAPPING §6.1): resolve `sold_at` → lock every product `FOR UPDATE` in **id order** (so two sales touching the same products in different orders never deadlock) → lock the customer if named (must be active) → compute lines from the locked rows → validate → insert sale, items, payments → `services.inventory.apply_movement(SALE)` per tracked line (stock check + cache + movement row, `sale_id` set) → `services.credit.post_entry(CHARGE)` when there is a CREDIT tender → commit. Any failure rolls the whole sale back (tested by failing after the ledger writes).
- **Server-side truth:** the client sends products, quantities, optional per-line `unit_price` overrides (FR-F3), a sale-level `discount_amount`, tender lines and an optional customer. Everything else is computed here: `line_total = round_half_up(qty × price)` (BR-9), `subtotal = Σ line_total`, `total = subtotal − discount` (discount ≤ subtotal, else 422 `DISCOUNT_EXCEEDS_SUBTOTAL`), and tender lines must sum to the total exactly (BR-1, else 422 `PAYMENTS_DO_NOT_BALANCE`). Client totals are never read.
- **Snapshots (FR-F5):** each item stores `product_name`, `unit_price`, `default_unit_price`, `unit_cost` (the product's `cost_price` at sale time, NULL when unknown — contributes 0 to COGS and is counted as `lines_missing_cost`, BR-16) and `discount_allocated`. Repricing, renaming or archiving a product afterwards changes nothing; movements keep their own `unit_cost`. Archived products cannot be put on a new sale (409 `PRODUCT_ARCHIVED`); archived customers cannot be named (409 `CUSTOMER_ARCHIVED`).
- **Discount allocation (BR-14):** `services.money.allocate_discount` splits the discount pro-rata by line total with largest-remainder rounding — floor every share to the cent, hand the leftover cents one by one to the largest fractional remainders (earlier lines win ties). Σ `discount_allocated` = `discount_amount` exactly, and no line exceeds its own total (also a DB CHECK).
- **Tenders:** one or more payment lines (split payments), methods CASH / MPESA / CREDIT (`PaymentMethod`), always `status=CONFIRMED`, `provider=MANUAL`. MPESA lines carry an optional typed reference that is recorded, never verified (no Daraja). A CREDIT line requires a customer (schema-level), and its amount is posted as one `CHARGE` on the customer's ledger with `sale_id` and `payment_id`, through the Phase 7 primitive — the sales service never touches `customers.balance` itself. **Revenue** is `total_amount` of COMPLETED sales (accrual, credit included); **cash collected** is CONFIRMED CASH/MPESA tenders plus credit REPAYMENTs; a CREDIT tender is a receivable and a repayment is never revenue (BR-15).
- **Credit limit (FR-G5):** `services.credit.enforce_credit_limit` runs on the locked customer before anything is written: STAFF over the limit → 409 `CREDIT_LIMIT_EXCEEDED`; OWNER gets the same 409 (the warning, with the numbers and `owner_may_override`) and proceeds by resending with `credit_limit_override: true`, which is audited as `sale.credit_limit_override`. Exactly at the limit is allowed; `credit_limit` 0 refuses all credit; NULL is unlimited.
- **Untracked products** (services) sell without stock checks or movements and still snapshot cost for profit (FR-E1).
- **Stock:** `apply_movement` refuses a SALE that would take a tracked product below zero (409 `INSUFFICIENT_STOCK`) and nothing partial is written. Because every sale holds the product row locks, two sales of the last unit serialise: one 201, one 409, stock 0 (tested with real connections, as are five-way oversell attempts, opposite lock orders, and a credit-limit race).
- **Idempotency (FR-F6):** the `Idempotency-Key` (UUID) is mandatory. The hash is SHA-256 of the canonical request (lines with product, quantity, price override; payments with method, amount, reference; customer; discount; note; `sold_at`; override flag). Same key + same hash → 200 with the original sale and no side effects; different hash → 409 `IDEMPOTENCY_CONFLICT`. The unique `(business_id, idempotency_key)` settles concurrent duplicates (the loser re-reads and answers as a replay), so four identical concurrent requests yield one sale, one movement, one CHARGE. Keys are per business.
- **Backdating (FR-F8):** `sold_at` may be set by OWNER only (403 for STAFF), within `settings.sale_backdate_days` (422 `SALE_BACKDATE_WINDOW`), never in the future beyond clock skew (422 `SALE_IN_FUTURE`). Movements and the CHARGE carry the same `occurred_at`; their running balances still follow posting order (DATA_MAPPING §3.7).
- **Void (FR-F7, BR-3, BR-8):** OWNER only, reason required, the row stays. Under the sale row lock: a `SALE_REVERSAL` for every `SALE` movement the sale wrote (products locked in id order; archived products included), a `REVERSAL` for the full charged amount when the sale had a CREDIT tender (`allow_negative=True`, so a repaid-then-voided sale leaves a credit in favour), status → VOIDED with `voided_at/by/reason`, audit `sale.void`. Voiding twice is 409 `SALE_ALREADY_VOIDED`. Voided sales stay in listings with their status; analytics filter `status = 'COMPLETED'`.
- **Responses** carry items (snapshots, allocation) and tender lines but not `unit_cost` or profit — those are analytics, OWNER-only (§16). Sale creation itself is not audited (FR-K1); void and credit-limit overrides are.

### 5.10 Inventory operations
- **Endpoints:** `POST /api/v1/inventory/restock` (OWNER, or STAFF when the business setting `staff_can_restock` is on — PRD §16), `POST /api/v1/inventory/adjust` (OWNER), `POST /api/v1/inventory/initial` (OWNER; opening stock for a tracked product that has no movements yet, else 409 `PRODUCT_ALREADY_STOCKED`), `GET /api/v1/inventory/movements?product_id=&movement_type=&date_from=&date_to=&limit=` (members), `GET /api/v1/inventory/low-stock` (members), `POST /api/v1/inventory/recompute` (OWNER). Registered with the isolation helper as `inventory`.
- **One writer:** every operation goes through `services.inventory.apply_movement` under the product row lock, exactly like sales and voids, so the ledger row and the `stock_quantity` cache move together (BR-11) and concurrent writers serialise (tested: six concurrent restocks land with six distinct `quantity_after`; four concurrent −2 adjustments against 5 let exactly two through; a restock racing a sale leaves cache == ledger either way). Products must be active and tracked (409 `PRODUCT_ARCHIVED`, 422 `PRODUCT_UNTRACKED`); a foreign product is a 404.
- **Restock** (FR-E5, BR-6): quantity > 0, `unit_cost` required (INITIAL/RESTOCK rows carry cost), optional `supplier_name`/`reason`; `update_cost_price: true` also sets the product's current `cost_price` (audited inside the same row). Restocks are stock in, never expenses. **Adjustment** (BR-4): signed `quantity_delta` ≠ 0 with a mandatory reason (also a DB CHECK); a decrease below zero is 409 `INSUFFICIENT_STOCK`. Audit actions: `inventory.restock`, `inventory.adjust`, `inventory.initial`, `inventory.recompute`, written in the operation's transaction (rollback tested).
- **History** is newest first by posting order (`created_at`, then id). `quantity_after` is the balance at posting; `occurred_at` (business time, backdated by an OWNER-dated sale) is a filter only. A backdated sale posted after a restock therefore shows the post-restock balance (tested with real commits).
- **Low stock** (FR-E4): active, tracked products with `stock_quantity <= coalesce(low_stock_threshold, settings.low_stock_default_threshold)`, one query, ordered by how far below the threshold they are, then name.
- **Recompute** (DATA_MAPPING §6.4): for every tracked product (archived included) lock the row, compare the cache with Σ `quantity_delta`, report — and with `apply: true` rewrite the cache to the ledger value (no movement is written; the ledger is the truth) with an `inventory.recompute` audit row. `scripts/recompute_caches.py` runs the same service for every business (exit 1 on drift unless `--apply`). Customer balances are not covered by it (`repositories.credit.sum_entries` is their check).

### 5.11 Analytics
- **Endpoints (OWNER-only, PRD §16):** `GET /api/v1/analytics/summary`, `/timeseries?granularity=day|week|month`, `/products?sort=quantity|revenue|profit&limit=`, `/slow-products?days=&limit=`, `/categories`; each period endpoint takes `period=today|yesterday|this_week|this_month` or `period=custom&date_from=&date_to=` (≤ 366 days, else 422 `INVALID_PERIOD`). `app/analytics/` holds the read-only query functions the AI phase will reuse; it imports models only, never services.
- **Time (BR-10):** `app/analytics/periods.py` turns local calendar days in `businesses.timezone` into a half-open UTC interval `[00:00 date_from, 00:00 day-after-date_to)`; named periods are relative to "now" in that timezone (`this_week` = Monday..today, `this_month` = 1st..today). Time-series buckets are `date_trunc` of `sold_at AT TIME ZONE tz` (weeks start Monday, months on the 1st) and report the local bucket start date. A sale at 23:30 EAT belongs to that local day (tested).
- **Definitions (FR-I1, BR-15, BR-16), all over COMPLETED sales by `sold_at` — voided sales never count:** `revenue` = Σ `total_amount` (accrual; credit tenders included; discounts already deducted); `discounts` = Σ `discount_amount`; `cogs` = Σ `quantity × sale_items.unit_cost` over lines with a known cost (the sale-time snapshot, never today's cost_price); `lines_missing_cost` / `products_missing_cost` count what contributed 0; `gross_profit` = revenue − cogs; `expenses` = Σ non-deleted `expenses.amount` with `incurred_at` in the period (0 until the expenses phase); `net_profit` = gross_profit − expenses; `tender_split` = Σ `payments.amount` by CASH/MPESA/CREDIT; `cash_collected` = CONFIRMED CASH/MPESA tenders on period sales **plus** credit REPAYMENTs with `occurred_at` in the period, by method — a CREDIT tender is never cash and a repayment is never revenue; `receivables_outstanding` = Σ positive `customers.balance` (point in time).
- **Products (FR-I2):** per product, `quantity`, `revenue` = Σ `line_total − discount_allocated`, `cogs`, `gross_profit`, `sales_count`, `lines_missing_cost`; sorted by the chosen metric desc, then name, id. Because discount is allocated at sale time, Σ product profit = period profit (tested). Archived products keep their history (`is_active` reported). **Categories:** the same grouped by `products.category_id`, with a `null` row for uncategorised products. **Slow products (FR-I3):** active, tracked, `stock_quantity > 0`, no COMPLETED sale in the last `days` (default 30); returns `last_sold_at`, ordered never-sold first, then oldest sale, then stock. These are facts, not judgements.
- **Performance:** one aggregate query per figure (summary runs seven; time series five grouped queries merged by bucket), no per-row round trips, results bounded (`limit` ≤ 200 products). Money returns as NUMERIC → Decimal and is rounded half-up to the cent once, in Python.

### 5.12 Expenses and the financial overview
- **Endpoints (all OWNER-only, PRD §16 "Record expenses" / "Export data"):** `GET/POST /api/v1/expenses`, `GET/PATCH/DELETE /api/v1/expenses/{id}`, `GET /api/v1/expenses/categories`, `GET /api/v1/expenses/export.csv`, `GET /api/v1/analytics/expenses`. Registered with the isolation helper as `expenses`. Static paths are declared before `/{expense_id}`.
- **Model (FR-H1, DATA_MAPPING §3.13):** `amount` > 0 (14,2), `category` free text normalised to trimmed upper case (so "rent" and "Rent " group together; the fixed suggestions RENT, TRANSPORT, UTILITIES, AIRTIME, SALARIES, LICENSES, OTHER plus the business's own used categories come from `/expenses/categories`), `payment_method` CASH or MPESA (`MoneyReceivedMethod` — no other methods exist), optional `reference`/`note`, `incurred_at` (aware datetime; defaults to now; may be in the past, never in the future beyond clock skew → 422 `EXPENSE_IN_FUTURE`). Expense categories are *not* the product `categories` table. Restocks are never expenses (BR-6).
- **Lifecycle (FR-H3):** PATCH changes the fields present (amount, category, method, reference, note, incurred_at) under the row lock and audits the changed fields as `expense.update`; DELETE is a soft delete (`deleted_at`, audited as `expense.delete`, idempotent) — the row stays readable by id, listings and every total skip it (`include_deleted=true` shows it), and editing a deleted expense is 409 `EXPENSE_DELETED`. Creation is not audited (FR-K1 audits edit/delete). No hard delete exists.
- **No idempotency key:** FR-F6 requires one for sales only; a duplicated expense is visible and deletable, so the extra machinery is not worth its surface. Concurrent creates simply all land; concurrent edit/delete serialise on the row lock.
- **Listing and export:** `date_from`/`date_to` are inclusive local calendar days in the business timezone (the analytics convention), plus `category`, `payment_method`, `include_deleted`, `limit` ≤ 200; newest first by `incurred_at, id`. `export.csv` (NFR-12) streams non-deleted rows oldest first in keyset batches of 500 — columns `date, time, category, amount, payment_method, reference, note`, dates/times local, amounts as `"450.00"`, UTF-8, no ids and nothing from another business. Sales and customer CSV exports are still to come.
- **Financial overview** is `GET /analytics/summary` (FR-I1); the expense figures now populate it: `expenses` = Σ non-deleted expenses with `incurred_at` in the period, `net_profit` = `gross_profit − expenses` (FR-I1's term). Expenses sit *below* gross profit and never touch revenue, COGS, tenders, cash collected, receivables, stock or customer balances (tested end to end, including a void afterwards). Time-series buckets carry `expenses` and `net_profit` too. `GET /analytics/expenses` gives the period total, count, `by_category` (largest first) and `by_method` (CASH/MPESA) from grouped SQL (FR-I6). The concepts stay separate: revenue ≠ cash collected; gross profit ≠ net profit; credit ≠ cash; repayment ≠ revenue; expense ≠ restock.

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

**Proposal tools (as built 2026-09-18, `app/ai/proposals.py`).** Four more tools are declared to the model but are *never executed*: `propose_product`, `propose_sale`, `propose_repayment`, `propose_restock`. Their strict schemas are the Pydantic models in `app/ai/proposals.py`; ids inside them (`product_id`, `customer_id`) must come from `search_products` / `search_customers`. When the model calls one, the orchestrator ends the tool loop, validates the arguments against the schema (invalid → dropped, the answer is stored without a proposal), and stores `{kind, payload}` on the assistant message with `proposal_status = PENDING`. The `ai` module still never imports `services`.

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
8. The AI module has no write path. A proposal (§6.2) is data on the message. `POST /ai/conversations/{cid}/messages/{mid}/confirm` (OWNER, body `{payload}`) is handled by `services/ai_actions.confirm`, which is the only path from a proposal to a record: it re-validates the confirmed (possibly edited) payload from scratch, checks the message belongs to the caller's business and conversation, is an assistant message with a PENDING proposal not older than 24 h (`PROPOSAL_EXPIRED` 409 otherwise, `PROPOSAL_NOT_PENDING` 409 once applied or rejected), then calls the normal service: `products.create_product`, `sales.create_sale`, `credit.record_repayment`, `inventory.restock`. Sales and repayments use an idempotency key derived from the message id (`uuid5`), so a retried confirm replays instead of double-recording. Service errors (insufficient stock, credit limit, duplicate name, foreign id → 404) surface unchanged and leave the proposal PENDING. On success the message row is locked, marked APPLIED with the entity id, and an `ai.proposal_apply` audit row records the kind, entity and whether the owner edited the payload. `…/reject` marks it REJECTED with `ai.proposal_reject`. The frontend renders the proposal as an editable card under the answer; nothing happens until the owner taps Confirm.

### 6.5 Cost and quota
- Per-business quotas are server-side configuration (`AI_DAILY_MESSAGE_LIMIT`, default 10 user messages/day; `AI_MONTHLY_MESSAGE_LIMIT`, default 100/calendar month), checked before calling the API and counted from `ai_messages` rows with `role='user'`. They are not part of `businesses.settings` and no API lets an owner change them.
- The defaults are conservative on purpose. At the start of Phase 9: read current pricing from the Anthropic documentation (never from memory), measure real per-message cost from `usage` over the eval run, and set the quotas so that a business at quota stays within the PRD §18 cost target.
- Global monthly spend estimate from token usage; alert at 80%; hard stop at 100% (configurable).
- Prompt caching on the stable prefix. Caching only applies above the model's minimum cacheable prefix, so Phase 9 must confirm `usage.cache_read_input_tokens > 0` on the second and later requests; if it is 0, the prefix is either too short or something volatile sits inside it. Conversation window bounded (last N messages / token estimate).

### 6.6 Evaluation
- A fixture business with known answers; question→expected pairs for English and Swahili; injection and refusal cases.
- CI runs tool-level tests with recorded outputs (no model call). A nightly job runs the live eval and reports numeric accuracy.

### 6.7 Receipt intelligence (as built, 2026-09-17)
- **Principle:** the model is an *extraction assistant*, never a writer. Pipeline: image → `ReceiptExtractionProvider` (image → structured proposal) → backend validation → product matching → owner review → owner confirmation → `services.inventory.restock_in_transaction` per line in **one** transaction → `inventory_movements`. Nothing in `app/ai` or `app/services/receipts.py` writes a movement; the inventory service remains the only path, exactly as a manual restock.
- **Endpoints (OWNER-only; `app/api/v1/receipts.py`):** `POST /api/v1/receipts` (multipart `file`) → 201 `UPLOADED`; `GET /receipts` (newest first, ≤ 100); `GET /receipts/{id}` (with lines); `GET /receipts/{id}/image` (authenticated, `Cache-Control: private, no-store`); `POST /receipts/{id}/process` (UPLOADED or FAILED → PROCESSING → READY_FOR_REVIEW | FAILED); `POST /receipts/{id}/confirm`; `POST /receipts/{id}/cancel`. Cross-tenant ids are 404 everywhere (isolation helper test). STAFF get 403: confirmation moves stock and the receipt flow is owner-only in MVP even where `staff_can_restock` would allow a manual restock.
- **Upload validation (`services.receipts.validate_image`):** the client's `Content-Type` and extension are ignored; the format is sniffed from bytes (JPEG, PNG, WebP only), decoded and verified with Pillow, bounded by `RECEIPT_MAX_BYTES` (8 MB default, read in 256 KB chunks so nothing larger is ever buffered), `RECEIPT_MAX_PIXELS` (25 MP) and `RECEIPT_MIN_SIDE_PX` (200). HTML, SVG, PDF, executables and truncated images → 422 `RECEIPT_IMAGE_INVALID`; oversize → 413 `RECEIPT_TOO_LARGE`.
- **Storage (`app/storage`):** `BlobStorage` protocol (`put/get/delete` by key). `LocalFileStorage` under `RECEIPT_STORAGE_DIR` (default `var/receipts`, git-ignored) writes atomically and refuses any key outside its root; keys are `receipts/{business_id}/{receipt_id}.{ext}` generated by the service. The database stores the key, never the bytes. Production: an S3-compatible implementation of the same protocol (same keys); images are never exposed by public URL. The blob is written inside the upload transaction, so a storage failure (503 `STORAGE_UNAVAILABLE`) leaves no row.
- **Extraction contract (`app/ai/receipts.py`):** `ReceiptExtraction{supplier_name?, receipt_number?, receipt_date?, currency?, subtotal?, total?, lines[{product_name, sku?, quantity>0 (3 dp), unit_cost≥0, line_total?≥0, confidence?∈[0,1]}]}` — strict Pydantic models (`extra="forbid"`, ≤ 60 lines). The Anthropic provider sends the image (base64) plus a fixed instruction and **forces** a `record_receipt` tool call whose strict JSON schema is this contract, so the model cannot return anything else; the tool input is re-validated by Pydantic. No business, product or customer data is sent with the image — the provider signature is `extract(image, mime_type)` and nothing more exists to pass (tested). Provider failures map like the copilot's (503 `AI_TIMEOUT` / `AI_PROVIDER_BUSY` / `AI_UNAVAILABLE`); an unparseable answer or no lines → 503 `RECEIPT_EXTRACTION_FAILED`; no key configured → 503 `RECEIPT_AI_NOT_CONFIGURED` (the upload is kept and can be processed later). There is no fake provider in production code; tests inject `FakeReceiptExtractionProvider` through the `get_receipt_provider` dependency.
- **Backend validation (untrusted input):** per line, `quantity × unit_cost` is compared with the printed `line_total` with a tolerance of max(KSh 1.00, 1%) → `line_total_mismatch`; `zero_unit_cost`; `low_confidence` (< 0.6). Per receipt, the line sum is compared with the printed subtotal/total (same tolerance) → `subtotal_mismatch` / `total_mismatch`; `currency_not_kes`. Warnings are stored as codes (`receipts.warnings`, `receipt_lines.warnings`) and shown to the reviewer; nothing is corrected silently and no model prose is stored.
- **Matching (`services/receipt_matching.py`):** against the business's active products only. SKU/barcode equality or a normalised exact name → `MATCHED`; the best `SequenceMatcher` score ≥ 0.90 with no runner-up ≥ 0.90 → `MATCHED`; otherwise scores ≥ 0.70 (top 3) → `AMBIGUOUS` with `candidate_product_ids`; else `UNMATCHED`. The model never sees or produces product ids; only `MATCHED` lines are pre-ticked in the UI.
- **Confirmation (`services.receipts.confirm`):** `{lines:[{line_id, product_id, quantity, unit_cost, update_cost_price}], supplier_name?, reason?}` — the owner's final values, not the extraction's. Inside one transaction: `SELECT … FOR UPDATE` on the receipt; status must be `READY_FOR_REVIEW` (`CONFIRMED` → 409 `RECEIPT_ALREADY_CONFIRMED`, anything else → 409 `RECEIPT_INVALID_STATE`); every `line_id` must belong to the receipt (422 `RECEIPT_LINE_INVALID`); each line goes through `restock_in_transaction`, which locks the product and applies the existing rules (another business's or unknown product → 404, archived → 409 `PRODUCT_ARCHIVED`, untracked → 422 `PRODUCT_UNTRACKED`), writes the `RESTOCK` movement with the confirmed unit cost, optionally sets `products.cost_price`, and records the usual `inventory.restock` audit (plus `receipt_id`/`receipt_line_id`). Lines not in the payload are `SKIPPED`. Any failure rolls back everything (tested for each case). The row lock serialises concurrent confirmations: one 200, the rest 409, one set of movements (tested with four simultaneous requests).
- **Cost model:** unchanged. The confirmed unit cost becomes the movement's `unit_cost` (and the product's `cost_price` only when the owner ticks it); historical `sale_items.unit_cost` snapshots are untouched, so past profit does not move.
- **Audit:** `receipt.upload` (mime, size, dimensions), `receipt.extract` (status, provider, model, line and match counts, warnings — or the error code), `receipt.confirm` (movement ids, skipped count), `receipt.cancel`, plus one `inventory.restock` per applied line. No image bytes, no prose.
- **Frontend:** Inventory → **Scan receipt** → `/inventory/receipts` (list + camera/file input, `accept` limited to the three formats, `capture="environment"`; size/type checked before upload, re-checked by the server) → upload then immediate processing → `/inventory/receipts/{id}` review: status banner, receipt-level warnings, one card per line with match badge (Matched / Which product? / Not in your products), "Hard to read" flag, line warnings, include checkbox, product picker (tracked products only, with a link to create the product under Products), editable quantity and cost, optional "make this the cost price"; a summary (products, total quantity, total supplier cost, the list of what will be restocked) and a confirmation dialog; success state links to the movements. Owner-only route under `RequireOwner`.
- **When Anthropic billing is unavailable:** uploads, storage, listing, the image endpoint, cancel and the whole review/confirm path work; `process` returns the provider's safe 503 and the receipt is marked `FAILED` with the error code so it can be retried later. Nothing is faked.
- **Retention and storage in production (2026-09-17):** local files are development-only; production must set `RECEIPT_STORAGE_DIR` to an absolute path on a persistent volume (enforced at start-up) until an object-storage `BlobStorage` exists. Keys are `receipts/<business_id>/<uuid>.<ext>`, generated server-side and re-validated against the root on every read. Cancelling keeps the row and the image; confirmed receipts and their images are financial records and are never deleted; images of CANCELLED/FAILED/never-read receipts become eligible for deletion 30 days after their last status change (policy in `docs/OPERATIONS.md` §3 — no purge job yet). Matching considers the first 500 active products by name.
- **Open:** object-storage backend, the image purge job, creating a product from the review screen in one step, a live accuracy check of the Anthropic provider (needs API billing).

### 6.8 As built (AI phase, 2026-09-17)
- **Module:** `app/ai/` — `provider.py` (the `AIProvider` protocol and the official `anthropic` SDK implementation, `AsyncAnthropic`, one retry, `AI_REQUEST_TIMEOUT_SECONDS`), `tools.py` (the registry), `periods.py` (natural-language periods), `prompts.py` (system prompt + volatile context), `service.py` (the orchestrator), `errors.py`; `app/repositories/ai.py` for the two AI tables; `app/api/v1/ai.py` for the endpoints; `app/schemas/ai.py`. The package imports `analytics`, three named repository read functions (`list_debtors`, `list_customers`, `list_low_stock`) and the `businesses`/`users` repositories for the prompt context — never `services`.
- **Endpoints (OWNER-only, PRD AI-14):** `GET /api/v1/ai/quota`, `POST/GET /api/v1/ai/conversations`, `GET /api/v1/ai/conversations/{id}` (with messages, newest 200), `POST /api/v1/ai/conversations/{id}/messages` (`{content}` ≤ 2,000 chars → `{user_message, assistant_message, quota}`). Conversations are scoped by `business_id` **and** `user_id`: another business's id, and another owner's conversation in the same business, are both 404. Without `ANTHROPIC_API_KEY` every AI endpoint is 503 `AI_NOT_CONFIGURED` and nothing else in the app is affected (FR-J8).
- **Tools (all read-only, no `business_id` parameter anywhere, strict schemas with every property required and `additionalProperties: false`):** `get_business_summary`, `get_sales_summary` (+ top products by revenue ≤ 10), `get_product_performance` (sort quantity|revenue|profit, ≤ 20), `get_slow_products` (≤ 90 days, ≤ 20), `get_inventory_status` (low stock ≤ 50, thresholds from the business default), `get_debtors` (≤ 50, no phone numbers), `get_expense_summary`, `search_customers` (name or normalised phone, ≤ 10, returns id/name/balance/limit, no phone). Money is returned as decimal strings with `currency: "KES"`; every summary carries `notes` restating the definitions (credit ≠ cash, repayments ≠ revenue, missing-cost understates profit) so the model relays them. Outputs over 12,000 characters are refused rather than truncated. Periods: `today|yesterday|this_week|last_week|this_month|last_month|custom(date_from,date_to)` resolved from the server clock in `businesses.timezone`, ≤ 366 days, never in the future (a range past today is cut at today; a start after today is an error the model sees).
- **Read-only execution:** each tool call runs inside a savepoint with `SET LOCAL transaction_read_only = on`; a write fails at the database and rolling the savepoint back restores the request's normal transaction for persisting the answer (tested with a rogue tool).
- **Loop and guardrails:** at most `AI_MAX_TOOL_ROUNDS` (6) tool rounds per question, then 503 `AI_INCOMPLETE`; unknown tools, schema-invalid arguments and period errors go back as `is_error` tool results, never exceptions; unsupported content blocks → 503 `AI_INVALID_RESPONSE`; `refusal` → 503 `AI_REFUSED`; empty text → 503 `AI_INVALID_RESPONSE`; `max_tokens` is stored as the stop reason and the UI says the answer was cut short (no post-hoc truncation anywhere). Provider timeouts, rate limits, connection and status errors map to 503 `AI_TIMEOUT` / `AI_PROVIDER_BUSY` / `AI_UNAVAILABLE` with fixed messages — the provider's text, model name or key state never reaches the client.
- **Persistence:** the user message is committed before the provider is called; on any failure it stays and no assistant message is written. Re-sending the identical question as the next message reuses that row (no duplicate, no second quota hit). The assistant row stores the text, `tool_calls` (name, input, ok, duration, bounded output summary), model, token usage incl. cache reads, stop reason and latency. Timestamps are set by the service so the two rows of one turn order deterministically.
- **Quota:** `AI_DAILY_MESSAGE_LIMIT` (10) and `AI_MONTHLY_MESSAGE_LIMIT` (100) per business, counted from `ai_messages` rows with `role='user'` since local midnight / the local 1st; checked before persisting the question; 429 `AI_QUOTA_EXCEEDED` with `details.scope`, `limit`, `used`, `resets_at` and `Retry-After`. `businesses.settings` rejects any AI key (422), so owners cannot change the limits. Plus an in-process burst limit per user on the ask endpoint (`RATE_LIMIT_AI_MESSAGES_PER_MINUTE`, 10).
- **Prompting:** the system prompt is one cached block (`cache_control: ephemeral`) with the role, the money vocabulary (revenue vs cash collected vs receivables, missing-cost rule), the read-only stance and the injection rules; a second uncached block carries business name/type, currency, timezone, local date and time, the user's first name and role. User text is always a user turn; business data only ever appears inside `tool_result` blocks. Adaptive thinking (`AI_THINKING=adaptive`) is requested; thinking blocks are replayed verbatim on tool rounds and never stored or shown.
- **Not streamed yet:** the answer is returned once complete (one JSON response). SSE streaming, the eval set with recorded tool outputs and the nightly live run, cost-per-message measurement and the global monthly spend cap remain open (see ROADMAP).
- **Frontend:** `/assistant` (`features/assistant/`, nav "Copilot", OWNER-only like Analytics): conversation list (sidebar on desktop, a select on phones), example questions, Enter-to-send composer, a "Checking your records…" status while waiting, the answer with which records were checked, a "cut short" note on `max_tokens`, safe error alerts with Retry (except on quota), and the remaining daily/monthly questions. Nothing is rendered that did not come from the backend.

## 7. External integrations (M-Pesa)

### 7.1 SMS matching (as built, 2026-09-18)
Every M-Pesa payment a shop receives arrives as a confirmation SMS on the shop's phone (Pochi la Biashara, Buy Goods/Till, Paybill, or a plain "send money"). The owner or attendant pastes that SMS, or shares it from the Messages app, and SokoWise links it to the record of the money.

- **Parser** `app/mpesa/parser.py`: a pure function that needs a 10-character transaction code, an amount and a date; direction (received vs sent), product kind, sender name, the masked sender phone and a Paybill account are best effort. Times are parsed as Africa/Nairobi and stored in UTC. Customer-side messages ("sent to", "paid to") are refused as `NOT_MONEY_RECEIVED` and never stored; unreadable text is kept as `UNPARSED` so unknown Safaricom templates surface during the pilot.
- **Table** `mpesa_messages` (DATA_MAPPING §3.19): a side table. A message never creates a sale, payment or ledger entry by itself; it is *linked* to the `payments` row (an M-Pesa tender of a COMPLETED sale) or the `credit_transactions` REPAYMENT that carries the same code. Unique `(business_id, code)`, so a second paste replays the first (200, `created=false`; a concurrent race is settled by the index and answered as a replay).
- **Rules** (`services/mpesa.py`, all scoped by the caller's business): (a) code equals an existing unlinked M-Pesa tender → MATCHED; (b) code equals an M-Pesa repayment reference → MATCHED; (c) otherwise UNMATCHED with *suggestions* only: tenders of the same amount within ±120 minutes that carry no known code, and active customers whose phone ends with the sender's visible digits. Suggestions are never applied automatically.
- **Reverse hook**: when a sale or a repayment is later recorded with an M-Pesa reference, `services.sales` / `services.credit` call `link_reference_in_transaction`, which updates at most one UNMATCHED message inside the same transaction. Voiding a sale returns its message to UNMATCHED. This is why the sell screen opened from a message needs no message id: it prefills the tender and code, and the hook links.
- **Transitions**: UNMATCHED → MATCHED (paste rule, manual match, repayment-from-message, reverse hook; OWNER and STAFF); UNMATCHED/UNPARSED → IGNORED (OWNER only); MATCHED → UNMATCHED (void). Everything else is 409 `MPESA_INVALID_TRANSITION`. Audit actions `mpesa.paste`, `mpesa.match` (with `via`), `mpesa.ignore`, `mpesa.unlink` carry ids, codes, amounts and statuses, never text, names or phones.
- **Reconciliation** `GET /mpesa/reconciliation?date=`: for one local day, messages received (count, sum), matched, unmatched, ignored and unparsed, next to the M-Pesa money the app recorded (tenders + repayments from `analytics.cash_collected`). The dashboard card and the M-Pesa page show it.
- **Privacy**: raw SMS text, sender name and phone stay in the tenant table; they are not logged, not exported, and no AI tool reads the table.
- **Share target**: `frontend/public/manifest.webmanifest` declares `share_target` → `/mpesa?text=…`; the page prefills the paste box. Installing the app from Chrome ("Add to Home screen") is what makes SokoWise appear in Android's share sheet. No service worker.

### 7.2 Daraja (designed now, built later)

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
- Domain exceptions (`UnauthorizedError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError`, `RateLimitedError`, and later `ValidationError`, `InsufficientStockError`, `CreditLimitExceededError`, `AIUnavailableError`) subclass `app.core.errors.AppError` (which carries `status_code`, `code`, a user-safe `message`, optional `details` and optional response `headers` such as `WWW-Authenticate` or `Retry-After`) and are mapped to HTTP by the handlers in that module. A subclass's default `code` can be overridden per instance for a more specific stable code: authentication uses `INVALID_CREDENTIALS`, `INVALID_REFRESH_TOKEN` (401), `PASSWORD_CHANGE_REQUIRED`, `BUSINESS_INACTIVE`, `MEMBERSHIP_INACTIVE`, `CSRF_REJECTED` (403), `INVALID_CURRENT_PASSWORD` (400), `PRODUCT_UNTRACKED` (422), `ACCOUNT_EXISTS`, `LAST_OWNER`, `CATEGORY_EXISTS`, `CATEGORY_IN_USE`, `PRODUCT_NAME_EXISTS`, `SKU_EXISTS`, `BARCODE_EXISTS`, `PRODUCT_HAS_STOCK`, `INSUFFICIENT_STOCK`, `CUSTOMER_PHONE_EXISTS`, `REPAYMENT_EXCEEDS_BALANCE`, `ADJUSTMENT_EXCEEDS_BALANCE`, `BALANCE_WOULD_BE_NEGATIVE`, `CREDIT_LIMIT_EXCEEDED`, `IDEMPOTENCY_CONFLICT`, `PRODUCT_ARCHIVED`, `CUSTOMER_ARCHIVED` and `SALE_ALREADY_VOIDED` (409); `PRODUCT_ALREADY_STOCKED`, `EXPENSE_DELETED` (409); `PAYMENTS_DO_NOT_BALANCE`, `DISCOUNT_EXCEEDS_SUBTOTAL`, `SALE_BACKDATE_WINDOW`, `SALE_IN_FUTURE`, `EXPENSE_IN_FUTURE` and `INVALID_PERIOD` (422). Framework-level failures use fixed codes: `VALIDATION_ERROR` (422, with `details` = list of `{loc, msg, type}`), `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `UNAUTHORIZED`, `FORBIDDEN`, `CONFLICT`, `RATE_LIMITED`, `SERVICE_UNAVAILABLE`, `HTTP_ERROR` (other statuses) and `INTERNAL_ERROR` (500).
- Pydantic validation errors are reformatted into the envelope with field-level `details`.
- List *filters* follow the same tenant contract as path ids: `GET /sales?customer_id=` and `GET /products?category_id=` naming another business's row are 404, never an empty list.
- Unhandled exceptions → 500 with a generic message and `request_id`; full details go to logs and Sentry. Stack traces, SQL, and internal identifiers never reach the client (CLAUDE.md rule 25). In production the engine is created with `hide_parameters=True`, so a DBAPI exception in the logs carries the statement but not the bound values (customer names, phone numbers).
- Cross-tenant access → 404, never 403.

## 9. Logging and observability

- Structured JSON logs (`request_id`, `user_id`, `business_id`, route, status, duration_ms). No PII values (phone numbers, names) in log messages; identifiers only.
- Log levels: INFO for requests, WARNING for domain rejections that matter (credit limit, stock), ERROR for unexpected failures.
- Sentry: backend via `sentry-sdk[fastapi]`, initialised only when `SENTRY_DSN` is set (`app/main.py: init_error_reporting`): `send_default_pii=False`, request bodies never sent, `request_id` attached as a tag by the request-ID middleware, unhandled exceptions captured explicitly by the 500 handler. Frontend Sentry is not wired yet (`VITE_SENTRY_DSN` is read by nothing).
- AI calls log model, tokens, cache hits, latency, tool names (not tool outputs).
- Health endpoints: `/health/live` (process up → `{"status":"ok"}`) and `/health/ready` (`{"status":"ready"|"not_ready","checks":{database, migrations, receipt_storage}}`): `database` runs `SELECT 1`; `migrations` compares `alembic_version` with the head shipped in the image (`pending` → 503, so a deploy that skipped `alembic upgrade head` never receives traffic; `unknown` when the scripts are not next to the package); `receipt_storage` reports whether the blob root is writable but never fails readiness. Neither endpoint touches the Anthropic API.
- Log records are one JSON object per line with `timestamp`, `level`, `logger`, `message`, `request_id` when bound, and any `extra` fields. The access line (`logger = app.access`) carries `method`, `path`, `status`, `duration_ms`; uvicorn's own access log is disabled to avoid duplicates.

## 10. Configuration and environment variables

Configuration comes from environment variables loaded by `pydantic-settings`; the app refuses to start if required values are missing. `.env` files are local-only and git-ignored; `.env.example` documents every variable without secrets.

| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | yes | `development` / `test` / `production`; production disables `/docs` and `/openapi.json` |
| `APP_NAME` | no (`SokoWise API`) | OpenAPI title |
| `API_HOST`, `API_PORT` | no (`0.0.0.0`, `8000`) | bind address for the container `CMD`; Railway's `PORT` mapping is decided in Phase 15 |
| `DATABASE_URL` | yes | `postgresql+asyncpg://…` |
| `JWT_SECRET` | yes | ≥ 32 characters; no default anywhere, including tests (each test/CI environment sets its own throwaway value) |
| `JWT_ISSUER`, `JWT_AUDIENCE` | no (unset) | when set, added to and verified on every access token |
| `ACCESS_TOKEN_TTL_MINUTES` | no (15) | 1–60 |
| `REFRESH_TOKEN_TTL_DAYS` | no (30) | 1–90 |
| `CORS_ORIGINS` | yes | comma-separated frontend origins in browser `Origin` form (`scheme://host[:port]`, no trailing slash — whitespace and a trailing slash are stripped on load); also the CSRF Origin allow-list |
| `CORS_ORIGIN_REGEX` | no | regex for origins that cannot be listed (Vercel previews); preview API environment only |
| `COOKIE_DOMAIN` | no | refresh cookie `Domain`; host-only when unset |
| `COOKIE_SECURE` | no (true) | must be true in production (enforced); `false` only for local http |
| `COOKIE_SAMESITE` | no (`lax`) | `lax` / `strict` / `none`; `none` requires `COOKIE_SECURE=true` (enforced) |
| `GOOGLE_CLIENT_ID` | no | OAuth Web client id whose ID tokens are accepted (§5.1); unset → Google sign-in is off |
| `SMS_PROVIDER` | no (`none`) | `none` / `console` (development only, refused in production) / `africastalking` |
| `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY`, `AFRICASTALKING_SENDER_ID` | with `africastalking` | Africa's Talking credentials; `sandbox` username for the sandbox |
| `RATE_LIMIT_PASSWORD_RESET_PER_MINUTE` | no (5) | per IP, each step |
| `RATE_LIMIT_PASSWORD_RESET_PER_PHONE_PER_MINUTE` | no (3) | SMS requests per phone |
| `RATE_LIMIT_PASSWORD_RESET_CONFIRM_PER_PHONE_PER_MINUTE` | no (10) | code attempts per phone |
| `PLATFORM_ADMIN_PHONES` | no | comma-separated phones (any accepted form) allowed to open the operator dashboard `/admin`; empty → nobody (§5.4) |
| `PLATFORM_ADMIN_EMAILS` | no | same, by email (lower-cased); a user matches on phone or email |
| `ANTHROPIC_API_KEY` | yes (AI) | server-side only |
| `AI_MODEL` | no (`claude-opus-5`) | |
| `AI_DAILY_MESSAGE_LIMIT` | no (10) | per-business user messages per day; operator-controlled |
| `AI_MONTHLY_MESSAGE_LIMIT` | no (100) | per-business user messages per calendar month; operator-controlled |
| `AI_MONTHLY_BUDGET_USD` | no | global hard cap (not enforced yet — see ROADMAP Phase 9) |
| `AI_MAX_OUTPUT_TOKENS` | no (2000) | per-answer `max_tokens`; the only length bound |
| `AI_THINKING` | no (`adaptive`) | `adaptive` or `disabled` |
| `AI_REQUEST_TIMEOUT_SECONDS` | no (60) | provider timeout → 503 `AI_TIMEOUT` |
| `AI_MAX_TOOL_ROUNDS` | no (6) | tool rounds per question → 503 `AI_INCOMPLETE` beyond |
| `AI_HISTORY_MESSAGES` | no (20) | conversation window sent to the model |
| `RATE_LIMIT_AI_MESSAGES_PER_MINUTE` | no (10) | per user, in-process burst limit on the ask endpoint |
| `RECEIPT_STORAGE_DIR` | no (`var/receipts`) | local blob root for receipt images; production requires an absolute path on a persistent volume (enforced at start-up) — object storage is the intended long-term backend |
| `RECEIPT_MAX_BYTES` | no (8 MiB) | upload limit; larger → 413 `RECEIPT_TOO_LARGE` |
| `RECEIPT_MAX_PIXELS` | no (25,000,000) | decompression-bomb bound |
| `RECEIPT_MIN_SIDE_PX` | no (200) | smaller images are refused as unreadable |
| `SENTRY_DSN` | prod | error reporting; unset → disabled |
| `FORWARDED_ALLOW_IPS` | prod (Railway) | read by uvicorn, not the app: `*` behind the platform proxy so `X-Forwarded-For` is trusted; unset where the port is published directly |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | no (5, 5) | connections per process |
| `DB_STATEMENT_TIMEOUT_MS` | no (30000) | server-side `statement_timeout` on every pooled connection |
| `LOG_LEVEL` | no (INFO) | |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | no (5) | per IP and per identifier |
| `RATE_LIMIT_REGISTER_PER_MINUTE` | no (5) | per IP |
| `RATE_LIMIT_REFRESH_PER_MINUTE` | no (30) | per IP (shops share an address) |
| `RATE_LIMIT_PASSWORD_CHANGE_PER_MINUTE` | no (5) | per user |
| Frontend: `VITE_API_BASE_URL` | prod/preview | API origin; empty in local development (Vite proxies `/api`, keeping the refresh cookie same-origin) |
| Frontend: `VITE_SENTRY_DSN` | prod | |

## 11. Database architecture

- PostgreSQL 16+. One database, one schema (`public`) in MVP.
- Conventions and constraints per DATA_MAPPING §2 and §6.
- Migrations: Alembic (`backend/alembic/`, async env), one migration per logical change, reviewed, reversible where practical. `alembic.ini` holds no URL; `env.py` reads `DATABASE_URL` via settings unless a caller sets `sqlalchemy.url` (tests). Commands run from `backend/`: `uv run alembic upgrade head`, `uv run alembic downgrade -1`, `uv run alembic revision --autogenerate -m "..."`, `uv run alembic check`. Autogenerate output is always hand-reviewed: expression indexes render as `sa.literal_column(...)`, mixin columns need `DateTime(timezone=True)` explicitly, and the generated banner comments are removed. CI runs `alembic upgrade head` on a fresh database and `alembic check` for drift; the test suite also asserts zero drift and a `downgrade base → upgrade head` round trip.
- Naming convention (`app/db/base.py`): `pk_<table>`, `fk_<table>_<cols>_<referred>`, `uq_<table>_<cols>`, `ck_<table>_<name>`, `ix_<table>_<cols>`. Enum columns are `VARCHAR` + named CHECK (`ck_<table>_<column>`), never native Postgres enums.
- Mixins: `UUIDPrimaryKeyMixin` (uuid4 app-side), `CreatedAtMixin`, `TimestampMixin` (`updated_at` refreshed by SQLAlchemy `onupdate`); all timestamps `TIMESTAMPTZ`.
- Indexes: every FK, `(business_id, <time column>)` on transactional tables, partial unique indexes for soft-deleted uniqueness.
- Backups: Railway daily snapshots plus a weekly `pg_dump` to object storage — **not configured yet**; the procedure, the restore steps and the cache verification after a restore are in `docs/OPERATIONS.md` §2.
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

SQLite is not used for tests: NUMERIC semantics, partial indexes and `FOR UPDATE` differ. Database tests live in `backend/tests/db/`, carry the `db` marker, and run against the PostgreSQL named by `TEST_DATABASE_URL` (skipped with a visible reason when unset; CI always sets it). The session fixture runs `alembic upgrade head`; each test runs inside an outer transaction that is rolled back (`join_transaction_mode="create_savepoint"`). Async tests use the `anyio` pytest plugin that ships with Starlette's dependencies; Alembic commands invoked from async tests run in a worker thread because Alembic drives its own event loop. API tests (`api` / `api_factory` fixtures) send requests through httpx's ASGI transport in the test's event loop, with `get_session` overridden to the test's own session, so a test can call endpoints and then inspect or edit rows in the same rolled-back transaction; `api_factory(**settings)` builds an app with overridden settings (low rate limits, cookie modes). Because the app shares the session, a test reading rows the app bulk-updated must query with `populate_existing=True`. Tests that need real concurrency (two refreshes racing, two owners stepping down at once) commit through separate connections and delete their rows afterwards. The `tenants` fixture provides two unrelated businesses, each with a logged-in owner and staff member, for role-matrix and isolation tests; `tests/db/isolation.py` holds the reusable tenant-isolation check (§5.4).

Definition of done for a feature: tests for happy path, validation failure, permission denial, and cross-tenant access.

## 13. Deployment architecture

- **Frontend:** Vercel, static build, preview deployments per PR, production from `main`. `frontend/vercel.json` rewrites non-`/api/` paths to `index.html` (client-side routing on refresh/deep links) and sets the security headers.
- **Backend:** Railway service from `backend/Dockerfile` (multi-stage, non-root user, one `uvicorn` worker per container — scale with replicas; see §5.2 for what that means for the in-memory rate limiter). `backend/railway.toml` declares the release step (`preDeployCommand = "alembic upgrade head"`) and the readiness health check; `/health/ready` refuses traffic while migrations are pending. Production start-up guards, the `FORWARDED_ALLOW_IPS` requirement and the persistent volume for receipt images are in `docs/OPERATIONS.md`.
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
