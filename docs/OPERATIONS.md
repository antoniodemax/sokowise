# SokoWise — Operations runbook

Companion to `ARCHITECTURE.md` §9, §10 and §13. This file says what a production deployment
needs, what is already implemented in the repository, and what still has to be configured by
hand on the hosting platforms. Every item is labelled:

- **SUPPORTED PROCEDURE** — the code and configuration in this repository do this today.
- **REQUIRES DEPLOYMENT CONFIGURATION** — must be set up in Railway, Vercel, GitHub or the
  Anthropic console before the pilot; nothing in the repository can do it for you.

Last reviewed: 2026-09-18 (Phase 18c real-world staging check; see `docs/REAL_WORLD_TESTING.md` for what testers are told). No production environment
exists yet; nothing below has been exercised against a live Railway or Vercel project.

## 1. Deployment checklist

### Backend (Railway, Docker image from `backend/Dockerfile`)

| Item | Status | Notes |
|---|---|---|
| Image builds non-root, single uvicorn worker, `/health/live` container healthcheck | SUPPORTED PROCEDURE | `backend/Dockerfile`; CI builds the image on every push. |
| Migrations before traffic | SUPPORTED PROCEDURE (config) / REQUIRES DEPLOYMENT CONFIGURATION (verify) | `backend/railway.toml` sets `preDeployCommand = "alembic upgrade head"` and `healthcheckPath = "/health/ready"`. Confirm in the Railway service settings that the file is picked up (service root must be `backend/`). `/health/ready` answers 503 `migrations: pending` if the schema is behind, so a deploy that skipped the step fails its health check instead of serving traffic. |
| Start-up guards | SUPPORTED PROCEDURE | With `APP_ENV=production` the app refuses to start when `COOKIE_SECURE` is not true, `CORS_ORIGINS` contains a wildcard, `CORS_ORIGIN_REGEX` matches everything, `JWT_SECRET` is the `.env.example` placeholder, or `RECEIPT_STORAGE_DIR` is a relative path. `/docs` and `/openapi.json` are disabled. |
| Client address behind the proxy | REQUIRES DEPLOYMENT CONFIGURATION | Set `FORWARDED_ALLOW_IPS=*` in the Railway service variables. Railway's edge terminates TLS and forwards `X-Forwarded-For`; uvicorn only trusts that header from loopback by default, so without this every user shares the proxy's address and the per-IP login/register/refresh limits apply to *everyone at once*, and `audit_logs.ip` records the proxy. The app logs a warning at start-up when the variable is missing. Never set it in `docker-compose.yml`, where the port is published directly. |
| Sign in with Google | REQUIRES DEPLOYMENT CONFIGURATION | Google Cloud console → create a project (or reuse one) → **APIs & Services → OAuth consent screen**: External, app name "SokoWise", your support email, save → **Credentials → Create credentials → OAuth client ID → Web application**; *Authorised JavaScript origins*: `http://localhost:5173` and `https://sokowise-staging.vercel.app` (add the production domain later); no redirect URI is needed for the ID-token flow. Copy the **client ID** (it is public) into `GOOGLE_CLIENT_ID` on the backend service and `VITE_GOOGLE_CLIENT_ID` on the Vercel project, then redeploy both. The client *secret* is not used; never put it anywhere. Until both are set the button is hidden and the API answers 503. |
| Password reset by SMS | REQUIRES DEPLOYMENT CONFIGURATION | Africa's Talking account → an app → API key. Sandbox for testing (`AFRICASTALKING_USERNAME=sandbox`; the client then calls `api.sandbox.africastalking.com` and messages go to the sandbox simulator, not real phones); live needs an approved sender ID or short code (`AFRICASTALKING_SENDER_ID`) and airtime (about KSh 0.80 per SMS). Set `SMS_PROVIDER=africastalking`, `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY` (secret), `AFRICASTALKING_SENDER_ID` on the backend service. `SMS_PROVIDER=console` is refused in production because it logs the code. Until configured, "Forgot password?" says it is not switched on yet. |
| Operator dashboard | REQUIRES DEPLOYMENT CONFIGURATION | `PLATFORM_ADMIN_PHONES=+2547…` and/or `PLATFORM_ADMIN_EMAILS=you@example.com` (comma-separated) on the backend service name who may open `/admin` (platform-wide counts, ARCHITECTURE §5.4). Sign in with your normal SokoWise account; "Admin" appears in the navigation. Unset → the route and the API answer not-found for everyone. |
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

## 1a. Staging as deployed (2026-09-18): Render + Neon

The Railway path in §1 could not be exercised: the Railway workspace is on a *Limited Trial*
(unverified GitHub account) and every image build, including a two-line `python:3.12-slim`
Dockerfile, was scheduled and marked FAILED within 5 s with no build output. Railway's API also
rejected `railwayConfigFile` because config-as-code (`railway.toml`) is deprecated until
2026-12-01. The Hobby plan ($5/month) would lift both; it was not affordable, so staging runs on
free tiers instead. Nothing in the application changed for this; the only image change is the
migrate-then-serve entrypoint below.

| Item | Value / status |
|---|---|
| Frontend | Vercel project `sokowise` (root directory `frontend`, Git-connected to `main`), alias `https://sokowise-staging.vercel.app` (per-deployment hash URLs are behind Vercel SSO by default; the alias is public). `VITE_API_BASE_URL`, `VITE_PUBLIC_URL` set in the Vercel *production* environment of that project. |
| Backend | Render free web service `sokowise-api-staging`, Frankfurt, Docker from `backend/Dockerfile`, `https://sokowise-api-staging.onrender.com`. Definition in `render.yaml` (the Render counterpart of `backend/railway.toml`). |
| Migrations before traffic | Render free has **no pre-deploy command**, so the Docker command is `/app/scripts/start.sh`: `alembic upgrade head` then `exec uvicorn`. With one instance and the readiness check on `/health/ready` (503 while `migrations: pending`) the ordering guarantee is the same as Railway's `preDeployCommand`. Verified: a brand-new Neon database reached head `7f4db0684dfd` with all 18 tables on first deploy. |
| Database | Neon free project `sokowise-staging`, Frankfurt, Postgres 18, 0.5 GB, autosuspends when idle, SSL required. `DATABASE_URL` uses `postgresql+asyncpg://…?ssl=require` (Neon prints `sslmode=require&channel_binding=require`; asyncpg wants `ssl=require`). Pool sized `DB_POOL_SIZE=3`, `DB_MAX_OVERFLOW=2`. Isolated from every local database. |
| Environment | `APP_ENV=production` (the §1 start-up guards run for real), `CORS_ORIGINS=https://sokowise-staging.vercel.app` exactly, `COOKIE_SECURE=true`, `COOKIE_SAMESITE=none` (app and API are on different registrable domains — the cross-site mode of ARCHITECTURE §5.1; the CSRF header and Origin check are what protect it), `FORWARDED_ALLOW_IPS=*` (the container is reachable only through Render's proxy; verified that `audit_logs.ip` records the real client and that per-IP rate limits key on it), `RECEIPT_STORAGE_DIR=/app/var/receipts`, `API_PORT=10000`. `ANTHROPIC_API_KEY` and `SENTRY_DSN` unset. |
| Receipt images | **Ephemeral.** Render free has no persistent disk. Measured: images survive a *restart* (same container) but are gone after a *redeploy* or an idle spin-down; `GET /receipts/{id}/image` then answers 503 `STORAGE_UNAVAILABLE` and the row stays. Upload, validation, review and confirmation all work. A persistent volume or the object-storage backend is required before any pilot data. |
| Cold start | Render spins the service down after 15 minutes without traffic; the first request afterwards waits for the container to boot and migrate (tens of seconds). Warm requests measure ~220 ms round trip from Nairobi, ~35 ms server time. |
| Sentry / uptime | Not configured on staging (no DSN). |
| Backups | None. Neon free keeps a short point-in-time history but no snapshot schedule was configured; the procedure in §2 still REQUIRES DEPLOYMENT CONFIGURATION. |
| Cost | $0. Render 750 free hours/month, Neon free tier. |

Deploying a change to staging: push to `main` (Render auto-deploys the backend; Vercel's Git
integration is not connected to this project yet — the frontend was deployed with `vercel deploy
--prod` from `frontend/`). The Render service currently builds from the `staging-deploy` branch
until the entrypoint commit lands on `main`; switch it back to `main` afterwards.

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
