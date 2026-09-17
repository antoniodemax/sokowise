# SokoWise — Operations runbook

Companion to `ARCHITECTURE.md` §9, §10 and §13. This file says what a production deployment
needs, what is already implemented in the repository, and what still has to be configured by
hand on the hosting platforms. Every item is labelled:

- **SUPPORTED PROCEDURE** — the code and configuration in this repository do this today.
- **REQUIRES DEPLOYMENT CONFIGURATION** — must be set up in Railway, Vercel, GitHub or the
  Anthropic console before the pilot; nothing in the repository can do it for you.

Last reviewed: 2026-09-17 (Phase 15 production-hardening audit). No production environment
exists yet; nothing below has been exercised against a live Railway or Vercel project.

## 1. Deployment checklist

### Backend (Railway, Docker image from `backend/Dockerfile`)

| Item | Status | Notes |
|---|---|---|
| Image builds non-root, single uvicorn worker, `/health/live` container healthcheck | SUPPORTED PROCEDURE | `backend/Dockerfile`; CI builds the image on every push. |
| Migrations before traffic | SUPPORTED PROCEDURE (config) / REQUIRES DEPLOYMENT CONFIGURATION (verify) | `backend/railway.toml` sets `preDeployCommand = "alembic upgrade head"` and `healthcheckPath = "/health/ready"`. Confirm in the Railway service settings that the file is picked up (service root must be `backend/`). `/health/ready` answers 503 `migrations: pending` if the schema is behind, so a deploy that skipped the step fails its health check instead of serving traffic. |
| Start-up guards | SUPPORTED PROCEDURE | With `APP_ENV=production` the app refuses to start when `COOKIE_SECURE` is not true, `CORS_ORIGINS` contains a wildcard, `CORS_ORIGIN_REGEX` matches everything, `JWT_SECRET` is the `.env.example` placeholder, or `RECEIPT_STORAGE_DIR` is a relative path. `/docs` and `/openapi.json` are disabled. |
| Client address behind the proxy | REQUIRES DEPLOYMENT CONFIGURATION | Set `FORWARDED_ALLOW_IPS=*` in the Railway service variables. Railway's edge terminates TLS and forwards `X-Forwarded-For`; uvicorn only trusts that header from loopback by default, so without this every user shares the proxy's address and the per-IP login/register/refresh limits apply to *everyone at once*, and `audit_logs.ip` records the proxy. The app logs a warning at start-up when the variable is missing. Never set it in `docker-compose.yml`, where the port is published directly. |
| Secrets | REQUIRES DEPLOYMENT CONFIGURATION | `JWT_SECRET` (≥ 32 random chars, `python -c "import secrets; print(secrets.token_urlsafe(48))"`), `DATABASE_URL` (Railway private networking), `ANTHROPIC_API_KEY`, `SENTRY_DSN`. Stored only in Railway variables. Rotating `JWT_SECRET` logs every user out (access tokens become invalid; refresh still works because refresh tokens are opaque). |
| CORS / cookies | REQUIRES DEPLOYMENT CONFIGURATION | `CORS_ORIGINS=https://app.<domain>` exactly (no trailing slash), `COOKIE_SECURE=true`, `COOKIE_SAMESITE=lax` when app and API share a registrable domain. Preview API environment: `CORS_ORIGIN_REGEX` for Vercel previews and `COOKIE_SAMESITE=none` (ARCHITECTURE §5.1). |
| Receipt image storage | REQUIRES DEPLOYMENT CONFIGURATION | Attach a Railway volume (e.g. mounted at `/data`) and set `RECEIPT_STORAGE_DIR=/data/receipts`. The container filesystem is ephemeral: without a volume every redeploy deletes the images while the `receipts` rows keep pointing at them (`GET /receipts/{id}/image` → 503). An S3-compatible backend is the intended long-term store; the `BlobStorage` interface exists, the implementation does not (PRD §21). |
| Rate limiting | SUPPORTED PROCEDURE, documented limitation | Counters live in the process's memory (`app/core/ratelimit.py`). The image runs **one** uvicorn worker, so within one container the limits are exact; with N Railway replicas the effective limit is N× and every deploy resets it. Acceptable for the pilot (≤ 50 businesses): the per-identifier login limit and Argon2 cost still bound brute force per account. Move to a shared store only if abuse is observed. |
| Database pool | SUPPORTED PROCEDURE | Per process: `DB_POOL_SIZE` (5) + `DB_MAX_OVERFLOW` (5) connections, `pool_pre_ping`, 30 s server-side `statement_timeout` (`DB_STATEMENT_TIMEOUT_MS`). Size replicas so `replicas × 10` stays well under the Postgres `max_connections`. |
| Error reporting | SUPPORTED PROCEDURE (code) / REQUIRES DEPLOYMENT CONFIGURATION (DSN) | `SENTRY_DSN` set → Sentry initialised with `send_default_pii=False`, request bodies never sent, `request_id` tagged on every event. Unset → no-op. Frontend Sentry is not wired. |
| Uptime / alerting | REQUIRES DEPLOYMENT CONFIGURATION | Point an external monitor at `GET /health/ready` (expects `{"status":"ready"}`); Railway's own health check only restarts the container. No alerting exists. |

### Frontend (Vercel, static build of `frontend/`)

| Item | Status | Notes |
|---|---|---|
| SPA routing and security headers | SUPPORTED PROCEDURE (config) / verify on first deploy | `frontend/vercel.json` rewrites every non-`/api/` path to `index.html` (deep links and refreshes on `/dashboard/...` work) and sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` (camera allowed for receipt capture), HSTS and immutable caching for `/assets/`. |
| Environment | REQUIRES DEPLOYMENT CONFIGURATION | `VITE_API_BASE_URL=https://api.<domain>`, `VITE_PUBLIC_URL=https://app.<domain>`; `VITE_SENTRY_DSN` is read by nothing yet. |
| CI | SUPPORTED PROCEDURE | `.github/workflows/ci.yml`: secrets scan (gitleaks), backend lint/type/migrate/test against Postgres, frontend lint/test/build, Docker build. Deploys are triggered by Railway's and Vercel's Git integrations, not by CI (no deploy job exists). |

## 2. Backup and recovery

| Procedure | Status | How |
|---|---|---|
| Automatic database backups | REQUIRES DEPLOYMENT CONFIGURATION | Enable Railway PostgreSQL backups (daily) on the production database. **Nothing in this repository configures backups; until this is done, NFR-8 is unmet and a database loss is unrecoverable.** |
| Off-platform logical backup | REQUIRES DEPLOYMENT CONFIGURATION | Weekly `pg_dump --format=custom --no-owner "$DATABASE_URL" > sokowise-$(date +%F).dump` from a scheduled job (GitHub Actions with a Railway-issued read-only URL, or a cron container), uploaded to object storage with a 90-day lifecycle. Test a restore from it before the pilot. |
| Restore | SUPPORTED PROCEDURE (commands) | 1. Put the API in maintenance (scale to 0 or point DNS away). 2. `pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" sokowise-<date>.dump`. 3. `cd backend && alembic upgrade head` (a dump taken before a migration needs the newer migrations applied). 4. `uv run --env-file .env python scripts/recompute_caches.py` to verify the two cached columns against their ledgers (`--apply` to repair). 5. `GET /health/ready` must report `migrations: ok`. 6. Scale back up. |
| Migrations rollback | SUPPORTED PROCEDURE | Every revision has a `downgrade()`; `alembic downgrade -1` on the affected environment, then redeploy the previous image. The test suite proves `downgrade base → upgrade head` round-trips. Do not downgrade a revision that has received data unless the data loss is understood (the receipts revision drops the receipt tables). |
| Receipt images | REQUIRES DEPLOYMENT CONFIGURATION | Images are files under `RECEIPT_STORAGE_DIR` keyed `receipts/<business_id>/<uuid>.<ext>`; the database row is the index. Back the volume up with Railway volume backups or a periodic `tar` to object storage. A restore is copying the tree back to the same path; rows whose file is missing return 503 on image download and can still be reviewed/confirmed from the extracted lines. |
| Secret recovery | REQUIRES DEPLOYMENT CONFIGURATION | Keep `JWT_SECRET`, `ANTHROPIC_API_KEY` and `SENTRY_DSN` in the team password manager as well as in Railway. Losing `JWT_SECRET` is harmless (generate a new one; users sign in again). Losing the database password means rotating it in Railway and updating `DATABASE_URL`. |

## 3. Data retention

| Data | Rule | Status |
|---|---|---|
| Sales, payments, inventory movements, credit ledger, audit logs, expenses | Kept for the life of the business; ledgers are append-only and never purged (financial records). | SUPPORTED PROCEDURE (no deletion path exists) |
| Receipt rows and lines | Kept with the financial records: a CONFIRMED receipt is the source document of its RESTOCK movements and must stay. | SUPPORTED PROCEDURE |
| Receipt images — CONFIRMED | Retain as long as the business exists (source document). | SUPPORTED PROCEDURE (nothing deletes them) |
| Receipt images — CANCELLED, FAILED, never-read UPLOADED | Eligible for deletion **30 days** after the last status change; the database row stays with `storage_key` intact so the audit trail is complete, and image download then returns 503 `STORAGE_UNAVAILABLE`. | PLANNED — no purge job exists yet. When built it must be a script like `scripts/recompute_caches.py`: dry-run by default, `--apply` to delete, one `receipt.image_purge` audit row per file. |
| Customer PII (name, phone, notes) | Deletion on request is a PRD requirement (NFR-7, Data Protection Act 2019). | PLANNED — no endpoint; today it is a manual SQL change by an operator. Record such requests until the feature exists. |
| Cancelling a receipt | Marks the row CANCELLED, audits it, keeps the image (so a mistaken cancel can be reviewed by an operator); the image falls under the 30-day rule above. Confirmed receipts cannot be cancelled. | SUPPORTED PROCEDURE |

## 4. Routine operations

- **Cache verification** (stock and customer balances): `cd backend && uv run --env-file ../.env python scripts/recompute_caches.py` reports drift for every business (exit code 1 when drift exists); `--apply` repairs it with audit rows. Owners can do the same for their own business through `POST /inventory/recompute` and `POST /customers/recompute`.
- **Readiness**: `GET /health/ready` → `checks.database`, `checks.migrations` (`ok` / `pending` / `unknown`), `checks.receipt_storage` (`ok` / `unavailable`, never fails readiness). `GET /health/live` only proves the process is up. Neither touches the Anthropic API: SokoWise runs normally when AI is unavailable (copilot and receipt reading answer 503 `AI_NOT_CONFIGURED` / `RECEIPT_AI_NOT_CONFIGURED` or the provider error).
- **Logs**: one JSON object per line; every request line carries `request_id`, `method`, `path`, `status`, `duration_ms`. Search by `request_id` (also returned to clients as `X-Request-ID` and in every error envelope). Logs never contain passwords, tokens, cookies, request bodies, images or customer phone numbers; in production SQL parameters are hidden from exception logs (`hide_parameters`).
- **Anthropic billing**: the copilot and receipt reading need credit on the configured key. A key without credit fails with the provider's 400 `credit balance is too low`, which the app reports as 503 `AI_UNAVAILABLE`; nothing else is affected.

## 5. Query performance baseline (2026-09-17)

Measured on a seeded tenant in the local test database (300 products, 2,000 customers, 40,500 sales, 106k sale lines, 109k inventory movements, 13k credit entries, 5k expenses), `EXPLAIN (ANALYZE, BUFFERS)` on the exact statements the application issues plus wall-clock medians. Statement counts are constant per endpoint (no N+1: sale listings issue three statements regardless of rows). Every plan filtered on `business_id`.

| Query | Result | Action taken |
|---|---|---|
| `GET /analytics/slow-products` and the `get_slow_products` copilot tool | 3.1 s wall: a correlated subquery was evaluated three times per product, each a full scan of `sales` | Rewritten as one grouped derived table outer-joined to products (`app/analytics/queries.py: slow_products`) |
| `GET /inventory/movements` without a product filter | parallel sequential scan of the whole ledger + sort (24 ms at 109k rows, linear growth) | Index `inventory_movements (business_id, created_at, id)` (migration `7f4db0684dfd`) |
| Repayments-in-period sum inside every summary/timeseries (dashboard, two copilot tools) | sequential scan of the whole credit ledger keeping a handful of rows | Index `credit_transactions (business_id, occurred_at)` (same migration) |
| Summary, timeseries, product and category performance for a day/week/month | 10–45 ms, index-backed on `sales (business_id, sold_at)` | none |
| Same for a 366-day custom range | 200–380 ms; the COGS `count(distinct …)` and the product grouping spill to disk at 4 MB `work_mem` | deferred — acceptable for the pilot; revisit if long-range reports are used daily (aggregate lines first, or raise `work_mem` for the analytics session) |
| Sales list, sale detail, ledger, expenses, exports, receipts, low stock | ≤ 30 ms, index-backed, keyset-paged exports | none |
| Debtors list | 20–30 ms; window over the tenant's whole ledger (linear in ledger size) | deferred — bounded output, fine at pilot scale |

Not re-measured after the changes in a seeded run; the index and the rewrite were verified by the test suite and by reading the new plans' shape.
