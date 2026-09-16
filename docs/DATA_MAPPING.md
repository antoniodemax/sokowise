# SokoWise — Data Mapping

| Field | Value |
|---|---|
| Status | Draft v0.2 — Phase 0 (architecture review fixes applied) |
| Last updated | 2026-09-16 |
| Related docs | [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) |

This document maps the business entities, decides which are needed for the MVP, and records the constraints that keep the data trustworthy. It is the input to the SQLAlchemy models and Alembic migrations built in ROADMAP Phase 2 — no models exist yet.

---

## 1. Entity decision table

Entities from the Phase 0 brief, with the decision for MVP.

| Entity | MVP? | Decision & reasoning |
|---|---|---|
| businesses | **Yes** | The tenant. Everything hangs off it. |
| users | **Yes** | People who log in. |
| roles | **No table** | Two fixed roles (OWNER, STAFF) as an enum on the membership row. A roles/permissions table is unjustified until roles become configurable. |
| business_memberships | **Yes** | Links users to businesses with a role. Adds one small table now so "user in two businesses" is a data change, not a migration of `users.business_id`. MVP UI still exposes one business per user. |
| refresh_tokens | **Yes** | Required for rotation/revocation (PRD FR-B3). |
| categories | **Yes** | Tiny per-business label table; keeps product filtering and analytics-by-category clean. |
| products | **Yes** | Core. |
| inventory | **No separate table** | On-hand quantity is a column on `products` (`stock_quantity`), maintained from `inventory_movements`. A separate `inventory` table only pays off with multiple locations, which is out of scope. |
| inventory_movements | **Yes** | The stock ledger; source of truth for on-hand quantity and restock costs. |
| sales | **Yes** | Core. |
| sale_items | **Yes** | Core. |
| payments | **Yes** | Payment lines per sale (CASH / MPESA / CREDIT). This is the extension point for M-Pesa. |
| customers | **Yes** | Core for credit. |
| credit_transactions | **Yes** | Customer credit ledger. |
| expenses | **Yes** | Core. |
| suppliers | **Deferred** | Restocks carry an optional free-text `supplier_name`. A suppliers table arrives with purchase records post-MVP. |
| purchases / purchase_items | **Deferred** | A restock is a single-product `inventory_movements` row with cost. Multi-line purchases with a supplier and payment terms are post-MVP; when added, each purchase_item will *generate* a RESTOCK movement, so the ledger design does not change. |
| ai_conversations | **Yes** | Chat history per user. |
| ai_messages | **Yes** | Messages + tool call records + token usage (audit and evals). |
| audit_logs | **Yes** | Attributable financial changes (PRD FR-K1). Lightweight. |
| mpesa_transactions | **Deferred** | Provider-level record for Daraja (checkout request id, receipt number, callback payload). Added with the integration; linked from `payments` and `credit_transactions` via a nullable FK. |
| attachments / receipts | **Deferred** | Phase 10 (receipt intelligence) stores the uploaded image/text and the extraction result. Not designed in detail yet. |

**MVP total: 16 tables.**

## 2. Conventions (apply to every table)

- **Primary keys:** `id UUID` generated application-side (`uuid4`; UUIDv7 may be adopted later for index locality — it is a drop-in change).
- **Tenant column:** every tenant-owned table has `business_id UUID NOT NULL REFERENCES businesses(id)`, indexed, *including* child tables such as `sale_items`. This lets every repository query filter by `business_id` and enables Postgres row-level security later.
- **Composite tenant FKs (defence in depth):** child rows reference their parent with a composite foreign key `(parent_id, business_id) → parent(id, business_id)`. A `sale_item` therefore cannot point at a sale from another business even if application code is wrong. Parents get a `UNIQUE (id, business_id)` constraint to support this.
- **Timestamps:** `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL` (app-maintained). Stored in UTC. Business-local dates are derived using `businesses.timezone`.
- **Money:** `NUMERIC(14,2)`, non-negative unless stated. Currency is per business (`businesses.currency`, MVP always `KES`); no per-row currency.
- **Quantities:** `NUMERIC(12,3)`, to allow 0.5 kg or 0.25 L.
- **Enums:** stored as `VARCHAR` with a `CHECK` constraint (not Postgres native enums) so that adding a value is a simple migration.
- **Soft delete:** `is_active`/`archived_at` for master data (products, customers, users). Transactional records (sales, movements, ledger entries) are never deleted; sales are voided.
- **Actor columns:** `created_by UUID REFERENCES users(id)` on transactional tables.
- **Naming:** snake_case, plural table names, singular FK names (`customer_id`).

## 3. Entity definitions

### 3.1 businesses
The tenant. One row per shop.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(120) NOT NULL | |
| business_type | VARCHAR(40) NOT NULL | CHECK in (`GENERAL_SHOP`, `BOUTIQUE`, `SALON`, `RESTAURANT`, `ELECTRONICS`, `OTHER`) — used for defaults and analytics only |
| phone | VARCHAR(20) NULL | E.164 |
| address | VARCHAR(255) NULL | |
| currency | CHAR(3) NOT NULL DEFAULT 'KES' | |
| timezone | VARCHAR(64) NOT NULL DEFAULT 'Africa/Nairobi' | IANA name |
| settings | JSONB NOT NULL DEFAULT '{}' | Owner-editable, validated by a Pydantic model; keys: `staff_can_restock` (bool, default false), `sale_backdate_days` (int, default 7), `low_stock_default_threshold` (int, default 5). AI quotas are **not** here: they are server-side configuration (`AI_DAILY_MESSAGE_LIMIT`, `AI_MONTHLY_MESSAGE_LIMIT`, ARCHITECTURE §6.5) so a business cannot raise its own limit. A per-business override, if ever needed, will be an operator-only column, never part of `settings`. |
| is_active | BOOLEAN NOT NULL DEFAULT true | |
| created_at, updated_at | | |

Lifecycle: created during registration in the same transaction as the OWNER membership. Deactivation blocks all logins to the business. No hard delete.

### 3.2 users
A person who can log in. Not tenant-scoped itself; scoped through memberships.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| phone | VARCHAR(20) NOT NULL UNIQUE | E.164, normalised (`+2547…`). Primary login identifier. |
| email | VARCHAR(255) NULL UNIQUE | Optional secondary login identifier, lower-cased |
| full_name | VARCHAR(120) NOT NULL | |
| password_hash | VARCHAR(255) NOT NULL | Argon2id encoded string |
| is_active | BOOLEAN NOT NULL DEFAULT true | Global deactivation |
| must_change_password | BOOLEAN NOT NULL DEFAULT false | Set true when an OWNER creates a STAFF user or resets their password; login succeeds but every endpoint except change-password and logout returns 403 until the user sets a new password |
| last_login_at | TIMESTAMPTZ NULL | |
| created_at, updated_at | | |

Constraint: a user cannot be created without a membership in MVP (enforced in the registration/invite services, not the DB).

### 3.3 business_memberships
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| user_id | UUID NOT NULL FK | |
| role | VARCHAR(20) NOT NULL | CHECK in (`OWNER`, `STAFF`) |
| is_active | BOOLEAN NOT NULL DEFAULT true | Per-business deactivation of a staff member |
| created_at, updated_at | | |

Constraints: `UNIQUE (business_id, user_id)`. Every business must have ≥ 1 active OWNER (service rule: the last owner cannot be demoted or deactivated).

The access token carries the active `business_id`; the backend re-checks the membership exists and is active on every request (see ARCHITECTURE §5).

### 3.4 refresh_tokens
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| family_id | UUID NOT NULL | Same value for every token in one login session's rotation chain; equals the first token's `id`. Indexed. Revocation on reuse is `UPDATE … SET revoked_at = now() WHERE family_id = ?` |
| user_id | UUID NOT NULL FK | |
| token_hash | VARCHAR(128) NOT NULL UNIQUE | SHA-256 of the opaque token; the raw token is never stored |
| parent_id | UUID NULL FK refresh_tokens | Rotation chain |
| expires_at | TIMESTAMPTZ NOT NULL | |
| revoked_at | TIMESTAMPTZ NULL | |
| user_agent, ip | VARCHAR NULL | For "logout everywhere" UX |
| created_at | | |

Lifecycle: issued at login with a new `family_id`; on refresh the old row is revoked and a child issued with the same `family_id`; presenting a revoked token revokes the whole family (replay detection).

### 3.5 categories
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| name | VARCHAR(60) NOT NULL | |
| created_at, updated_at | | |

Constraints: `UNIQUE (business_id, lower(name))`; `UNIQUE (id, business_id)` so `products.category_id` can use the composite tenant FK.

### 3.6 products
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (id, business_id)` |
| business_id | UUID NOT NULL FK | |
| category_id | UUID NULL FK (composite with business_id) | |
| name | VARCHAR(120) NOT NULL | |
| sku | VARCHAR(60) NULL | |
| barcode | VARCHAR(64) NULL | |
| unit | VARCHAR(20) NOT NULL DEFAULT 'piece' | CHECK in (`piece`, `kg`, `g`, `litre`, `ml`, `metre`, `pack`, `service`, `other`) |
| selling_price | NUMERIC(14,2) NOT NULL CHECK ≥ 0 | |
| cost_price | NUMERIC(14,2) NULL CHECK ≥ 0 | NULL = unknown; analytics flag products with unknown cost |
| track_inventory | BOOLEAN NOT NULL DEFAULT true | false for services. Untracked products write no inventory movements, skip stock validation on sale, and keep `stock_quantity = 0` |
| stock_quantity | NUMERIC(12,3) NOT NULL DEFAULT 0 | Cache of movement ledger (BR-11). Never written directly by the API; product creation with `opening_stock` writes an `INITIAL` movement in the same transaction, otherwise the product starts at 0 (PRD FR-D6) |
| low_stock_threshold | NUMERIC(12,3) NULL | NULL → business default |
| is_active | BOOLEAN NOT NULL DEFAULT true | Archive instead of delete |
| created_at, updated_at | | |

Constraints: `UNIQUE (business_id, lower(name)) WHERE is_active` (partial index); `UNIQUE (business_id, sku) WHERE sku IS NOT NULL`; `UNIQUE (business_id, barcode) WHERE barcode IS NOT NULL`. Index on `(business_id, name)` for search.

Financial note: `cost_price` is the *current* expected unit cost; it is snapshotted onto `sale_items.unit_cost` at sale time. Weighted-average cost is not computed in MVP (simple, explainable; documented limitation).

### 3.7 inventory_movements
The stock ledger. Append-only.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| product_id | UUID NOT NULL FK (composite) | |
| movement_type | VARCHAR(20) NOT NULL | CHECK in (`INITIAL`, `RESTOCK`, `SALE`, `SALE_REVERSAL`, `ADJUSTMENT`) |
| quantity_delta | NUMERIC(12,3) NOT NULL | Signed. SALE negative; RESTOCK positive; ADJUSTMENT either. |
| quantity_after | NUMERIC(12,3) NOT NULL | Running balance in commit order (`created_at`), for auditability. Backdated rows (`occurred_at` earlier than `created_at`) keep commit-order balances, so a history sorted by `occurred_at` may show non-monotonic values; `occurred_at` is for reporting only |
| unit_cost | NUMERIC(14,2) NULL | Required for RESTOCK/INITIAL; enables future weighted-average cost |
| total_cost | NUMERIC(14,2) NULL | quantity × unit_cost for RESTOCK |
| sale_id | UUID NULL FK (composite) | Set for SALE / SALE_REVERSAL |
| supplier_name | VARCHAR(120) NULL | Free text until a suppliers table exists |
| reason | VARCHAR(255) NULL | Required for ADJUSTMENT |
| occurred_at | TIMESTAMPTZ NOT NULL | Business-meaningful time (may be backdated by OWNER) |
| created_by | UUID NOT NULL FK users | |
| created_at | | |

Constraints: `CHECK (movement_type <> 'ADJUSTMENT' OR reason IS NOT NULL)`. Index on `(business_id, product_id, occurred_at)` and `(business_id, product_id, created_at)`. The service updates `products.stock_quantity` in the same transaction using `SELECT … FOR UPDATE` on the product row to serialise concurrent sales of the same product.

Rules: only `track_inventory=true` products get movements. A void writes `SALE_REVERSAL` rows for every tracked line even if the product has since been archived (`is_active=false`); archiving hides a product from sale entry, it does not stop history from being corrected.

### 3.8 customers
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (id, business_id)` |
| business_id | UUID NOT NULL FK | |
| name | VARCHAR(120) NOT NULL | |
| phone | VARCHAR(20) NULL | E.164 |
| notes | TEXT NULL | |
| credit_limit | NUMERIC(14,2) NULL | NULL = no limit |
| balance | NUMERIC(14,2) NOT NULL DEFAULT 0 | Cache of credit ledger (positive = owes the business) |
| is_active | BOOLEAN NOT NULL DEFAULT true | |
| created_at, updated_at | | |

Constraint: `UNIQUE (business_id, phone) WHERE phone IS NOT NULL`. PII: name and phone; deletable on request by nulling `phone` and renaming to "Deleted customer" while keeping ledger integrity (PRD NFR-7).

### 3.9 sales
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (id, business_id)` |
| business_id | UUID NOT NULL FK | |
| customer_id | UUID NULL FK (composite) | Required if any payment line is CREDIT |
| idempotency_key | UUID NOT NULL | Client-generated |
| idempotency_hash | CHAR(64) NOT NULL | SHA-256 of the canonical request payload; a retry with the same key and a different hash returns 409 |
| status | VARCHAR(20) NOT NULL | CHECK in (`COMPLETED`, `VOIDED`) |
| subtotal | NUMERIC(14,2) NOT NULL | Σ line totals |
| discount_amount | NUMERIC(14,2) NOT NULL DEFAULT 0 | ≤ subtotal |
| total_amount | NUMERIC(14,2) NOT NULL | subtotal − discount |
| note | VARCHAR(255) NULL | |
| sold_at | TIMESTAMPTZ NOT NULL | Business-meaningful time |
| voided_at | TIMESTAMPTZ NULL | |
| voided_by | UUID NULL FK users | |
| void_reason | VARCHAR(255) NULL | |
| created_by | UUID NOT NULL FK users | |
| created_at, updated_at | | |

There is no cached cost total on the sale. COGS is always computed from `sale_items` so that lines with unknown cost are counted (`lines_missing_cost`) instead of nulling out the whole sale (PRD BR-16).

Constraints: `UNIQUE (business_id, idempotency_key)`; `CHECK (total_amount = subtotal - discount_amount)`; `CHECK (status <> 'VOIDED' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL))`. Index on `(business_id, sold_at DESC)` and `(business_id, customer_id)`.

Lifecycle: created COMPLETED in one transaction with items, payments, SALE movements, and any CHARGE ledger entry. Void → status VOIDED + SALE_REVERSAL movements + REVERSAL ledger entry + audit row. No other transitions. `PENDING` status will be added when M-Pesa STK push arrives (a sale awaiting provider confirmation); analytics already filter on `status = 'COMPLETED'` so this is additive.

### 3.10 sale_items
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| sale_id | UUID NOT NULL FK (composite) | |
| product_id | UUID NOT NULL FK (composite) | |
| product_name | VARCHAR(120) NOT NULL | Snapshot |
| quantity | NUMERIC(12,3) NOT NULL CHECK > 0 | |
| unit_price | NUMERIC(14,2) NOT NULL CHECK ≥ 0 | Actual price charged |
| default_unit_price | NUMERIC(14,2) NOT NULL | Product price at the time (shows overrides) |
| unit_cost | NUMERIC(14,2) NULL | Snapshot of product cost_price; NULL = unknown, contributes 0 to COGS and is counted in `lines_missing_cost` |
| line_total | NUMERIC(14,2) NOT NULL | quantity × unit_price, rounded (BR-9) |
| discount_allocated | NUMERIC(14,2) NOT NULL DEFAULT 0 | This line's share of `sales.discount_amount`, pro-rata by `line_total` with largest-remainder rounding (BR-14). Σ over the sale = `discount_amount` |
| created_at | | |

Constraint: `CHECK (discount_allocated >= 0 AND discount_allocated <= line_total)`. Product revenue = `line_total − discount_allocated`; product gross profit = `line_total − discount_allocated − quantity × unit_cost`. Allocating at sale time is what lets product-level and period-level profit reconcile.

### 3.11 payments
Payment (tender) lines of a sale. **This is the M-Pesa extension point.**

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (id, business_id)` so `credit_transactions.payment_id` can use the composite tenant FK |
| business_id | UUID NOT NULL FK | |
| sale_id | UUID NOT NULL FK (composite) | |
| method | VARCHAR(20) NOT NULL | CHECK in (`CASH`, `MPESA`, `CREDIT`) — additive: `CARD`, `BANK` later. A `CREDIT` row is a receivable, not money received; every "cash collected" query filters `method <> 'CREDIT' AND status = 'CONFIRMED'` (PRD BR-15) |
| amount | NUMERIC(14,2) NOT NULL CHECK > 0 | |
| status | VARCHAR(20) NOT NULL DEFAULT 'CONFIRMED' | CHECK in (`CONFIRMED`, `PENDING`, `FAILED`). MVP always CONFIRMED (manual). Daraja STK push will create PENDING and confirm via callback. |
| reference | VARCHAR(64) NULL | Manually typed M-Pesa code in MVP |
| provider | VARCHAR(20) NOT NULL DEFAULT 'MANUAL' | CHECK in (`MANUAL`) now; `MPESA_DARAJA` later |
| provider_transaction_id | UUID NULL | Future FK → `mpesa_transactions.id` |
| created_at | | |

Constraints: Σ(amount) = `sales.total_amount` is enforced in the sales service (BR-1). M-Pesa reference format is validated in Pydantic, not by a DB CHECK, because code formats can change. Index on `(business_id, method, created_at)` for cash/M-Pesa splits.

Why a separate table rather than `sales.payment_method`: split payments (part cash, part credit) are common; provider status and references are per tender; adding M-Pesa later means adding a provider table and a status transition, not restructuring sales.

### 3.12 credit_transactions
Customer credit ledger. Append-only.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| customer_id | UUID NOT NULL FK (composite) | |
| entry_type | VARCHAR(20) NOT NULL | CHECK in (`CHARGE`, `REPAYMENT`, `REVERSAL`, `ADJUSTMENT`) |
| amount | NUMERIC(14,2) NOT NULL | Signed effect on balance: CHARGE +, REPAYMENT −, REVERSAL −, ADJUSTMENT ± |
| balance_after | NUMERIC(14,2) NOT NULL | Running balance |
| sale_id | UUID NULL FK (composite) | For CHARGE / REVERSAL |
| payment_id | UUID NULL FK (composite) | The CREDIT payment line that created a CHARGE |
| payment_method | VARCHAR(20) NULL | For REPAYMENT: `CASH` or `MPESA` |
| reference | VARCHAR(64) NULL | M-Pesa code for repayment |
| provider_transaction_id | UUID NULL | Future FK → `mpesa_transactions.id` |
| reason | VARCHAR(255) NULL | Required for ADJUSTMENT |
| occurred_at | TIMESTAMPTZ NOT NULL | |
| created_by | UUID NOT NULL FK users | |
| created_at | | |

Constraints: `CHECK (entry_type <> 'ADJUSTMENT' OR reason IS NOT NULL)`; `CHECK (entry_type <> 'REPAYMENT' OR payment_method IS NOT NULL)`. `customers.balance` updated in the same transaction with `SELECT … FOR UPDATE` on the customer row. Index `(business_id, customer_id, occurred_at)`.

Repayments are against the customer, not a specific sale (PRD FR-G3). "Age of oldest unpaid charge" for the debtors list is computed FIFO from the ledger at query time.

### 3.13 expenses
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| amount | NUMERIC(14,2) NOT NULL CHECK > 0 | |
| category | VARCHAR(60) NOT NULL | Free text; UI suggests `RENT`, `TRANSPORT`, `UTILITIES`, `AIRTIME`, `SALARIES`, `LICENSES`, `OTHER` |
| payment_method | VARCHAR(20) NOT NULL | CHECK in (`CASH`, `MPESA`) |
| reference | VARCHAR(64) NULL | |
| note | VARCHAR(255) NULL | |
| incurred_at | TIMESTAMPTZ NOT NULL | |
| deleted_at | TIMESTAMPTZ NULL | Soft delete; audited |
| created_by | UUID NOT NULL FK users | |
| created_at, updated_at | | |

Restock spend is *not* here (BR-6).

### 3.14 ai_conversations
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `UNIQUE (id, business_id)` |
| business_id | UUID NOT NULL FK | |
| user_id | UUID NOT NULL FK users | Conversations are private to the user who started them |
| title | VARCHAR(120) NULL | First question, truncated |
| created_at, updated_at | | |

### 3.15 ai_messages
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| conversation_id | UUID NOT NULL FK (composite) | |
| role | VARCHAR(20) NOT NULL | CHECK in (`user`, `assistant`). The system prompt is built per request and is not stored as a message |
| content | TEXT NOT NULL | Final text shown to the user |
| tool_calls | JSONB NULL | `[ {name, input, output_summary, duration_ms} ]` — outputs are bounded/truncated |
| model | VARCHAR(60) NULL | e.g. `claude-opus-5` |
| input_tokens, output_tokens, cache_read_tokens | INTEGER NULL | |
| stop_reason | VARCHAR(30) NULL | |
| latency_ms | INTEGER NULL | |
| created_at | | |

Index `(business_id, role, created_at)` for quota counting; quotas count `role = 'user'` rows only.

### 3.16 audit_logs
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| business_id | UUID NOT NULL FK | |
| actor_user_id | UUID NULL FK users | NULL for system actions |
| action | VARCHAR(60) NOT NULL | e.g. `sale.void`, `inventory.adjust`, `credit.adjust`, `expense.delete`, `product.price_change`, `user.deactivate`, `business.settings_update` |
| entity_type | VARCHAR(40) NOT NULL | |
| entity_id | UUID NOT NULL | |
| before | JSONB NULL | |
| after | JSONB NULL | |
| ip, user_agent | VARCHAR NULL | |
| created_at | | |

Append-only. Written by services inside the same transaction as the change.

## 4. Relationship diagram

```
businesses 1──* business_memberships *──1 users 1──* refresh_tokens
    │
    ├──* categories 1──* products 1──* inventory_movements
    │                                   └──(sale_id)──> sales
    ├──* customers 1──* credit_transactions ──(sale_id, payment_id)──> sales/payments
    │        └──1 * sales 1──* sale_items *──1 products
    │                 └──* payments
    ├──* expenses
    ├──* ai_conversations 1──* ai_messages
    └──* audit_logs
```

Every arrow from `businesses` is a `business_id NOT NULL`; the child tables also carry `business_id` even where the diagram shows them hanging off another parent.

## 5. Ownership, lifecycle and audit summary

| Entity | Owner | Mutable? | Deleted? | Audited |
|---|---|---|---|---|
| businesses | itself | settings only | never | settings changes |
| users | self / OWNER | profile, password | never (deactivate) | role/deactivation |
| products | business | yes | archive only | price changes |
| inventory_movements | business | **append-only** | never | adjustments & restocks |
| sales | business | status only (void) | never | void |
| sale_items / payments | sale | **immutable** | never | via sale |
| customers | business | yes | archive / PII scrub | manual balance adjustments |
| credit_transactions | business | **append-only** | never | adjustments |
| expenses | business | OWNER edits | soft delete | edit/delete |
| ai_* | user within business | append | retention policy TBD | — |
| audit_logs | business | **append-only** | never | — |

## 6. Financial integrity rules (enforced in services, backed by DB constraints)

1. Sale creation is a single transaction: lock products (`FOR UPDATE`, ordered by id to avoid deadlocks) → validate stock → insert sale, items, payments → insert SALE movements and update `stock_quantity` → if CREDIT, lock customer, insert CHARGE, update `balance` → commit. Any failure rolls everything back.
2. Idempotency: `UNIQUE (business_id, idempotency_key)`. On conflict, compare `idempotency_hash`: equal → return the existing sale (200, not 201); different → 409 CONFLICT and no write.
3. Void is the mirror image and is also one transaction, plus an audit row.
4. Cached columns (`products.stock_quantity`, `customers.balance`) can be recomputed from ledgers; a maintenance command `recompute-caches` will exist and a nightly check will alert on drift.
5. Analytics always filter `sales.status = 'COMPLETED'` and `expenses.deleted_at IS NULL`; money-received queries also filter `payments.status = 'CONFIRMED' AND method <> 'CREDIT'`.
6. COGS is computed from `sale_items` only; unknown `unit_cost` contributes 0 and increments `lines_missing_cost` / `products_missing_cost` in every result that reports profit (PRD BR-16).
7. Sale-level discount is allocated to lines at sale time (`sale_items.discount_allocated`, PRD BR-14) so product and period profit reconcile.

## 7. Tenant isolation checklist (must hold for every tenant-scoped table)

- [ ] `business_id NOT NULL` with index.
- [ ] Repository methods take `business_id` as a required argument; there is no "get by id" without business scope.
- [ ] Composite FK to parents where a parent exists.
- [ ] Automated test: cross-tenant read returns 404, cross-tenant write returns 404 (never 403, to avoid confirming existence).
- [ ] Analytics SQL is parameterised by `business_id` in the outermost `WHERE`.
- [ ] AI tools receive `business_id` from the request context only.

## 8. Workflow coverage check

| Workflow (PRD journeys) | Tables touched | Covered |
|---|---|---|
| Register + create business | users, businesses, business_memberships, refresh_tokens | ✔ |
| Add product / opening stock | products, categories, inventory_movements(INITIAL) | ✔ |
| Cash / M-Pesa sale | sales, sale_items, payments, inventory_movements(SALE) | ✔ |
| Credit sale | + customers, credit_transactions(CHARGE) | ✔ |
| Repayment | credit_transactions(REPAYMENT), customers.balance | ✔ |
| Restock | inventory_movements(RESTOCK), products.stock_quantity/cost_price | ✔ |
| Stock adjustment | inventory_movements(ADJUSTMENT), audit_logs | ✔ |
| Void | sales, inventory_movements(SALE_REVERSAL), credit_transactions(REVERSAL), audit_logs | ✔ |
| Expense | expenses | ✔ |
| Analytics summary | sales, sale_items, payments, expenses, credit_transactions (repayments for cash collected) | ✔ (COGS via `sale_items.unit_cost`; revenue vs cash collected per PRD BR-15) |
| Debtors | customers, credit_transactions | ✔ |
| Copilot | ai_conversations, ai_messages + read-only queries above | ✔ |
| Future: M-Pesa STK push | payments.status/provider + new mpesa_transactions; sales.status PENDING | ✔ additive |
| Future: purchases | new purchases/purchase_items generating RESTOCK movements | ✔ additive |
| Future: multi-branch | would need `locations` and a per-location stock table — **not** additive to `products.stock_quantity`; accepted MVP limitation |

## 9. Implementation notes (Phase 2, migration `b7a497cc6a27`)

The schema is implemented exactly as §3 describes, plus the following database-level backstops and indexes that follow from documented rules but were not spelled out as DDL:

- CHECKs: `products.stock_quantity >= 0` and `inventory_movements.quantity_after >= 0` (BR-4); `products.selling_price >= 0`, `cost_price >= 0` when present; `customers.credit_limit >= 0` when present; `sales.subtotal >= 0` and `0 <= discount_amount <= subtotal` (FR-F4); `sale_items.unit_price >= 0`, `unit_cost >= 0` when present; `credit_transactions.payment_method IN ('CASH','MPESA')` when present.
- `sales.idempotency_hash` is `CHAR(64)` (SHA-256 hex).
- Additional indexes for FK lookups and documented access patterns: `business_memberships(user_id)`, `refresh_tokens(user_id)`, `products(category_id)`, `customers(business_id, name)`, `sale_items(sale_id)`, `sale_items(business_id, product_id)`, `payments(sale_id)`, `inventory_movements(sale_id)`, `credit_transactions(sale_id)`, `credit_transactions(payment_id)`, `*(created_by)` on ledgers, `expenses(business_id, incurred_at)`, `ai_conversations(business_id, user_id)`, `ai_messages(conversation_id, created_at)`, `audit_logs(business_id, created_at)`, `audit_logs(business_id, entity_type, entity_id)`, `audit_logs(actor_user_id)`.
- Enum values are enforced by named CHECK constraints (`ck_<table>_<column>`); columns are `VARCHAR`.
- ORM relationships exist only where later phases obviously need them (`Sale.items`, `Sale.payments`, `BusinessMembership.user/business`, `User.memberships`, `Product.category`) and are all `lazy="raise"`.

### 9.1 Phase 3 notes (no schema change)

- `users.phone` is stored in E.164 after normalisation in `app/schemas/identifiers.py` (Kenyan local forms `07…`, `01…`, `254…` become `+254…`); `users.email` is lower-cased. The same normalisation runs at login, so the identifier the user typed at registration always finds the account.
- `users.password_hash` holds the Argon2id encoded string (`$argon2id$v=19$m=19456,t=2,p=1$…`, ~97 characters, well within 255).
- `refresh_tokens.token_hash` is the SHA-256 hex digest (64 characters) of a 256-bit random token; `family_id` equals the first token's `id`; `parent_id` links each rotation to the token it replaced; `user_agent` (truncated to 255) and `ip` (45) are recorded from the request. Rotation is a single `UPDATE … RETURNING` so concurrent refreshes cannot both succeed (ARCHITECTURE §5.1).
- Registration inserts `users`, `businesses` and the OWNER `business_memberships` row in one transaction; uniqueness of phone/email is left to `uq_users_phone` / `uq_users_email`, and a violation rolls the whole registration back.

### 9.2 Phase 4 notes (no schema change)

- `businesses.settings` is written only as the full validated `BusinessSettings` object (defaults materialised), so a stored value is either `{}` (never edited) or has all three keys.
- `business_memberships.is_active=false` is the "deactivated staff" state; `users.is_active` stays true. The last active OWNER of a business cannot be demoted or deactivated; the service locks the `businesses` row (`FOR UPDATE`) while checking.
- `audit_logs.action` values in use: `business.update`, `user.create`, `user.role_change`, `user.deactivate`, `user.reactivate`, `user.password_reset` (`<entity>.<verb>`); `entity_type` is `business` or `user`; `before`/`after` contain changed fields only and never secrets or phone numbers.

### 9.3 Phase 5 notes (no schema change)

- `products.stock_quantity` is written only by `services/inventory.apply_movement`, in the same transaction as the movement row, with the product row locked. Product creation with `opening_stock` sets it via the `INITIAL` movement; every other product write leaves it alone.
- `inventory_movements.total_cost` is `|quantity_delta| × unit_cost` rounded to 2 dp; `occurred_at` defaults to the commit time for INITIAL-at-creation.
- The SKU and barcode unique indexes are not partial on `is_active`, so an archived product keeps its SKU/barcode reserved; only the *name* is freed by archiving (partial index `WHERE is_active`).
- `audit_logs.action` values added: `product.price_change`, `product.archive`, `product.unarchive`; `entity_type` `product`; Decimal values in `before`/`after` are stored as strings.

## 10. Open data questions

1. Weighted-average vs latest cost for COGS. MVP: latest `cost_price` snapshot. Revisit if pilot owners restock at volatile prices.
2. AI message retention period (proposal: 12 months, configurable).
3. Whether `expenses` needs a `supplier_name`/vendor field (probably yes, cheap; decide in Phase 8).

Resolved since v0.1: STAFF can view customer balances and ledgers (PRD §16) because they record repayments; `sales.cost_total` removed; discount allocated per line; AI quota moved out of owner-editable settings.
