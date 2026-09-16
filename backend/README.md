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
- `GET /health/ready` — 200 when `SELECT 1` succeeds on the database, otherwise 503

Authentication (`/api/v1/auth`, docs/ARCHITECTURE.md §5):

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /register` | — | create user + business + OWNER membership; returns a session |
| `POST /login` | — | phone-or-email + password; returns a session |
| `POST /refresh` | refresh cookie + `X-Requested-With: sokowise` | rotate the refresh token, new access token |
| `POST /logout` | refresh cookie + `X-Requested-With: sokowise` | revoke this device's session (204) |
| `POST /logout-all` | bearer | revoke every session of the user (204) |
| `POST /change-password` | bearer | set a new password; clears `must_change_password`; replaces all sessions |
| `GET /me` | bearer | the caller's user, business and role |

Business and members (OWNER-only, `Authorization: Bearer …`; docs/ARCHITECTURE.md §5.3):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/business` | profile + settings |
| `PATCH /api/v1/business` | update name, type, phone, address, timezone, settings (audited) |
| `GET /api/v1/users` | members of the business |
| `POST /api/v1/users` | create a STAFF user (must change password at first login) |
| `GET /api/v1/users/{user_id}` | one member |
| `PATCH /api/v1/users/{user_id}` | change `role` / `is_active`; the last active owner is protected (409 `LAST_OWNER`) |
| `POST /api/v1/users/{user_id}/reset-password` | set a STAFF member's temporary password (204) |

Catalogue (members read, OWNER writes; docs/ARCHITECTURE.md §5.6):

| Endpoint | Purpose |
|---|---|
| `GET/POST /api/v1/categories`, `GET/PATCH/DELETE /api/v1/categories/{id}` | per-business labels; delete only while unused |
| `GET /api/v1/products?q=&category_id=&include_archived=&limit=` | list / prefix search on name, SKU, barcode |
| `POST /api/v1/products` | create; optional `opening_stock` + `opening_unit_cost` write the INITIAL movement atomically |
| `GET/PATCH /api/v1/products/{id}` | read; update fields, reprice (audited), archive with `{"is_active": false}` |

Customers (members read and create; docs/ARCHITECTURE.md §5.7):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/customers?q=&include_archived=&limit=` | list; `q` matches part of the name or a phone in any local form |
| `POST /api/v1/customers` | create (name, optional phone/notes/credit_limit); duplicate phone in the business → 409 |
| `GET /api/v1/customers/{id}` | one customer, with the read-only ledger `balance` |

Customer accounts (docs/ARCHITECTURE.md §5.8):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/customers/{id}/ledger?limit=` | balance, credit limit and entries (newest first) — members |
| `POST /api/v1/customers/{id}/repayments` | record CASH/MPESA repayment; 409 above the balance unless `allow_overpayment` — members |
| `POST /api/v1/customers/{id}/adjustments` | INCREASE/DECREASE with a reason; never below zero — OWNER |
| `GET /api/v1/debtors?sort=balance\|age&limit=` | customers who owe, with oldest unpaid charge (FIFO) — members |

Repayments and adjustments accept an optional `Idempotency-Key: <uuid>` header: a retry with the same
key and body returns the original entry (200); a different body is a 409.

Sales (docs/ARCHITECTURE.md §5.9):

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/sales` (+ `Idempotency-Key: <uuid>`) | lines, tender lines (CASH/MPESA/CREDIT, must sum to the total), optional customer, discount, note, OWNER-only `sold_at` — members |
| `GET /api/v1/sales?date_from=&date_to=&customer_id=&limit=` | newest first; STAFF see only their own sales from today — members |
| `GET /api/v1/sales/{id}` | one sale with item snapshots and tenders |
| `POST /api/v1/sales/{id}/void` | reason required; reverses stock and credit, audited — OWNER |

Inventory (docs/ARCHITECTURE.md §5.10):

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/inventory/restock` | stock in with unit cost, optional supplier/reason, optional `update_cost_price` — OWNER, or STAFF if `staff_can_restock` |
| `POST /api/v1/inventory/adjust` | signed correction with a reason; never below zero — OWNER |
| `POST /api/v1/inventory/initial` | opening stock for a product with no movements — OWNER |
| `GET /api/v1/inventory/movements?product_id=&movement_type=&date_from=&date_to=&limit=` | history, newest first by posting order — members |
| `GET /api/v1/inventory/low-stock` | active tracked products at/below their threshold — members |
| `POST /api/v1/inventory/recompute` (`{"apply": false}`) | compare the stock cache with the ledger; `apply: true` repairs it — OWNER |

Analytics (OWNER-only; docs/ARCHITECTURE.md §5.11). Periods: `period=today|yesterday|this_week|this_month`
or `period=custom&date_from=&date_to=` (local calendar days in the business timezone):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/analytics/summary` | sales count, revenue, discounts, COGS, missing-cost counts, gross/net profit, tender split, cash collected by method, receivables |
| `GET /api/v1/analytics/timeseries?granularity=day\|week\|month` | the same per bucket |
| `GET /api/v1/analytics/products?sort=quantity\|revenue\|profit&limit=` | product performance (archived products included) |
| `GET /api/v1/analytics/slow-products?days=30` | tracked products in stock with no sale in `days` |
| `GET /api/v1/analytics/categories` | revenue / COGS / profit by category (null = uncategorised) |

`uv run --env-file ../.env python scripts/recompute_caches.py [--apply]` checks (or repairs) every business's stock cache.

Expenses (OWNER-only; docs/ARCHITECTURE.md §5.12):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/expenses?date_from=&date_to=&category=&payment_method=&include_deleted=&limit=` | newest first; local calendar days |
| `POST /api/v1/expenses` | amount, category (free text, upper-cased), CASH/MPESA, optional reference/note/incurred_at |
| `GET/PATCH/DELETE /api/v1/expenses/{id}` | detail; edit (audited); soft delete (audited) |
| `GET /api/v1/expenses/categories` | suggested categories plus the ones this business has used |
| `GET /api/v1/expenses/export.csv` | streamed CSV with the listing's filters |
| `GET /api/v1/analytics/expenses` | period total, count, by category, by method |

The financial overview is `GET /api/v1/analytics/summary`: revenue, cash collected, receivables, COGS,
gross profit, expenses and net profit (= gross profit − expenses), all in the business timezone.

Money and quantities are decimal strings in JSON (`"150.00"`, `"12.500"`).

A session response carries the access token (send it as `Authorization: Bearer …`) and sets the
`sokowise_refresh` HttpOnly cookie; the refresh token is never in the body. `JWT_SECRET` (≥ 32
characters) is required; with `COOKIE_SECURE=false` the cookie works over plain http locally.

## Database

```bash
uv run --env-file ../.env alembic upgrade head        # apply migrations
uv run --env-file ../.env alembic downgrade -1        # step back one revision
uv run --env-file ../.env alembic revision --autogenerate -m "describe change"
uv run --env-file ../.env alembic check               # fail if models drifted from migrations
```

Review every autogenerated migration by hand before committing it (docs/ARCHITECTURE.md §11).

## Checks

```bash
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # types
uv run pytest                # tests
```

Database tests (`tests/db/`) need `TEST_DATABASE_URL` pointing at a PostgreSQL 16 database the
suite may migrate up and down (Compose creates `<POSTGRES_DB>_test` on first start):

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://sokowise:sokowise@localhost:5432/sokowise_test
uv run pytest
```

Without it the database tests are skipped and pytest says so.

## Layout

```
app/
├── main.py            application factory (create_app) and the `app` object uvicorn serves
├── core/              config (pydantic-settings), logging, error envelope, passwords (Argon2id),
│                      tokens (JWT + opaque refresh), rate limiter, request context dataclasses
├── db/                declarative base, naming convention, async engine, session dependency,
│                      `transaction()` helper used by services
├── models/            SQLAlchemy 2.x models, one module per aggregate (16 tables)
├── schemas/           Pydantic request/response models (auth), identifier normalisation
├── repositories/      queries (users/memberships, businesses, refresh tokens, audit logs,
│                      categories, products, inventory movements, customers, credit, sales,
│                      expenses)
├── services/          transactions and rules (auth, business, members, audit, categories,
│                      products, inventory operations, customers, credit ledger, sales, money,
│                      expenses)
├── middleware/        request-ID middleware and access log
└── api/               health router, deps.py (auth chain, role guards, CSRF, rate limits),
                       v1/ (routers mounted at /api/v1: auth, business, users, categories,
                       products, customers, debtors, sales, inventory, analytics, expenses)
├── analytics/         read-only SQL aggregates and period helpers (business timezone)
alembic/               migrations (async env; two revisions); alembic.ini holds no URL
scripts/               management commands (recompute_caches.py)
tests/                 pytest; tests/db/ needs PostgreSQL (API tests use the `api`/`tenants` fixtures;
                       register tenant-scoped endpoints in tests/db/test_tenant_isolation.py)
```

Settings are read from environment variables (see `../.env.example`). The app refuses to start
when a required value is missing.
