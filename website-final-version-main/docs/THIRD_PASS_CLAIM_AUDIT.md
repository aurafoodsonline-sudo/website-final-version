# Third-Pass Claim Audit

Audit date: 2026-07-08.

## Critical Findings Repaired

| Finding | Severity | Repair | Verification |
|---|---|---|---|
| Dispatch could proceed without a complete active reservation set after expiry/reallocation edge cases | Critical | Added reservation reallocation and strict dispatch reservation coverage | Sales regression tests and full suite |
| Refund approval could be detached from verified payment and partial/inconsistent effects | Critical | Made refund request and approval verified-payment linked, exact, atomic and idempotent | Shop/sales refund tests and full suite |
| QA return rejection workflow was missing | High | Added QA reject service, URL and console action without restocking | Sales QA regression test |
| Credit/debit notes lacked strong invoice/order/customer linkage | High | Required invoice-linked order for the same customer | Sales note regression test |
| Commerce console exposed mutation affordances too broadly | High | Added action-specific permission flags and template guards | Read-only commerce UI test |
| Public settings endpoint could expose non-public keys | High | Added public setting whitelist and anonymous-safe viewset filtering | Public settings API test |
| Admin dashboard actions and labels were not production-grade | Medium | Normalized labels, valid status actions, permission-aware controls and touch targets | Smoke/performance/template coverage |
| Invoice list and aging balances risked stale or repeated calculations | Medium | Added annotated ledger/payment balance helper | Report query regression test |
| Runtime SBOM and release package manifest were overinclusive/inaccurate | High | Runtime dependency closure, dev dependency exclusion, manifest exclusions, verifier | Release tool tests and package build gate |

## Non-Repeated Evidence Policy

The full test suite was not rerun after documentation-only updates. The last code-impacting defect was the release manifest exclusion, after which the full suite passed: 274 tests OK. Subsequent checks were limited to release commands, syntax, health, smoke, performance, SBOM, manifest and package generation because those artifacts were still being produced.

## Browser Caveat

The in-app browser refused access to the local dev server because of browser security policy. This is recorded as an external live-browser QA blocker. Repository-side UI validation used UI/UX Pro Max review rules, template/CSS inspection, route smoke checks, performance budgets and JavaScript syntax checks.

## Final Claim Boundary

The codebase is deployment-ready as a repository release package. It is not claimed to be production-commissioned until PostgreSQL staging, object storage, SMTP, DNS/TLS, WAF, monitoring, backups, payment/courier credentials, legal/tax approval, business UAT and external browser/device QA are completed.
