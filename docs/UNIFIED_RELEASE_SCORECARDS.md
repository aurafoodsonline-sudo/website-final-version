# Unified Release Scorecards

Audit date: 2026-07-08. Scores reflect repository evidence after the third-pass repair cycle. They do not certify external hosting, payment, courier, legal, tax, or live browser UAT.

## Integration Architecture

| Domain | Score / 10 | Evidence |
|---|---:|---|
| ERP preservation | 9.5 | ERP services, posting controls, migrations, reports and regression tests retained |
| Web portal preservation | 9.3 | Storefront, account, cart, checkout, support and policy routes pass smoke checks |
| Unified Django architecture | 9.4 | One project, shared settings, auth, URL tree, Docker artifact and release package |
| Product/SKU integration | 9.5 | Active public variants map to active finished ERP SKUs |
| Inventory source of truth | 9.5 | ERP batch/reservation paths drive availability and dispatch |
| Checkout-stock enforcement | 9.5 | Aggregated cart/reservation coverage and dispatch completeness regression tests |
| Customer/user integration | 9.3 | Registered/guest namespacing and service-level ownership checks |
| Sales ledger | 9.4 | Invoice-linked ledger effects, payment, returns, refunds and notes coverage |
| Customer ledger | 9.4 | Invoice balances and aging derive from annotated ledger/payment calculations |
| Delivery workflow | 9.3 | Reservation, challan, dispatch, shipment and COD synchronization tests |
| FEFO dispatch allocation | 9.5 | FEFO reservation, expiry handling, reallocation and dispatch gates |
| Returns/refunds | 9.4 | Delivered-only ownership, QA accept/reject, atomic verified-payment refund workflow |
| CRM | 9.2 | Inquiry, lead, opportunity, follow-up and customer conversion coverage |
| Scheduler | 9.3 | Expiry, supplier-overdue and parent maintenance command evidence |
| SBOM/signing readiness | 9.1 | Runtime SBOM, manifest, checksum, private-artifact rejection; no signature claimed |
| Security and permissions | 9.4 | Public settings whitelist, explicit commerce actions, deploy check and dependency audit |
| UI/UX Pro Max frontend | 9.0 | Permission-aware dense ERP controls, responsive CSS, JS syntax; live browser blocked |
| Reports and exports | 9.2 | Ledger-derived report balances and performance budgets |
| Testing and QA | 9.5 | 274 tests pass, plus smoke, performance, syntax, deploy and release-tool gates |
| Deployment readiness | 9.2 | Docker, static collection, health endpoint, release package scripts and runbooks |
| Documentation | 9.2 | Final audit, scorecards, SBOM/signing and commissioning caveats reconciled |
| Regression safety | 9.5 | Full suite passed after targeted fix for release manifest defect |
| Release package integrity | 9.5 | Exclusions, verifier, SBOM, SHA-256 payload manifest and detached checksum |

## Business Functions

| Domain | Score / 10 |
|---|---:|
| Public storefront | 9.0 |
| Product catalog | 9.3 |
| Cart | 9.4 |
| Checkout | 9.5 |
| Customer account | 9.2 |
| Orders | 9.4 |
| Payments | 9.4 |
| Shipments | 9.3 |
| Returns/refunds | 9.4 |
| Support/contact | 9.1 |
| Blog/content/policies | 9.0 |
| Customer/distributor master | 9.3 |
| Sales invoice | 9.4 |
| Customer ledger | 9.4 |
| Delivery challan | 9.3 |
| Dispatch allocation | 9.5 |
| CRM lead management | 9.2 |
| CRM opportunity pipeline | 9.2 |
| Supplier finance | 9.3 |
| Inventory | 9.5 |
| Production | 9.2 |
| Packing | 9.2 |
| Costing | 9.2 |
| Expiry/FEFO | 9.5 |
| Scheduler | 9.3 |
| SBOM/release governance | 9.4 |

## Final Verification Snapshot

- Migrations: no drift.
- Django checks: normal and production-shaped deploy checks passed.
- Full regression: 274/274 tests passed.
- Dependency consistency: `pip check` passed.
- Vulnerability audit: approved local `python -m pip_audit` path found no known vulnerabilities.
- Runtime operations: collectstatic, role seeding, demo seeding, expiry refresh, overdue refresh and scheduled maintenance passed.
- Health/smoke/performance: `/health/` returned 200; smoke and performance commands passed.
- Syntax: Python compileall returned code 0; 5 source JS files passed `node --check`.
- Browser: in-app browser live QA was blocked by policy, so live visual certification remains external.
