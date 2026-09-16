# SokoWise — Roadmap

| Field | Value |
|---|---|
| Status | Draft v0.2 — Phase 0 (architecture review fixes applied) |
| Last updated | 2026-09-16 |
| Related docs | [PRD.md](PRD.md) · [DATA_MAPPING.md](DATA_MAPPING.md) · [ARCHITECTURE.md](ARCHITECTURE.md) |

Phases are sequential. A phase starts only when its dependencies are complete and ends only when every completion criterion is verified (not assumed). Do not pull later-phase work forward "while you're in there".

Legend: ☐ not started · ◐ in progress · ☑ complete

---

## Phase 0 — Product discovery and architecture ☑
**Objective:** establish the engineering source of truth before writing application code.

**Tasks**
- Inspect the existing repository.
- Write PRD, DATA_MAPPING, ARCHITECTURE, ROADMAP.
- Establish CLAUDE.md and README.md; make `.gitignore` ignore `.env*`; document variables in `.env.example`.
- Review for contradictions, scope size, ambiguity, risks.

**Dependencies:** none.

**Completion criteria**
- All four docs exist and cross-reference each other consistently.
- Open questions are listed (PRD §19, DATA_MAPPING §9, and the Phase 0 report).
- No application code, models, or dependencies were added.

---

## Phase 1 — Backend project foundation ☑ (2026-09-16; `docker compose up` still unverified locally because the development account lacks Docker socket access)
**Objective:** a runnable, empty FastAPI service with configuration, logging, error envelope, health checks, tooling and CI, plus the repository restructure.

**Tasks**
- Move the Vite scaffold from the repo root into `frontend/` (git `mv`; keep history). Update root README.
- Create `backend/` with `pyproject.toml` (uv), `app/main.py`, `app/core/{config,logging,errors}.py`, `/health/live`, `/health/ready` (ready returns 503 until Phase 2 wires the DB).
- Global exception handlers producing the error envelope (ARCHITECTURE §8); request-id middleware; CORS from settings.
- `ruff`, `mypy`, `pytest` configured; one smoke test for `/health/live`.
- `docker-compose.yml` with PostgreSQL 16 for local dev; `backend/Dockerfile` (multi-stage, non-root).
- GitHub Actions: backend lint + test; frontend lint + build.

**Dependencies:** Phase 0.

**Completion criteria**
- `uv run pytest` passes locally and in CI.
- `docker compose up` starts Postgres; `uvicorn app.main:app` serves `/health/live` → 200.
- No secrets in the repo; app fails fast on missing required env vars.

---

## Phase 2 — Database and migrations ◐ (implemented 2026-09-16; verified against local PostgreSQL 16.15; CI run and Compose start pending)
**Objective:** SQLAlchemy models and Alembic migrations for the 16 MVP tables in DATA_MAPPING.

**Tasks**
- Async engine/session factory; `Base` with UUID PK and timestamp mixins.
- Models per DATA_MAPPING §3 including CHECK constraints, partial unique indexes, composite tenant FKs.
- Alembic initial migration (hand-reviewed), `alembic check` in CI.
- Test harness: session fixture with per-test rollback against Postgres; factory helpers for business/user/product/customer.
- `scripts/seed.py` for the demo/fixture business — **deferred to Phase 3**: a seed needs a hashed owner password, which does not exist before authentication.
- `/health/ready` checks DB connectivity.

**Dependencies:** Phase 1.

**Completion criteria**
- `alembic upgrade head` on an empty DB succeeds; `alembic downgrade -1` works; autogenerate shows no drift.
- Constraint tests: cross-business composite FK insert fails; negative amounts rejected; enum CHECKs enforced.
- DATA_MAPPING updated with any deviation discovered while modelling.

---

## Phase 3 — Authentication ☐
**Objective:** secure registration, login, refresh, logout.

**Tasks**
- Argon2id hashing (`argon2-cffi`) with rehash-on-login.
- JWT access tokens (PyJWT); opaque rotating refresh tokens stored hashed; family revocation on reuse.
- Endpoints: `POST /auth/register` (creates user + business + OWNER membership atomically), `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`, `POST /auth/change-password`, `GET /auth/me`.
- Dependencies: `get_current_user`, `get_business_context`, `require_role`.
- Rate limiting for login/register; decide library vs in-house and record the reason; document the per-process limitation (ARCHITECTURE §5.2).
- Measure Argon2id cost on the target instance starting from m=19 MiB, t=2, p=1; record the chosen parameters.
- `must_change_password` gate: forced change at first login for owner-created users.
- Decide cookie/domain strategy (ARCHITECTURE §5.1) and document it.
- **Deferred decisions to make in this phase:** Vercel preview authentication (cross-site cookies) and shared-device session handling (PRD A8). Both are listed in ARCHITECTURE §5.1; neither is decided yet.

**Dependencies:** Phase 2.

**Completion criteria**
- Tests: register→login→refresh→logout flow; refresh reuse revokes family; deactivated user and inactive business rejected; wrong password rate-limited; tokens for business A rejected by membership check when membership is inactive; role is taken from the membership, not the token; `must_change_password` blocks other endpoints.
- No password or token material appears in logs.

---

## Phase 4 — Business and user management ☐
**Objective:** manage business settings and staff.

**Tasks**
- `GET/PATCH /business` (settings validated by Pydantic model).
- `GET/POST/PATCH /users` for OWNER: create STAFF (phone, name, initial password), deactivate, reset password.
- Last-owner protection.
- Audit entries for settings and user changes.
- **Generic tenant-isolation test helper**: a parametrised pytest fixture that, given an endpoint and a factory for its resource, creates the resource in Business B and asserts that Business A gets 404 on read, update, delete and list-exclusion. Every tenant-scoped endpoint added in this and later phases must be registered with it; a PR adding an endpoint without registering it is incomplete.

**Dependencies:** Phase 3.

**Completion criteria**
- Role matrix tests for every endpoint; every tenant-scoped endpoint registered with the isolation helper and passing; audit rows written.

---

## Phase 5 — Products and inventory ☐
**Objective:** catalogue and stock ledger.

**Tasks**
- Categories CRUD; products CRUD with archive; search endpoint (name/SKU/barcode prefix). Product creation accepts `opening_stock` + `opening_unit_cost` and writes the `INITIAL` movement atomically (PRD FR-D6); `stock_quantity` is never writable directly.
- Inventory movements: `POST /inventory/restock`, `POST /inventory/adjust`, `POST /inventory/initial`, `GET /inventory/movements?product_id=`.
- `products.stock_quantity` maintained transactionally with row locks.
- Low-stock list endpoint.
- `scripts/recompute_caches.py` to rebuild `stock_quantity` from the ledger.
- Audit: price change, restock, adjustment.

**Dependencies:** Phase 4.

**Completion criteria**
- Concurrency test: two simultaneous restocks/adjustments produce the correct final quantity.
- Recompute script yields identical values to cached column on fixture data.
- Tests: untracked products create no movements and are not stock-validated; `quantity_after` follows commit order for backdated movements.
- Role and isolation tests (registered with the Phase 4 helper).

---

## Phase 6 — Sales and payments ☐
**Objective:** record and void sales with split payments, including the customer records a credit sale needs.

**Tasks**
- `POST /sales` (idempotency key, lines, payments, optional customer, optional backdate for OWNER); `GET /sales`, `GET /sales/{id}`, `POST /sales/{id}/void`.
- Single-transaction creation per DATA_MAPPING §6; stock validation; price override recording; discount validation; BR-1 enforcement.
- Customers: create, get, list, search (name/phone) — the minimum a credit sale needs. Archive, PII scrub, repayments, adjustments, ledger view and debtors move to Phase 7.
- CREDIT payment lines create `CHARGE` ledger entries and update `customers.balance` inside the sale transaction; void writes the `REVERSAL`. The rest of the credit module (repayments, adjustments, limits) is Phase 7.
- Sale-level discount allocated to lines (`sale_items.discount_allocated`, BR-14) with largest-remainder rounding.
- Idempotency: store `idempotency_hash`; same key + same payload → 200 with the original; same key + different payload → 409.
- Void reverses stock and credit; audit row.
- STAFF sees own, same-day sales only.

**Dependencies:** Phase 5.

**Completion criteria**
- Tests: cash sale; M-Pesa sale with reference; split payment; credit sale requires customer; insufficient stock rejected; idempotent retry returns same sale with no duplicate movements; same key with different payload → 409; void restores stock and balance; void of a sale whose product was archived afterwards still writes reversals; Σ `discount_allocated` = `discount_amount` on awkward splits (e.g. 100 across three lines); STAFF cannot void or backdate.
- Money arithmetic tests for rounding (BR-9).

---

## Phase 7 — Customers and credit ☐
**Objective:** complete the customer module and the credit ledger.

**Tasks**
- Customers: update, archive, PII scrub endpoint (create/get/list/search shipped in Phase 6).
- `POST /customers/{id}/repayments`, `POST /customers/{id}/adjustments` (OWNER), `GET /customers/{id}/ledger`.
- Debtors list with oldest-charge age (FIFO).
- Credit-limit rule (FR-G5: STAFF blocked, OWNER warned).
- STAFF can view customer balance and ledger (PRD §16); OWNER-only for adjustments.
- `recompute_caches` extended to `customers.balance`.

**Dependencies:** Phase 6.

**Completion criteria**
- Ledger tests: charge → partial repayment → void → balance correct; adjustment requires reason; limit enforcement by role; isolation tests.

---

## Phase 8 — Expenses and analytics ☐
**Objective:** expenses and the read-only analytics used by dashboard and AI.

**Tasks**
- Expenses CRUD (soft delete, audit).
- `analytics/` query functions and endpoints: period summary with the exact FR-I1 fields (`revenue` accrual, `cash_collected` by method including credit repayments, `tender_split`, `cogs`, `lines_missing_cost`, `products_missing_cost`, gross/net profit), top products (qty / revenue / profit using `discount_allocated`), slow products, low stock, debtors summary, expenses by category. Period boundaries computed in business timezone.
- CSV export endpoints (sales, customers, expenses).

**Dependencies:** Phase 7.

**Completion criteria**
- Fixture-based tests with hand-computed expected values for every analytics function, including: a day-boundary case around midnight Nairobi time; a voided-sale exclusion case; a credit sale that raises revenue but not cash collected, followed by a repayment that raises cash collected but not revenue; a product with unknown cost reported in `lines_missing_cost`; Σ product profit = period gross profit on a discounted sale.
- Query plans checked on the transactional indexes (no seq scans on `sales` for a period query).

---

## Phase 9 — Claude AI integration ☐
**Objective:** the copilot, read-only, tenant-scoped, validated.

**Tasks**
- `ai/` module: Anthropic Python SDK client, settings, tool registry with Pydantic strict schemas over Phase 8 analytics, prompt builder with cached stable prefix, guardrails, quota check, persistence to `ai_conversations`/`ai_messages`.
- Endpoints: `POST /ai/conversations`, `GET /ai/conversations`, `GET /ai/conversations/{id}`, `POST /ai/conversations/{id}/messages` (SSE streaming).
- Eval set: fixture questions (English + Swahili), expected numbers, refusal and injection cases; CI runs with recorded tool outputs; nightly live run script.
- Cost logging and global monthly cap; per-business quotas from `AI_DAILY_MESSAGE_LIMIT` / `AI_MONTHLY_MESSAGE_LIMIT` (server-side, not owner-editable).
- **Pricing and cost verification (first task of the phase):** read current model pricing from the Anthropic documentation, run the eval set, measure per-message cost from `usage` (input, output, cache read), and record it in the PR. Set the quotas so a business at quota stays within the PRD §18 target; if the default model cannot meet it, evaluate a cheaper model against the eval set before changing `AI_MODEL`.
- **Cache-hit verification:** assert `usage.cache_read_input_tokens > 0` on the second request with the same stable prefix; treat 0 as a bug (volatile content inside the cached prefix or a prefix below the minimum cacheable size).
- `search_customers` tool and the `get_debtors → customer_id → get_customer_ledger` path.
- Tool executions run in a read-only transaction (`SET TRANSACTION READ ONLY`); conversation persistence uses the normal session.

**Dependencies:** Phase 8.

**Completion criteria**
- The six PRD §20 questions answered correctly on the fixture business in both languages (live eval run recorded in the PR).
- Tests: unknown tool rejected; tool cannot be called with another business's id (no such parameter exists — asserted at schema level); quota exceeded → 429 and owners cannot change the quota through any endpoint; API outage → graceful error; `max_tokens`/`refusal` stop reasons produce the terminal SSE notice; guardrail failure flags the stored message; a tool that attempts a write fails inside the read-only transaction.
- Measured cost per message and cache-hit evidence recorded in the phase PR; quotas adjusted if needed.
- No `ANTHROPIC_API_KEY` in frontend or logs.

---

## Phase 10 — Receipt intelligence ☐ (stretch)
**Objective:** turn M-Pesa messages and receipt photos into confirmable drafts.

**Tasks**
- `POST /ai/extract` accepting text or image (size/type limits), returning a structured draft via `output_config.format`.
- No writes; the frontend submits the confirmed draft to normal endpoints.
- Eval set of sample messages/receipts (synthetic; no real customer data in the repo).

**Dependencies:** Phase 9. May be deferred past Phase 12 if the schedule slips; it must not block the pilot.

**Completion criteria**
- ≥ 90% field accuracy on the synthetic set; malformed inputs rejected; no persistence of uploaded images beyond request handling unless a retention decision is documented.

---

## Phase 11 — Backend testing and security hardening ☐
**Objective:** confidence before UI work.

**Tasks**
- Audit that every tenant-scoped endpoint is registered with the Phase 4 isolation helper (generate the list from the router table and diff it against the registrations); fix any gap.
- Permission matrix test generated from PRD §16.
- Security review: headers, CORS, cookie flags, rate limits, error leakage, dependency audit, secret scanning in CI.
- Evaluate Postgres RLS as a second layer; implement if cost is low.
- Load test sale creation and analytics with pilot-scale data (e.g. 50 businesses × 10k sales).
- Backup/restore rehearsal documented.

**Dependencies:** Phases 3–9.

**Completion criteria**
- All matrices green; p95 targets in PRD NFR-3 met on the load test; audit findings resolved or explicitly accepted in a `docs/SECURITY_NOTES.md`.

---

## Phase 12 — Frontend implementation ☐
**Objective:** the mobile-first app.

**Tasks**
- Tailwind + shadcn/ui setup, router, providers, API client with token refresh, OpenAPI-generated types.
- Screens: auth, onboarding checklist, Sell (default), Sales list/detail/void, Products, Inventory (restock/adjust/low stock), Customers (ledger, repayment), Expenses, Dashboard/analytics, Copilot chat (streaming), Settings/users, Audit log (simple list, OWNER).
- Money and date formatting for KES / Nairobi time.
- PWA manifest.

**Dependencies:** Phase 11 (backend stable). UI design decisions are made in this phase.

**Completion criteria**
- Each screen works against the local backend; Vitest coverage for forms and formatting; bundle budget (NFR-2) met; Lighthouse mobile ≥ 80 on Sell.

---

## Phase 13 — Frontend/backend integration ☐
**Objective:** end-to-end behaviour against staging.

**Tasks**
- Staging environment on Railway/Vercel; CORS/cookie configuration for real domains.
- Error-state UX: offline banner, pending sale state, retry with idempotency key.
- Sentry on both sides.

**Dependencies:** Phase 12.

**Completion criteria**
- All PRD §14 journeys completed manually on a mid-range Android phone over mobile data; no console errors; error envelope rendered correctly.

---

## Phase 14 — End-to-end testing ☐
**Objective:** automated coverage of the core journeys.

**Tasks**
- Playwright suites for J1–J6 against a seeded backend in CI.
- Visual regression is out of scope.

**Dependencies:** Phase 13.

**Completion criteria**
- E2E suite passes in CI on every PR in under 10 minutes.

---

## Phase 15 — Docker and production infrastructure ☐
**Objective:** reproducible production builds and data safety.

**Tasks**
- Finalise Dockerfile (pinned base image, healthcheck), release-step migrations, worker count.
- Backups: Railway snapshots + weekly `pg_dump` to object storage; restore rehearsal.
- Production env var checklist; secret rotation procedure.

**Dependencies:** Phase 14.

**Completion criteria**
- Fresh production deploy from a clean database succeeds; restore from backup verified; runbook in `docs/RUNBOOK.md`.

---

## Phase 16 — Deployment and monitoring ☐
**Objective:** production live with observability.

**Tasks**
- CI/CD to production from `main` with manual approval gate.
- Uptime check on `/health/ready`; Sentry alerts; AI cost dashboard/alert.
- Privacy notice and terms published; DPA registration status documented.

**Dependencies:** Phase 15.

**Completion criteria**
- Production URL serves the app; alerts verified by a synthetic failure; PRD acceptance criteria §17 items 7–10 met.

---

## Phase 17 — Real-user pilot ☐
**Objective:** validate PRD assumptions A1–A9 with 10–20 businesses over 8 weeks.

**Tasks**
- Recruit businesses across the persona types; onboarding script; weekly check-ins.
- Instrument the success metrics (PRD §18).
- Collect the real top-10 copilot questions; feed into the eval set.
- Weekly triage of bugs and assumption findings; update PRD.

**Dependencies:** Phase 16.

**Completion criteria**
- Metrics report against PRD §18; each assumption marked validated / refuted / unclear with evidence; V2 scope proposal written.
