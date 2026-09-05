# Final Adversarial Audit

Audit date: 2026-07-08.

The previous completion state was treated as untrusted. A third-pass hostile review found and repaired repository-side gaps in stock reservation enforcement, refund atomicity, credit/debit-note invoice ownership, public settings exposure, commerce-console permissions, admin dashboard actions, release manifest accuracy, runtime SBOM scope, and package verification.

## Requirement Matrix

| Requirement / domain | Required behavior | Evidence | Defect found in third pass | Repair performed | Final status |
|---|---|---|---|---|---|
| Unified deployment | One Django deployment with shared auth, schema, URLs and release artifact | `aurafoods_erp`, unified apps, Dockerfile, release ZIP | No structural split found | Kept single-project architecture and release package gates | Verified |
| Product/SKU integration | Public variants sell only active mapped ERP finished SKUs | Catalog mapping services and checkout tests | No new code defect found | Existing mapping retained | Verified |
| Inventory source of truth | Dispatch and availability derive from ERP batches/reservations | `sales.services`, FEFO tests | Expired/incomplete reservations could leave dispatch workflow under-controlled | Added reservation reallocation and complete active-reservation gate before dispatch | Verified |
| Checkout and reservation | Server price, aggregated cart lines, FEFO allocation, no overcommit | Sales/shop tests, smoke/performance checks | Needed stronger dispatch-side proof after reservation expiry | Added reallocation workflow and regression coverage | Verified |
| Invoices and ledgers | Balance derives from invoice-linked ledger/payment/notes | `sales.reports.invoices_with_balance`, tests | Commerce console and reports could show stale or query-heavy balances | Added annotated invoice balances and aging/report regression coverage | Verified |
| Payments and refunds | Refunds are authorized, atomic, verified-payment linked, and exactly reconciled | `shop.services.lifecycle`, `shop.services.payments`, tests | Refund request/approval could be detached from a verified payment and mark processed before all effects were safe | Made lifecycle and payment refund atomic, exact-amount, idempotent, permission-tested | Verified |
| Returns and QA | Delivered order ownership, quarantine, QA restock/reject decisions | Sales and shop lifecycle tests | QA rejection path was incomplete | Added QA reject reversal without restock and console action | Verified |
| Credit/debit notes | Notes must belong to the same invoice/customer order context | Sales service tests | Notes could be posted without strong invoice order linkage | Required invoice-linked order and same customer | Verified |
| Customer identity and ownership | Public customers can only act on owned records | Shop lifecycle and API tests | Return/refund ownership needed stronger service-level checks | Added customer ownership checks in lifecycle services | Verified |
| Commerce permissions | Action buttons and views match explicit role permissions | `sales.views`, commerce template, negative UI test | Read-only users could still be offered mutation controls | Added action-specific flags and template guards | Verified |
| Public settings API | Anonymous public settings expose only safe keys | `shop.views`, settings tests | Settings endpoint could expose non-public configuration | Added whitelist and anonymous-safe viewset filtering | Verified |
| Admin dashboard UX/actions | Valid transitions only, permission-aware controls, responsive touch targets | `templates/admin/dashboard.html`, CSS | Dashboard contained invalid statuses, garbled labels, and unsafe action affordances | Normalized labels, fixed status transitions, added permission-aware actions | Verified |
| UI/UX Pro Max | Dense ERP UI, accessible controls, responsive layout, no decorative noise | CSS/templates, route smoke, performance, JS syntax | Live browser QA was blocked by in-app browser policy | Applied UI/UX Pro Max review rules through code/CSS checks; no live browser certification claimed | Verified with external browser caveat |
| Reports and performance | Bounded reports, no invoice-balance N+1, acceptable page query budgets | `release_performance_check`, report tests | Aging and invoice lists needed ledger-derived annotation | Added annotated balances and regression tests | Verified |
| Scheduler | Expiry and overdue jobs run safely and log child jobs | Management command outputs | No new defect found | Operational commands verified | Verified |
| Security | Ownership, explicit action roles, deploy settings, dependency audit | Deploy check, pip check, pip-audit local audit | Requirements-file audit tool failed before analysis in temp env | Used approved local environment audit; no known vulnerabilities found | Verified with tool-bootstrap caveat |
| SBOM and release packaging | Runtime SBOM, payload manifest, checksum, no private artifacts | `scripts/*release*`, package tests | Manifest included generated `.sha256` outside archive; SBOM included dev-only audit/test packages | Fixed manifest exclusions, runtime dependency closure, and package verifier | Verified |

## Verification Evidence

- `manage.py makemigrations --check --dry-run`: no changes detected.
- `manage.py check`: no issues.
- `manage.py test -v 2`: 274 tests passed after fixing the release-manifest defect found by the first run.
- `manage.py check --deploy` with production-shaped environment: no issues.
- `pip check`: no broken requirements.
- `python -m pip_audit --local`: no known vulnerabilities found.
- `manage.py collectstatic --noinput`: 3 copied, 206 unmodified, 431 post-processed.
- `manage.py seed_erp_roles`: roles and endpoint permissions ready.
- `manage.py seed_aurafoods_demo`: demo company, products, recipe and purchase requirement seeded.
- `manage.py refresh_expiry_statuses`: success.
- `manage.py refresh_overdue_supplier_invoices`: success.
- `manage.py run_scheduled_erp_maintenance`: success, 2 child job logs.
- `python -m compileall .`: exit code 0. Pip-audit cache leaves were unreadable, but project code compiled.
- `node --check` via bundled Node runtime: 5 source JavaScript files checked.
- GET `/health/` with allowed host: 200, `{"status": "ok", "service": "aurafoods-erp"}`.
- `manage.py release_smoke_check`: passed.
- `manage.py release_performance_check`: passed.

## External Commissioning

The repository is release-package ready, but production commissioning still requires external evidence: PostgreSQL staging migration and reconciliation, object storage write/read, SMTP delivery, DNS/TLS, WAF/rate limiting, monitoring and alerting, backup/restore drill, courier/payment credentials, legal/tax approval, business UAT, and a real browser/device pass outside the blocked in-app browser policy.

Excluded future scope remains MES expansion and Browser Mutation CI.

## Verdict

PASS at repository/application release-package level. All repository-side defects found in this third pass were repaired and verified. Remaining work is external commissioning or explicitly excluded scope.
