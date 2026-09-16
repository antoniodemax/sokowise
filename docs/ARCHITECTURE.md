# SokoWise — Architecture

| Field | Value |
|---|---|
| Status | Draft v0.7 — Phase 7 credit ledger implemented (§5.8); sales pending |
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

**Current state (after Phase 7):** the Vite scaffold lives in `frontend/` (plus a dev proxy for `/api`, §5.1). `backend/` holds the application factory, settings, JSON logging, the error envelope, the request-ID middleware, the health endpoints, `app/db/` (base, engine, session dependency, `transaction()` helper), `app/models/` (the 16 MVP tables), `alembic/` (one migration, `b7a497cc6a27`), and the authentication slice: `app/core/passwords.py`, `app/core/tokens.py`, `app/core/ratelimit.py`, `app/core/context.py` (`BusinessContext`, `ClientInfo`), `app/schemas/auth.py` + `identifiers.py`, `app/repositories/{users,businesses,refresh_tokens}.py`, `app/services/auth.py`, `app/api/deps.py` and `app/api/v1/auth.py` (mounted at `/api/v1/auth`); and the Phase 4 tenant core: `app/schemas/{business,members}.py`, `app/repositories/audit_logs.py` (+ business-scoped member queries in `users.py`), `app/services/{audit,business,members}.py`, `app/api/v1/{business,users}.py`; and the Phase 5 catalogue: `app/schemas/catalog.py`, `app/repositories/{categories,products,inventory}.py`, `app/services/{categories,products,inventory}.py`, `app/api/v1/{categories,products}.py`; customers: `app/schemas/customers.py`, `app/repositories/customers.py`, `app/services/customers.py`, `app/api/v1/customers.py`; the credit ledger: `app/schemas/credit.py`, `app/repositories/credit.py`, `app/services/credit.py`, ledger routes in `api/v1/customers.py` and `api/v1/debtors.py`; migration `e73124c3e89a` (idempotency columns on `credit_transactions`). `analytics/`, `ai/` and `integrations/` do not exist yet. Middleware lives in `app/middleware/`.

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

### 5.2 Passwords
- Argon2id via `argon2-cffi`, parameters in `app/core/passwords.py` (the only module that knows about Argon2): **m = 19 MiB, t = 2, p = 1**, 32-byte hash, 16-byte salt — the OWASP minimum the architecture starts from. Measured at ~28 ms per verification on a development laptop (i7-10610U); the target of roughly 100–250 ms on the deployed Railway instance has not been measured yet (no Railway environment exists), so raise `t` (then `m`) there before the pilot, staying within memory under concurrent logins (512 MB / 1–2 vCPU containers). `needs_rehash` + rehash-on-login means changing the constants is enough; old hashes are replaced as users log in. Passwords are capped at 128 characters so a login cannot make the server hash megabytes.
- Verification is constant-time inside the library. A login for an unknown identifier still verifies the password against a dummy hash so timing does not reveal whether the account exists, and unknown identifier, wrong password and deactivated user all produce the same 401 `INVALID_CREDENTIALS`.
- Minimum 8 characters; a small deny-list of common passwords (`app/schemas/auth.py`); no composition rules. The change-password endpoint requires the current password and rejects an unchanged one.
- **Rate limiting** is an in-house sliding-window limiter (`app/core/ratelimit.py`, ~50 lines) rather than `slowapi`: it needs no dependency, keys on whatever the endpoint chooses, and returns the project's error envelope (429 `RATE_LIMITED` + `Retry-After`). Keys: login per IP *and* per identifier (counted whether or not the account exists, so a 429 says nothing about existence), register per IP, refresh per IP, change-password per user. Rejected attempts are not counted, so a blocked client is not blocked longer by retrying. **Limitation:** counters live in process memory, and the backend runs 2–4 uvicorn workers, so the effective limit is up to N times the configured value and resets on deploy. This is accepted for the pilot; a shared store (database table or Redis) is the upgrade path if abuse appears. The Argon2 cost is the second line of defence. Behind Railway's proxy uvicorn must run with `--proxy-headers`/`--forwarded-allow-ips` so the per-IP key is the client's address (Phase 15).

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
- Domain exceptions (`UnauthorizedError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError`, `RateLimitedError`, and later `ValidationError`, `InsufficientStockError`, `CreditLimitExceededError`, `AIUnavailableError`) subclass `app.core.errors.AppError` (which carries `status_code`, `code`, a user-safe `message`, optional `details` and optional response `headers` such as `WWW-Authenticate` or `Retry-After`) and are mapped to HTTP by the handlers in that module. A subclass's default `code` can be overridden per instance for a more specific stable code: authentication uses `INVALID_CREDENTIALS`, `INVALID_REFRESH_TOKEN` (401), `PASSWORD_CHANGE_REQUIRED`, `BUSINESS_INACTIVE`, `MEMBERSHIP_INACTIVE`, `CSRF_REJECTED` (403), `INVALID_CURRENT_PASSWORD` (400), `PRODUCT_UNTRACKED` (422), `ACCOUNT_EXISTS`, `LAST_OWNER`, `CATEGORY_EXISTS`, `CATEGORY_IN_USE`, `PRODUCT_NAME_EXISTS`, `SKU_EXISTS`, `BARCODE_EXISTS`, `PRODUCT_HAS_STOCK`, `INSUFFICIENT_STOCK`, `CUSTOMER_PHONE_EXISTS`, `REPAYMENT_EXCEEDS_BALANCE`, `ADJUSTMENT_EXCEEDS_BALANCE`, `BALANCE_WOULD_BE_NEGATIVE`, `CREDIT_LIMIT_EXCEEDED` and `IDEMPOTENCY_CONFLICT` (409). Framework-level failures use fixed codes: `VALIDATION_ERROR` (422, with `details` = list of `{loc, msg, type}`), `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `UNAUTHORIZED`, `FORBIDDEN`, `CONFLICT`, `RATE_LIMITED`, `SERVICE_UNAVAILABLE`, `HTTP_ERROR` (other statuses) and `INTERNAL_ERROR` (500).
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
| `JWT_SECRET` | yes | ≥ 32 characters; no default anywhere, including tests (each test/CI environment sets its own throwaway value) |
| `JWT_ISSUER`, `JWT_AUDIENCE` | no (unset) | when set, added to and verified on every access token |
| `ACCESS_TOKEN_TTL_MINUTES` | no (15) | 1–60 |
| `REFRESH_TOKEN_TTL_DAYS` | no (30) | 1–90 |
| `CORS_ORIGINS` | yes | comma-separated frontend origins; also the CSRF Origin allow-list |
| `CORS_ORIGIN_REGEX` | no | regex for origins that cannot be listed (Vercel previews); preview API environment only |
| `COOKIE_DOMAIN` | no | refresh cookie `Domain`; host-only when unset |
| `COOKIE_SECURE` | no (true) | must be true in production (enforced); `false` only for local http |
| `COOKIE_SAMESITE` | no (`lax`) | `lax` / `strict` / `none`; `none` requires `COOKIE_SECURE=true` (enforced) |
| `ANTHROPIC_API_KEY` | yes (AI) | server-side only |
| `AI_MODEL` | no (`claude-opus-5`) | |
| `AI_DAILY_MESSAGE_LIMIT` | no (10) | per-business user messages per day; operator-controlled |
| `AI_MONTHLY_MESSAGE_LIMIT` | no (100) | per-business user messages per calendar month; operator-controlled |
| `AI_MONTHLY_BUDGET_USD` | no | global hard cap |
| `SENTRY_DSN` | prod | |
| `LOG_LEVEL` | no (INFO) | |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | no (5) | per IP and per identifier |
| `RATE_LIMIT_REGISTER_PER_MINUTE` | no (5) | per IP |
| `RATE_LIMIT_REFRESH_PER_MINUTE` | no (30) | per IP (shops share an address) |
| `RATE_LIMIT_PASSWORD_CHANGE_PER_MINUTE` | no (5) | per user |
| Frontend: `VITE_API_BASE_URL` | yes | |
| Frontend: `VITE_SENTRY_DSN` | prod | |

## 11. Database architecture

- PostgreSQL 16+. One database, one schema (`public`) in MVP.
- Conventions and constraints per DATA_MAPPING §2 and §6.
- Migrations: Alembic (`backend/alembic/`, async env), one migration per logical change, reviewed, reversible where practical. `alembic.ini` holds no URL; `env.py` reads `DATABASE_URL` via settings unless a caller sets `sqlalchemy.url` (tests). Commands run from `backend/`: `uv run alembic upgrade head`, `uv run alembic downgrade -1`, `uv run alembic revision --autogenerate -m "..."`, `uv run alembic check`. Autogenerate output is always hand-reviewed: expression indexes render as `sa.literal_column(...)`, mixin columns need `DateTime(timezone=True)` explicitly, and the generated banner comments are removed. CI runs `alembic upgrade head` on a fresh database and `alembic check` for drift; the test suite also asserts zero drift and a `downgrade base → upgrade head` round trip.
- Naming convention (`app/db/base.py`): `pk_<table>`, `fk_<table>_<cols>_<referred>`, `uq_<table>_<cols>`, `ck_<table>_<name>`, `ix_<table>_<cols>`. Enum columns are `VARCHAR` + named CHECK (`ck_<table>_<column>`), never native Postgres enums.
- Mixins: `UUIDPrimaryKeyMixin` (uuid4 app-side), `CreatedAtMixin`, `TimestampMixin` (`updated_at` refreshed by SQLAlchemy `onupdate`); all timestamps `TIMESTAMPTZ`.
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

SQLite is not used for tests: NUMERIC semantics, partial indexes and `FOR UPDATE` differ. Database tests live in `backend/tests/db/`, carry the `db` marker, and run against the PostgreSQL named by `TEST_DATABASE_URL` (skipped with a visible reason when unset; CI always sets it). The session fixture runs `alembic upgrade head`; each test runs inside an outer transaction that is rolled back (`join_transaction_mode="create_savepoint"`). Async tests use the `anyio` pytest plugin that ships with Starlette's dependencies; Alembic commands invoked from async tests run in a worker thread because Alembic drives its own event loop. API tests (`api` / `api_factory` fixtures) send requests through httpx's ASGI transport in the test's event loop, with `get_session` overridden to the test's own session, so a test can call endpoints and then inspect or edit rows in the same rolled-back transaction; `api_factory(**settings)` builds an app with overridden settings (low rate limits, cookie modes). Because the app shares the session, a test reading rows the app bulk-updated must query with `populate_existing=True`. Tests that need real concurrency (two refreshes racing, two owners stepping down at once) commit through separate connections and delete their rows afterwards. The `tenants` fixture provides two unrelated businesses, each with a logged-in owner and staff member, for role-matrix and isolation tests; `tests/db/isolation.py` holds the reusable tenant-isolation check (§5.4).

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
