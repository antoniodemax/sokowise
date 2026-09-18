# SokoWise — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Status | v0.3 — synchronised with the implemented product after Phase 14 (supplier receipts) and the Phase 15 production-hardening audit; §21 states what is IMPLEMENTED, PLANNED and what REQUIRES EXTERNAL CONFIGURATION |
| Owner | Product / Engineering |
| Last updated | 2026-09-17 |
| Related docs | [DATA_MAPPING.md](DATA_MAPPING.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [ROADMAP.md](ROADMAP.md) |

> This document is the product source of truth. If code and this document disagree, one of them is wrong — fix the disagreement, do not work around it. Items marked **ASSUMPTION** must be validated with real business owners during the pilot (see §19 and ROADMAP Phase 17).

---

## 1. Product vision

SokoWise is an AI-powered business copilot for small businesses, starting in Kenya. It helps an owner of a duka, mini-shop, boutique, salon, small restaurant, or electronics shop record what happens in the business every day (sales, stock, credit, expenses) with minimal effort, and then *understand* the business by asking plain questions such as "what sold most this week?" or "who owes me money?".

The differentiator is not data entry. Plenty of POS and inventory apps exist. The differentiator is that SokoWise turns the owner's own records into answers, advice and early warnings — in a form that fits a phone, a busy counter, and intermittent connectivity.

**One-line pitch:** "Record your sales in seconds, then ask your business anything."

## 2. Problem being solved

Most Kenyan micro and small businesses run on memory, a notebook, and M-Pesa statements. Typical consequences:

- The owner does not know real daily profit, only cash in the drawer.
- Customer credit ("nitalipa kesho" / "weka kwa book") is tracked in a notebook or not at all, and is regularly forgotten or disputed.
- Stock runs out on fast movers while cash is tied up in slow movers.
- Expenses (rent, transport, airtime, stock purchases) are mixed with personal spending.
- Existing software is desktop-oriented, priced for larger retailers, English-only, or a generic CRUD app that produces tables rather than answers.

SokoWise targets the gap between "notebook + M-Pesa" and "full POS/ERP".

## 3. Target users

**Primary:** owner-operators of businesses with 1–5 staff, roughly KSh 5,000–100,000 daily turnover, selling a bounded catalogue (tens to a few hundred products/services) from one location. The owner is usually also the main cashier.

**Secondary:** a trusted attendant/cashier who records sales when the owner is away.

**Not targeted in MVP:** multi-branch chains, wholesalers with complex pricing tiers, businesses needing VAT/eTIMS invoicing as a first-order feature, businesses without a smartphone.

## 4. Initial Kenyan market context

These are product considerations and working assumptions, not facts about any individual. Every item marked **ASSUMPTION** needs validation with real users.

| Consideration | Product implication |
|---|---|
| Currency is KSh; prices are whole shillings in practice, but cents exist. | Store money as decimal with 2 places; display whole shillings by default. |
| Cash and M-Pesa dominate payments. M-Pesa payments are often confirmed by SMS on the owner's phone, and *recorded* rather than *initiated* by the shop. | MVP records M-Pesa as a payment method with an optional transaction code; no API integration yet. Design must allow Daraja/STK-push later (see ARCHITECTURE §7). |
| Customer credit is common and relationship-based. **ASSUMPTION:** owners want a per-customer running balance and a simple list of "who owes me", not formal invoices. | Credit is a first-class payment method and a per-customer ledger. |
| Restocking is frequent and informal (owner goes to a wholesaler, pays cash or M-Pesa). **ASSUMPTION:** owners think in "I spent KSh X restocking", not purchase orders. | MVP restock = a quick stock-in with cost, no supplier PO workflow. |
| Mobile-first, often mid-range Android devices on metered data. **ASSUMPTION:** most sessions will be under 60 seconds at the counter. | Small bundle, fast sale entry, works on slow 3G, minimal screens per action. |
| Connectivity is intermittent, not absent. | MVP is online-first with safe retries (idempotent sale creation). Full offline mode is future scope. |
| Language: English and Swahili, often mixed (Sheng). | UI in English for MVP; AI copilot must accept and answer in English or Swahili. **ASSUMPTION:** a Swahili UI is desirable but not blocking. |
| WhatsApp is the default communication channel. | Sharing a receipt or a daily summary as text/image to WhatsApp is a cheap, high-value feature (post-MVP). |
| Units vary: pieces, kg (sugar, rice), litres (cooking oil, milk), services (haircut). | Products carry a unit; quantities allow decimals. |
| Regulation: Kenya Data Protection Act (2019) applies to personal data such as customer phone numbers. KRA eTIMS obligations are growing but vary by business size. | Minimise PII, document data handling, plan ODPC registration before public launch. eTIMS is out of MVP scope but must not be architecturally blocked. |

Do not stereotype users. These are hypotheses to test, and the pilot (Phase 17) should be designed to falsify them.

## 5. User personas

**Amina — duka owner (primary).** Runs a general shop in an estate. Sells ~150 SKUs. Knows her regulars and extends credit to ~30 of them. Records nothing digitally except what M-Pesa records for her. Wants to know: did I make money this month, and who owes me?

**Brian — electronics/phone accessories shop owner.** Higher-value items, lower volume. Cares about margin per item and which items sit unsold. Occasionally sells on credit to known customers. Would pay for something that tells him what to restock.

**Wanjiru — salon owner.** Sells services (no stock) plus a few retail products. Has two staff who take payments when she is out. Wants to see what each day brought in and to stop leaks.

**Kevin — attendant (secondary).** Works for an owner. Needs to record a sale in under 15 seconds without access to the owner's financial overview or the ability to delete records.

## 6. Core user problems

1. "I don't know if I'm actually making a profit."
2. "I forget who owes me and how much."
3. "I run out of fast-moving stock and sit on slow stock."
4. "Recording things takes too long, so I stop doing it."
5. "I can't trust my staff's numbers when I'm not there."
6. "Software is built for big shops, not for me."

## 7. Product goals

- G1. A sale can be recorded in under 15 seconds on a phone.
- G2. The owner can answer the six copilot questions in §20 from their own data.
- G3. Credit tracking replaces the notebook for pilot businesses.
- G4. The system is trustworthy: financial records are never silently changed, and every change is attributable to a user.
- G5. The architecture can grow toward M-Pesa integration, offline mode, and multi-branch without a rewrite.

## 8. Non-goals (MVP)

- M-Pesa API (Daraja) integration — recorded manually only.
- KRA eTIMS / VAT invoicing.
- Multi-branch or franchise management.
- Supplier purchase orders, supplier accounts payable.
- Payroll, HR, shifts.
- Accounting (double-entry ledger, balance sheet, bank reconciliation).
- Full offline-first sync.
- Hardware integration (barcode scanners, receipt printers) beyond what a phone camera/browser gives for free.
- Marketplace, e-commerce storefront, customer-facing app.
- AI that writes to the database autonomously.
- Native mobile apps (the web app must work well on mobile browsers; PWA install is a later addition).

## 9. MVP scope

The MVP is the smallest product a real duka could run on for a month.

| # | Capability | In MVP |
|---|---|---|
| 1 | Business account (create business, currency, timezone, basic settings) | Yes |
| 2 | Authentication (register, login, refresh, logout, change password) | Yes |
| 3 | Users & roles (OWNER, STAFF) within a business | Yes |
| 4 | Products (name, price, cost, unit, category, active flag, optional SKU/barcode) | Yes |
| 5 | Inventory (on-hand quantity, restock, adjustment, low-stock threshold, movement history) | Yes |
| 6 | Sales (multi-line, price override, sale-level discount, split payment across CASH / MPESA / CREDIT, void with reason) | Yes |
| 7 | Customers (name, phone, notes, running credit balance) | Yes |
| 8 | Credit (charge on credit sale, record repayment, adjustment, debtors list) | Yes |
| 9 | Expenses (amount, category, date, payment method, note) | Yes |
| 10 | Analytics (today/this week/this month: revenue, COGS, gross profit, expenses, net; top products; slow products; low stock; debtors; expenses by category) | Yes |
| 11 | AI copilot (chat over the owner's own data via backend-controlled tools, read-only) | Yes |
| 12 | Audit log of financial and inventory mutations | Yes (backend), minimal UI |
| 13 | Supplier receipt intelligence (photograph a supplier receipt → AI-drafted restock that the owner reviews and confirms; FR-L) | Yes — implemented as ROADMAP "Phase 14". The M-Pesa-SMS-to-expense half of the original idea is **not** built (§10) |

Everything else is §10.

## 10. Future scope

Ordered by expected value; not committed.

1. M-Pesa Daraja integration (STK push, C2B confirmation) — payments confirmed automatically.
2. WhatsApp sharing of receipts and daily summaries; later, a WhatsApp interface to the copilot.
3. Offline-first sale recording with background sync.
4. Suppliers and purchase records (accounts payable, supplier history). Receipt scanning (FR-L) records the supplier name on the receipt only; there is no supplier entity.
4b. Paste an M-Pesa SMS to draft an expense (the other half of the original receipt-intelligence idea, US-18).
5. Swahili UI.
6. Multi-branch businesses.
7. Customer statements and reminders (SMS/WhatsApp) for outstanding credit.
8. eTIMS-compliant receipts.
9. AI-proposed actions (draft a restock list, draft a reminder message) with explicit user confirmation before anything is written.
10. Business Owner "MANAGER" role for larger shops.

## 11. Functional requirements

Requirement IDs are stable; reference them from tests and commits.

### FR-A Business & account
- FR-A1. A new user can register and create a business in one flow (name, business type, currency defaults to KES, timezone defaults to Africa/Nairobi).
- FR-A2. The registering user becomes OWNER of the business.
- FR-A3. OWNER can update business name, type, phone, address, timezone and settings.
- FR-A4. A user belongs to one business in MVP; the data model supports membership in several (see DATA_MAPPING).

### FR-B Authentication
- FR-B1. Register with phone number (E.164) and password; email optional.
- FR-B2. Login with phone or email + password returns a short-lived access token and a rotating refresh token.
- FR-B3. Refresh tokens are single-use, rotated on refresh, and revocable (logout, logout-all).
- FR-B4. Passwords are hashed with Argon2id.
- FR-B5. Rate limiting on login and registration endpoints.
- FR-B6 (as built 2026-09-18). Self-service password reset by **SMS code**: the person enters their phone; if it belongs to an active account a 6-digit code is sent (Africa's Talking), valid 10 minutes, 5 guesses, single use; confirming sets the new password and signs every device out. The response never says whether the phone is registered. Until the SMS provider is configured the screen says reset is not switched on yet. Owner-initiated staff reset remains.
- FR-B7 (as built 2026-09-18). **Sign in with Google.** The browser gets an ID token from Google; the backend verifies it (signature, audience, issuer, verified email). A known account (by Google id, or first time by verified email) signs in; a new person completes a short finish-up form (phone, business name, type) and gets an account with no password (Google-only, until they set one through FR-B6). Hidden until a Google client id is configured.

### FR-C Users & roles
- FR-C1. OWNER can create a STAFF user for their business (name, phone, initial password). The new user has `must_change_password=true` and must set a new password at first login before any other endpoint is available. If the phone number already belongs to a user, creation returns 409 (one business per user in MVP, FR-A4).
- FR-C2. OWNER can deactivate a STAFF user; deactivated users cannot authenticate.
- FR-C3. Permission matrix in §16 is enforced by the backend on every request.

### FR-D Products & categories
- FR-D1. CRUD products with: name, selling price, cost price, unit, category (optional), SKU (optional), barcode (optional), track_inventory flag, low_stock_threshold, is_active.
- FR-D2. Product names must be unique per business among active products (case-insensitive).
- FR-D3. Products referenced by sales cannot be hard-deleted; they are archived (is_active=false).
- FR-D4. Categories are simple per-business labels.
- FR-D5. Search products by name/SKU/barcode with prefix matching for fast sale entry.
- FR-D6. Product creation may include `opening_stock` and `opening_unit_cost`. When present, the product and its `INITIAL` inventory movement are written in one transaction. When absent, `stock_quantity` starts at 0 and stock is added later through a restock or `INITIAL` movement. `stock_quantity` is never set directly.

### FR-E Inventory
- FR-E1. Every stock change is an inventory movement (RESTOCK, SALE, SALE_REVERSAL, ADJUSTMENT, INITIAL) with quantity delta, unit cost where applicable, reason, and actor. Products with `track_inventory=false` (services) write no movements and skip stock validation; their sale lines still snapshot `unit_cost` when it is known.
- FR-E2. Product on-hand quantity equals the sum of its movements; the denormalised value on the product is updated in the same transaction.
- FR-E3. A sale of a tracked product that would make stock negative is rejected with a clear error. **ASSUMPTION:** blocking is the right default; the pilot will test whether "allow with warning" is needed.
- FR-E4. Low-stock list: tracked, active products with on-hand ≤ threshold.
- FR-E5. Restock records quantity and unit cost; cost price on the product may optionally be updated to the new cost (user choice).

### FR-F Sales & payments
- FR-F1. A sale has one or more lines (product, quantity, unit price, line total) and one or more payment lines (method, amount, reference). Payment lines must sum to the sale total.
- FR-F2. Payment methods: CASH, MPESA, CREDIT. MPESA accepts an optional transaction code. CREDIT requires a customer.
- FR-F3. Unit price may be overridden per line at sale time; the product's default price is recorded alongside.
- FR-F4. Sale-level discount amount (≥ 0, ≤ subtotal).
- FR-F5. Each sale line snapshots product name, unit price and unit cost at the time of sale so later product edits do not change history.
- FR-F6. Sale creation is idempotent via a client-supplied idempotency key (UUID), so a retried request on a flaky network does not double-record. A retry with the same key and the same payload returns the original sale (200). The same key with a different payload returns 409 CONFLICT.
- FR-F7. Sales are immutable once completed. Corrections are made by voiding (OWNER only, with reason), which reverses stock and credit effects. Reversal movements are written even when the product has since been archived.
- FR-F8. Sale timestamp defaults to now but may be backdated by OWNER (e.g. entering yesterday's sales) within a configurable window (default 7 days).
- FR-F9. A sale may optionally be linked to a customer even when not on credit.

### FR-G Customers & credit
- FR-G1. CRUD customers: name, phone (optional, unique per business when present), notes, credit limit (optional).
- FR-G2. Customer balance is derived from a credit ledger: CHARGE (from credit sale), REPAYMENT (cash/M-Pesa), ADJUSTMENT (owner, with reason), REVERSAL (from void).
- FR-G3. Record a repayment against a customer (not against a specific sale) with method and optional reference; partial repayments allowed.
- FR-G4. Debtors list sorted by balance and by age of oldest unpaid charge.
- FR-G5. If a credit sale would exceed the customer's credit limit, STAFF is blocked and OWNER is warned but may proceed.

### FR-H Expenses
- FR-H1. Record an expense: amount, category (from a per-business suggested list, free text allowed), date, payment method (CASH/MPESA), note.
- FR-H2. Stock purchases are **not** expenses; they are restocks (see business rule BR-6).
- FR-H3. OWNER may edit or delete an expense; changes are audited.

### FR-I Analytics
- FR-I1. Summary for a period (today, yesterday, this week, this month, custom range, in business timezone) with these defined metrics (BR-15, BR-16):
  - `sales_count`: COMPLETED sales with `sold_at` in the period.
  - `revenue` (accrual): Σ `sales.total_amount` of those sales. Includes amounts sold on credit.
  - `discounts`: Σ `sales.discount_amount`.
  - `cogs`: Σ `sale_items.quantity × unit_cost` over lines with a known cost.
  - `lines_missing_cost` and `products_missing_cost`: how many lines, and how many distinct products, had no `unit_cost` and therefore contributed 0 to COGS.
  - `gross_profit` = revenue − cogs; `expenses` = Σ non-deleted expenses with `incurred_at` in the period; `net_profit` = gross_profit − expenses.
  - `tender_split`: Σ `payments.amount` by method (CASH, MPESA, CREDIT) for those sales.
  - `cash_collected`: Σ CONFIRMED `payments.amount` where method is CASH or MPESA for sales in the period, plus Σ credit `REPAYMENT` amounts with `occurred_at` in the period, reported by method. CREDIT tenders are excluded.
- FR-I2. Top products by quantity, by revenue (Σ `line_total − discount_allocated`), and by gross profit (Σ `line_total − discount_allocated − quantity × unit_cost`, lines with unknown cost flagged). Because discount is allocated to lines at sale time (BR-14), the sum of product gross profit equals period gross profit.
- FR-I3. Slow products: active tracked products with no sales in N days (default 30) and stock on hand.
- FR-I4. Low-stock products.
- FR-I5. Outstanding credit total and debtors list.
- FR-I6. Expenses by category for a period.
- FR-I7. All analytics are computed from the transactional tables on request; no pre-aggregation in MVP.

### FR-J AI copilot
- FR-J1. A user can ask a free-text question in English or Swahili and receive an answer grounded in their business's data.
- FR-J2. The backend exposes a fixed, read-only set of tools to Claude (see ARCHITECTURE §6). Claude never receives SQL access or raw table dumps.
- FR-J3. All tool executions are scoped to the authenticated user's business and role.
- FR-J4. Conversations and messages are persisted per business and user.
- FR-J5. Every answer that cites numbers must derive them from tool results; the backend records which tool results backed the answer.
- FR-J6. Per-business daily usage limits and a global cost cap are enforced.
- FR-J7 (as built 2026-09-18). The AI never writes. When the owner asks to *add* or *record* something, the copilot may return one **proposal** (a new product, a sale, a customer's debt repayment, or a restock) through a non-executing `propose_*` tool. The proposal is validated, stored on the assistant message as pending, and shown as a card with editable fields and **Confirm** / **Not now**. Only an explicit confirm by an OWNER, re-validated server-side and executed through the same services every screen uses, creates the record; a proposal older than 24 h cannot be confirmed. The answer text must say "tap Confirm" and never claim the record exists. Expenses, edits and voids are not proposable.
- FR-J8. If the AI service is unavailable, the rest of the app keeps working.
- FR-J9 (as built). Answers are returned whole, not streamed (AI-9 is not met yet; see §21). Global spend cap alerts (AI-8) are not enforced in code.

### FR-L Supplier receipt intelligence (implemented 2026-09-17, ROADMAP "Phase 14")
- FR-L1. OWNER uploads a photo of a supplier receipt (JPEG, PNG or WebP, ≤ 8 MB by default, ≥ 200 px on the short side, ≤ 25 megapixels). The file is sniffed by magic bytes and decoded with Pillow before it is stored; anything else is rejected (`RECEIPT_IMAGE_INVALID`, `RECEIPT_TOO_LARGE`). STAFF cannot use any receipt endpoint.
- FR-L2. The image is stored privately under a server-generated key in the business's namespace and is only ever served back to an OWNER of that business, with `Cache-Control: private, no-store`. Cross-tenant access is a 404.
- FR-L3. "Read receipt" sends the image to the extraction provider (Anthropic Claude, forced structured tool call) which proposes supplier, receipt number, date, currency, totals and up to 60 lines (name, SKU, quantity, unit cost, line total, confidence). The proposal is validated (shape, bounds, arithmetic) and stored as an **untrusted draft**; warnings are attached per line (`line_total_mismatch`, `zero_unit_cost`, `low_confidence`) and per receipt (`subtotal_mismatch`, `total_mismatch`, `currency_not_kes`).
- FR-L4. Each line is matched conservatively against the business's active products: SKU/barcode or exact normalised name → MATCHED; fuzzy name ≥ 0.90 with no close runner-up → MATCHED; ≥ 0.70 → AMBIGUOUS with up to three candidates; otherwise UNMATCHED. Only MATCHED lines are pre-selected for the owner. Matching looks at the first 500 active products by name (documented limitation).
- FR-L5. The owner reviews every line: choose or change the product, edit quantity and unit cost, tick/untick lines, optionally update the product's cost price. Nothing touches stock until the owner confirms.
- FR-L6. Confirmation applies each ticked line as an ordinary RESTOCK movement through the inventory service, in one transaction under the receipt row lock, with audit rows that reference the receipt and line. A second confirmation is a 409; a concurrent one loses. Skipped lines are recorded as SKIPPED. Confirmed receipts cannot be cancelled.
- FR-L7. Without `ANTHROPIC_API_KEY` the read step answers 503 `RECEIPT_AI_NOT_CONFIGURED`; provider failures (timeout, busy, unavailable, malformed output) mark the receipt FAILED with the error code and can be retried. Upload, review and confirmation of an already-read receipt work without the provider. The AI never writes to the database.
- FR-L8. Live extraction REQUIRES ANTHROPIC API BILLING on the configured key; it is exercised in tests only through a deterministic fake provider.

### FR-K Audit
- FR-K1. The following are audited with actor, timestamp, entity and before/after: sale void, stock adjustment, restock, credit adjustment, expense edit/delete, product price change, user role/deactivation, business settings change.

### FR-M M-Pesa SMS matching (implemented 2026-09-18)
- FR-M1. OWNER or STAFF can paste an M-Pesa confirmation SMS (or share it from the phone's Messages app into the installed web app). The app reads the transaction code, amount, sender, kind (Pochi, Till, Paybill, send money) and time. Messages about money sent or paid by the shop are refused; unreadable text is kept and flagged so the owner can check it.
- FR-M2. A message is linked to the sale tender or credit repayment that carries the same code, whether the record existed before the paste or is created afterwards (the sell screen can be opened from the message with the tender, amount and code prefilled). Nothing is ever recorded automatically from a message: only a sale or a repayment moves money.
- FR-M3. For a message with no record, the app *suggests* sales of the same amount around the same time and customers whose phone ends with the sender's visible digits. The user chooses; nothing is applied by itself.
- FR-M4. OWNER can ignore a message that is not shop income. Voiding a sale returns its message to "not recorded".
- FR-M5. For each day the app shows: M-Pesa received (from messages), recorded, not recorded, and the M-Pesa money recorded in SokoWise, so the owner can see at a glance what arrived without a record.
- FR-M6. Daraja (automatic confirmation from Safaricom for Till/Paybill) remains future scope (§10); Pochi la Biashara has no API, so SMS matching is its end state.

### FR-N Simple start (implemented 2026-09-18)
- FR-N1. A built-in, curated starter list per business type (general shop, boutique, salon, restaurant, electronics; "other" is empty) with Kenyan item names, typical prices and a suggested cost. It works without any AI key.
- FR-N2. Until the business has at least one product, the owner's dashboard shows a "What do you sell?" card leading to `/setup`, where the owner ticks items, fixes prices, types what they have in stock, and adds them all at once (all-or-nothing; an item that already exists names its row). The card can be skipped and never blocks the app.
- FR-N3. The product form shows the essentials (name, selling price, cost, stock now) with the rest under "More details". No field is removed.
- FR-N4. The sell screen has an "Other item" line (description + amount) for things not in the catalogue, recorded against the untracked product named "Other" that the starter list includes; the description goes into the sale note.
- FR-N5. Dashboard cards use plain words: Sold, In your pocket, Deni (owed to you), Profit before costs, Matumizi (costs), Profit. The analytics page keeps its terms.

## 12. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | Mobile-first UI: usable one-handed on a 360px-wide screen; core flows have no horizontal scroll. |
| NFR-2 | Initial JS bundle for the sale screen ≤ 300 KB gzipped (budget, enforced in CI in Phase 12). |
| NFR-3 | p95 latency ≤ 500 ms for CRUD and sale creation endpoints under pilot load (≤ 50 businesses); analytics ≤ 2 s; AI responses stream first token ≤ 3 s. |
| NFR-4 | Tenant isolation: no endpoint can return or mutate another business's data. Verified by automated tests for every tenant-scoped resource. |
| NFR-5 | Financial integrity: money as `NUMERIC(14,2)`, quantities as `NUMERIC(12,3)`; no floating point in money paths; totals validated server-side. |
| NFR-6 | Security: OWASP ASVS L1 baseline; Argon2id; JWT with short expiry; rotating refresh tokens; rate limiting; no stack traces to clients; dependencies scanned in CI. |
| NFR-7 | Privacy: collect only necessary PII (customer name/phone); document retention; support deleting a customer's PII on request (Data Protection Act 2019). |
| NFR-8 | Availability target 99.5% for the pilot; daily database backups with tested restore. |
| NFR-9 | Observability: structured JSON logs with request IDs, Sentry for errors, basic metrics (request rate, error rate, AI cost). |
| NFR-10 | Accessibility: WCAG 2.1 AA colour contrast, keyboard-operable forms, touch targets ≥ 44px. |
| NFR-11 | All timestamps stored in UTC; "today" computed in the business timezone. |
| NFR-12 | Data export: OWNER can export sales, customers and expenses as CSV (avoid lock-in; builds trust). Implemented: `GET /expenses/export.csv`, `GET /sales/export.csv` (one row per sale line, voided sales included with status), `GET /customers/export.csv`; streamed in keyset batches, dates in the business timezone. |

## 13. User stories

Format: As a *role*, I want *X*, so that *Y*. Priority: M (must), S (should), C (could).

| ID | Story | Pri |
|---|---|---|
| US-1 | As an owner, I want to create my business and log in on my phone, so that I can start recording today. | M |
| US-2 | As an owner, I want to add my products with price and cost quickly (name + price is enough), so that setup does not block me. | M |
| US-3 | As an owner, I want to record a cash sale of several items in a few taps, so that I do not lose customers while typing. | M |
| US-4 | As an owner, I want to record an M-Pesa sale with the transaction code, so that I can reconcile against my M-Pesa statement. | M |
| US-5 | As an owner, I want to put a sale on a customer's credit, so that I stop using the notebook. | M |
| US-6 | As an owner, I want to see who owes me and record when they pay, so that I collect what I am owed. | M |
| US-7 | As an owner, I want to record a restock with what I paid, so that my stock and profit are right. | M |
| US-8 | As an owner, I want to record expenses, so that I see net profit, not just sales. | M |
| US-9 | As an owner, I want to see today's and this week's sales and profit, so that I know how I am doing. | M |
| US-10 | As an owner, I want to be warned when stock is low, so that I restock before running out. | M |
| US-11 | As an owner, I want to ask "what sold most this week?" and get an answer, so that I do not have to read tables. | M |
| US-12 | As an owner, I want to add an attendant who can record sales but not see my profit or delete anything, so that I can leave the shop. | M |
| US-13 | As an attendant, I want the sale screen to be the first thing I see, so that I can serve customers fast. | M |
| US-14 | As an owner, I want to void a mistaken sale with a reason, so that my records stay correct and I can see who voided what. | M |
| US-15 | As an owner, I want to override a price during a sale, so that bargaining is recorded honestly. | S |
| US-16 | As an owner, I want to ask the copilot in Swahili, so that I can use my own words. | S |
| US-17 | As an owner, I want to export my data as CSV, so that my data is mine. | S |
| US-18 | As an owner, I want to paste an M-Pesa message or photograph a receipt and have the expense drafted for me, so that recording is faster. | C — the receipt-photo → restock half is built (FR-L); the M-Pesa-SMS → expense half is future scope |
| US-19 | As an owner, I want to share a daily summary to WhatsApp, so that I can send it to my partner. | C (post-MVP) |

## 14. User journeys

### J1. First day (owner)
1. Register (phone, password, name) → create business (name, type). Land on an empty dashboard with a 3-step setup checklist.
2. Add 5–10 products (name, selling price; cost and stock optional, can be filled later). Optionally set opening stock ("INITIAL" movement).
3. Record first sale from the Sell screen: search product → tap → quantity → tap product 2 → Charge → choose CASH → done. Under 15 s after products exist.
4. End of day: dashboard shows revenue, number of sales, cash vs M-Pesa. Copilot suggests: "You have 3 products with no cost price; add them to see profit."

### J2. Credit sale and repayment
1. On Sell screen, choose CREDIT as payment → pick or create customer (name + phone) → confirm. Customer balance increases; sale is COMPLETED with an outstanding credit charge.
2. Days later: open Customers → debtor → "Record payment" → amount, method (CASH/MPESA), M-Pesa code → balance decreases. Ledger shows both entries.

### J3. Restock
1. Inventory → Low stock list → tap product → "Restock" → quantity, unit cost, note ("Kariobangi wholesaler") → confirm. Stock and (optionally) cost price update; movement recorded.

### J4. Attendant's shift
1. Owner creates STAFF user. Attendant logs in on their own phone or the shop phone.
2. Attendant sees Sell, Products (read-only prices), Customers (record credit sale and repayment), no Analytics, no Expenses, no void.
3. Owner later reviews the day: every sale shows who recorded it.

### J5. Asking the copilot
1. Owner opens Copilot, types "Ni bidhaa gani zimeuzwa zaidi wiki hii?" (which products sold most this week).
2. Backend authenticates, loads the conversation, sends the message plus tool definitions to Claude. Claude calls `get_top_products(period="this_week")`. Backend executes it scoped to the business, returns validated JSON. Claude answers in Swahili with the figures. As built, the backend runs guardrails over the full response and returns it whole (no streaming yet), storing it with the tool results (ARCHITECTURE §6.1, §6.8).

### J6. Voiding a mistake
1. Owner opens Sales → today → tap the wrong sale → Void → reason → confirm.
2. Backend marks the sale VOIDED, writes SALE_REVERSAL movements, writes a credit REVERSAL if the sale was on credit, writes an audit entry. Analytics exclude voided sales.

## 15. Business rules

| ID | Rule |
|---|---|
| BR-1 | A sale's payment lines must sum exactly to `subtotal − discount`. |
| BR-2 | A CREDIT payment line requires a customer on the sale. |
| BR-3 | Sales are never edited or deleted after completion; only voided. Voiding is OWNER-only and reverses all side effects. |
| BR-4 | Stock for tracked products cannot go below zero via a sale. Adjustments may set any non-negative value with a reason. |
| BR-5 | Sale lines snapshot `unit_cost` from the product at sale time; COGS = Σ(quantity × unit_cost) over lines with a known cost. Lines with unknown cost contribute 0 and are counted in `lines_missing_cost` (BR-16). |
| BR-6 | Restocks are inventory events (asset), not expenses. Gross profit = revenue − COGS. Net profit = gross profit − operating expenses. A separate "cash movement" view may show restock spend as cash out. This prevents double-counting stock cost. |
| BR-7 | Customer balance = Σ ledger amounts (CHARGE and ADJUSTMENT(+) increase; REPAYMENT, REVERSAL and ADJUSTMENT(−) decrease). Balance may go negative (customer prepaid / over-repaid); UI labels this as "credit in favour". |
| BR-8 | Voiding a credit sale writes a REVERSAL for the original CHARGE amount even if repayments have occurred; the resulting balance is whatever the ledger says. |
| BR-9 | Money is rounded half-up to 2 dp at line level; totals are sums of rounded lines. Discount allocation (BR-14) uses largest-remainder rounding so the allocations sum exactly to `discount_amount`. |
| BR-10 | All "today / this week / this month" computations use the business's timezone. |
| BR-11 | A product's `stock_quantity` column is a cache of the movement ledger and is updated only inside the same DB transaction as the movement. |
| BR-12 | Deactivated users, archived products, and archived customers remain in history and analytics. |
| BR-13 | The AI copilot has read-only access to business data through named tools; it cannot create, update or delete records in MVP. |
| BR-14 | A sale-level discount is allocated to sale lines at sale time, pro-rata by `line_total`, and stored as `sale_items.discount_allocated`. Σ `discount_allocated` = `sales.discount_amount`. Product-level revenue and profit use `line_total − discount_allocated`, so product figures reconcile to period figures. |
| BR-15 | *Revenue* is accrual: Σ `total_amount` of COMPLETED sales by `sold_at`, including credit sales. *Cash collected* is money received: CONFIRMED CASH and MPESA tenders on sales plus credit REPAYMENTs. A CREDIT tender is a receivable, never cash received; it appears in outstanding credit until repaid. Repayments are never revenue (the revenue was recognised at the sale). |
| BR-16 | Profit figures are never silently understated. Any calculation that skips a line for lack of cost reports `lines_missing_cost` and `products_missing_cost` alongside the number, and the UI and copilot show this to the owner. |

## 16. Roles and permissions

MVP roles: **OWNER**, **STAFF**. (MANAGER is reserved for the future.)

| Action | OWNER | STAFF |
|---|---|---|
| View / edit business settings | ✔ | ✖ |
| Manage users | ✔ | ✖ |
| Create / edit products, prices | ✔ | ✖ |
| View products and prices | ✔ | ✔ |
| Restock / adjust stock | ✔ | ✖ (restock ✔ if setting `staff_can_restock` — **default off**) |
| Record sale (CASH, MPESA, CREDIT) | ✔ | ✔ |
| Backdate a sale | ✔ | ✖ |
| Void sale | ✔ | ✖ |
| View sales list | ✔ (all) | ✔ (own sales, today) |
| Create / edit customers, record repayment | ✔ | ✔ |
| View customer balance and ledger | ✔ | ✔ (needed to record repayments and explain the balance to the customer) |
| Adjust customer balance manually | ✔ | ✖ |
| Record expenses | ✔ | ✖ |
| View analytics / profit | ✔ | ✖ |
| Use AI copilot | ✔ | ✖ (MVP) |
| Export data | ✔ | ✖ |
| View audit log | ✔ | ✖ |

All checks are enforced server-side; the frontend only hides what the user cannot do.

## 17. Acceptance criteria (MVP)

The MVP is accepted when all of the following pass:

1. A new user can register, create a business, add a product, and record a cash sale in a mobile browser without assistance.
2. Automated tests prove that a user of Business A receives 404 for every tenant-scoped resource of Business B (list, get, update, delete, analytics, AI tools). 403 is reserved for role denials within the user's own business.
3. Sale creation with an existing idempotency key and the same payload returns the original sale and does not duplicate stock movements or credit charges; the same key with a different payload returns 409.
4. Voiding a credit sale restores stock and reverses the customer's balance; the audit log records actor and reason.
5. A period summary matches a hand-computed expectation on a fixture data set (revenue, COGS, gross profit, expenses, net).
6. The copilot answers the six reference questions in §20 correctly on the fixture data set, in both English and Swahili, and refuses/declines gracefully on out-of-scope requests ("delete all my sales").
7. No endpoint returns a stack trace or database error text; all errors use the documented error envelope.
8. Argon2id hashing, refresh-token rotation and revocation, and login rate limiting are covered by tests.
9. The app deploys from `main` via CI to Vercel (frontend) and Railway (backend + Postgres) with Sentry receiving errors.
10. Lighthouse mobile performance ≥ 80 on the Sell screen.

## 18. Success metrics

Pilot targets (first 8 weeks with ~10–20 businesses):

| Metric | Target |
|---|---|
| Activation: business records ≥ 10 sales within 7 days of signup | ≥ 60% |
| Daily recording: median days per week with ≥ 1 sale recorded | ≥ 5 |
| Credit adoption: businesses with ≥ 1 credit customer using repayments | ≥ 50% |
| Week-4 retention (business recorded a sale in week 4) | ≥ 50% |
| Copilot use: businesses asking ≥ 3 questions per week | ≥ 40% |
| Copilot accuracy on the internal eval set | ≥ 95% numeric correctness |
| Owner-reported "I know my profit now" (survey) | ≥ 70% agree |
| AI cost per active business per month | ≤ KSh 150 equivalent. The quota in AI-8 is set to keep a business at quota under this figure; verified against current pricing and measured usage at the start of Phase 9 (AI-12). |

## 19. Risks and assumptions

### Risks
| Risk | Impact | Mitigation |
|---|---|---|
| Data-entry fatigue: owners stop recording after a week. | Product fails regardless of AI quality. | Sale entry speed is the top UX priority; receipt intelligence (Phase 10) reduces typing; pilot measures drop-off. |
| Wrong profit numbers erode trust. | Fatal for the "copilot" promise. | Snapshot costs at sale time, BR-6, fixture-based analytics tests, show "how this was calculated". |
| AI hallucinated numbers. | Same. | Numbers only from tool results; structured validation; eval set; show source figures. |
| Prompt injection via product/customer names. | AI misbehaviour, data leakage across conversation. | Treat all business data as untrusted content in prompts; tools are read-only and tenant-scoped; no cross-tenant tools exist. |
| Tenant isolation bug. | Catastrophic, legal exposure. | business_id on every tenant table, repository-level scoping, mandatory isolation tests, optional Postgres RLS in hardening phase. |
| Intermittent connectivity leads to duplicate or lost sales. | Trust. | Idempotency keys; clear pending/failed state in UI; offline queue post-MVP. |
| AI cost outruns revenue. | Unit economics. | Conservative server-side quotas (AI-8) that owners cannot raise, prompt caching with verified cache hits, pricing and cost measured at the start of Phase 9 before quotas are relaxed, cost dashboard. |
| Password reset without SMS/email provider. | Support burden. | Owner-resets-staff in MVP; pick provider before public launch. |
| Regulatory (DPA 2019, eTIMS). | Compliance. | PII minimisation, privacy notice, ODPC registration plan; eTIMS designed-for but not built. |
| Solo-developer bandwidth. | Schedule. | Strict MVP scope; roadmap phases with completion criteria; no premature features. |

### Assumptions to validate with real businesses (pilot)
- A1. Owners will record every sale if it takes < 15 s. *(Alternative: they record end-of-day totals — which would change the data model toward daily summaries.)*
- A2. Owners want per-customer balances rather than per-sale invoices.
- A3. Blocking negative stock is acceptable; owners keep stock reasonably current.
- A4. Restock-as-stock-in (not as expense) matches how owners think about profit once explained.
- A5. Phone number is the preferred login identifier.
- A6. English UI with Swahili-capable copilot is sufficient for the pilot.
- A7. The six copilot questions are the ones owners actually ask; discover the real top 10.
- A8. Staff will use their own phones rather than a shared shop device (affects session length and logout behaviour). How a shared device is handled (idle timeout, shorter refresh lifetime, explicit "shared device" login) is a deferred decision for Phase 3 (ROADMAP); the MVP default until then is the standard 30-day refresh token.
- A9. Owners are willing to pay a monthly subscription in the KSh 300–1,000 range (pricing not yet decided; MVP is free for pilot).

## 20. AI-specific requirements

Reference questions the copilot must answer from tools:

1. "What did I sell most this week?" → `get_top_products`
2. "Which products should I restock?" → `get_low_stock_products` (+ sales velocity)
3. "Who owes me money?" → `get_debtors`
4. "How much did I make today?" → `get_period_summary`
5. "Which products are not selling?" → `get_slow_products`
6. "Which products generate the most profit?" → `get_top_products(by="profit")`

Questions about a named customer ("how much does Mary owe?") resolve the customer through `search_customers`, then `get_customer_ledger`. `get_debtors` also returns `customer_id` for each row.

Requirements:

- AI-1. Model access only through the backend's `ai` module; the frontend never holds an Anthropic key.
- AI-2. Tools are explicit Python functions with Pydantic input/output schemas, registered in an allowlist, each taking the authenticated business context from the request — never from model input. Tool schemas use `strict: true` so arguments are schema-valid.
- AI-3. Tools are read-only in MVP and return bounded result sets (e.g. max 50 rows) with explicit units and currency.
- AI-4. System prompt states the business name, currency, timezone, today's date (in business tz), the user's role, and the language policy (answer in the user's language; Swahili and English supported). Volatile fields go after the cached stable prefix.
- AI-5. Business data (product names, customer names, notes) is inserted only as tool results, never as instructions; the system prompt tells the model to treat it as data.
- AI-6. The backend validates every model response once streaming completes: content blocks are text or allowed tool calls only, no leaked system prompt, tool inputs pass their schemas. Output length is bounded by `max_tokens`, never by cutting text after the fact. Correctness of the figures in an answer is verified by the eval set (AI-11); runtime logic records which tool results backed the answer but does not prove the arithmetic.
- AI-7. Every stored assistant message records the model ID, token usage, the tool calls made and their results (for audit and eval).
- AI-8. Quotas: default 10 user messages per business per day and 100 per calendar month, held in server-side configuration (`AI_DAILY_MESSAGE_LIMIT`, `AI_MONTHLY_MESSAGE_LIMIT`). Business owners cannot change these limits; they are operator settings. A global monthly spend cap alerts at 80% and stops at 100%. The defaults are deliberately conservative and are re-tuned in Phase 9 from measured cost (AI-12).
- AI-9. Latency: stream responses; first token target ≤ 3 s. **Not met as built** (whole answers; see §21).
- AI-10. Safety: the model must decline requests to change data, to reveal other businesses' data, or to act outside business analysis; these cases are in the eval set.
- AI-11. An eval set (fixture business + question/expected-answer pairs) exists before Phase 9 is complete and runs in CI against recorded tool outputs (not live model calls) plus a nightly live run.
- AI-12. Default model is `claude-opus-5` (configurable via `AI_MODEL`); adaptive thinking on; per-request `max_tokens` bounded. At the start of Phase 9, verify current model pricing from the Anthropic documentation, measure real per-message cost from `usage` (including cache reads), and set the quota so a business at the quota stays within the §18 cost target. If it cannot, evaluate a cheaper model against the eval set before changing the default. Pricing figures are never assumed from memory.
- AI-13. PII minimisation: customer phone numbers are not sent to the model unless the question requires them (e.g. "give me John's number"), and then only for the customers in the result set.
- AI-14. STAFF cannot use the copilot in MVP (it exposes profit). Revisit with a role-aware tool subset.

## 21. Implementation status (2026-09-18, after Phase 18)

This section is the honest map between this document and the code. "IMPLEMENTED" means built and covered by the automated suites (backend against a real PostgreSQL, frontend with Vitest) and, where noted, walked through in a browser. Nothing here claims a production deployment exists.

### IMPLEMENTED
- Business account and authentication (FR-A, FR-B1–B7; SMS reset and Google sign-in need their providers configured on the server), users and roles with the §16 matrix enforced server-side (FR-C), audit rows for the FR-K1 list plus inventory/credit/receipt actions.
- Products, categories, inventory (FR-D, FR-E; incl. opening stock, restock with optional cost update, adjustments, low stock, movement history, stock-cache recompute).
- Sales and payments (FR-F1–F9; idempotency, discount allocation BR-9/BR-14, voids that reverse stock and credit).
- Customers and credit (FR-G1–G5; ledger as source of truth, balance cache recompute `POST /customers/recompute`). Customer edit/archive and PII deletion (NFR-7) are **not** built.
- Expenses (FR-H) with soft delete and CSV export; analytics (FR-I1–I7) in the business timezone.
- AI copilot (FR-J1–J8, AI-1–AI-8 quotas, AI-10, AI-13, AI-14) — read-only tools, tenant scoped, whole-answer responses (no streaming, AI-9 open), no enforced global spend cap. Copilot proposals with owner confirmation (FR-J7 as built): covered by the backend suite with a fake provider; the live model behaviour (choosing to propose, resolving ids first) needs Anthropic billing to verify and has not been observed yet.
- Simple start (FR-N1–N5): starter catalogue per business type, bulk add, setup card, simplified product form, "Other item" quick sale, plain-words dashboard.
- Operator dashboard (`/admin`, ROADMAP Phase 19): platform-wide counts for the people listed in `PLATFORM_ADMIN_PHONES`; not a product feature for businesses, and it exposes no tenant records.
- Supplier receipt intelligence (FR-L1–L7) — upload, validation, private storage, extraction pipeline, conservative matching, owner review and atomic confirmation into inventory.
- Data exports (NFR-12): expenses, sales and customers CSV.
- M-Pesa SMS matching (FR-M1–M5): paste or share a confirmation SMS, automatic linking by code in both directions, suggestions, owner ignore, daily received-vs-recorded summary, Android share target via the web manifest.
- Public homepage at `/`; the app at `/dashboard`; mobile layouts checked at 390, 412, 820 and 1366 px.
- Operational: structured JSON logs with request ids, error envelope with no internals, in-process rate limits on auth and AI endpoints, `/health/live` and `/health/ready` (database + migration head; receipt storage reported), Sentry initialisation when `SENTRY_DSN` is set, production start-up guards (secure cookies, no wildcard CORS, no placeholder JWT secret, absolute receipt storage path).

### PLANNED (not built)
- Customer edit/archive and PII deletion on request (FR-G1 "CRUD", NFR-7).
- Streaming copilot answers (AI-9) and the global AI spend cap with 80 % alert (AI-8, FR-J6 "global cost cap").
- M-Pesa SMS → expense draft (US-18 second half); M-Pesa Daraja (FR-M6); WhatsApp; offline sync; PWA service worker/offline (the manifest and share target exist); Swahili UI; multi-branch; suppliers; eTIMS (§10).
- Audit-log UI (§9 row 12 "minimal UI") — the table is written; no endpoint or screen reads it yet.
- Receipt image retention automation (docs/OPERATIONS.md defines the rule; no purge job exists) and an object-storage backend (the `BlobStorage` interface exists; only local-file storage is implemented).
- Postgres row-level security as a second isolation layer (ROADMAP Phase 11).

### REQUIRES EXTERNAL CONFIGURATION (code is ready; the environment is not)
- **Anthropic API billing** on the configured key: without it the copilot and receipt reading answer with the documented 503/400-derived errors and the rest of the product works. Live extraction has not been verified.
- **Production object storage / persistent volume** for receipt images: `RECEIPT_STORAGE_DIR` must point at persistent, absolute storage (a mounted volume); the container disk is ephemeral.
- **Production secrets** (`JWT_SECRET`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SENTRY_DSN`) in Railway/Vercel, never in the repository.
- **Database backups** — Railway snapshots and an off-platform `pg_dump` schedule are described in docs/OPERATIONS.md but are not configured anywhere yet (NFR-8 is therefore unmet).
- **Deployment configuration** — `backend/railway.toml` (migrations before traffic, readiness health check) and `frontend/vercel.json` (SPA rewrite, security headers) are in the repo but have never been exercised against a real Railway/Vercel project; `FORWARDED_ALLOW_IPS` must be set in the Railway service so per-IP rate limits key on the client address.
- **Monitoring** — Sentry only activates with a DSN; there is no uptime check, no alerting and no frontend Sentry yet (NFR-9 partly unmet).
- **Argon2 cost calibration** on the production instance (ARCHITECTURE §5.2) and a tested restore drill before the pilot.
