# Hostile Security Checklist

Application-side controls implemented in this repository:

- Endpoint/action permissions: posting workflows require explicit `erp.<domain.action>` permissions.
- Report export authorization: financial and inventory exports are checked before JSON or CSV is generated.
- BasicAuthentication: disabled by default when `DJANGO_DEBUG=0`; enable only with `DJANGO_ENABLE_BASIC_AUTH=1`.
- Security headers: CSP, Referrer-Policy, Permissions-Policy, X-Content-Type-Options, and frame denial are configured.
- Request limits: `DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE` and `DJANGO_FILE_UPLOAD_MAX_MEMORY_SIZE`.
- API errors: validation, missing fields, and invalid decimal payloads return 400 responses.
- Dependency audit: `pip-audit` is part of the verification gate.
- Audit trail: ledger postings, reversals, GRN approval, stock movements, and opening balances create immutable audit records.

Attack-surface review:

- Authentication: Django session auth is primary; production requires strong `DJANGO_SECRET_KEY`, HTTPS, secure cookies, and external brute-force protection such as WAF/rate limiting.
- Authorization: P0 posting routes are mapped to explicit permissions. Normal authenticated users are tested against supplier payments, reversals, stock adjustment, and report exports.
- Injection: ORM query construction is used; raw SQL is not used in application code.
- CSRF: Session-authenticated writes use Django CSRF.
- XSS: templates autoescape by default; CSP restricts script sources to self.
- IDOR: customer account orders, addresses, support tickets, returns and refunds are scoped to the authenticated customer; public confirmation pages reveal private details only to the placing session or a user with `sales.view`. ERP objects are single-company and permission-scoped rather than tenant-scoped.
- File/media safety: media storage write-test exists; object storage virus scanning is an external deployment control.
- Audit tampering: audit rows are protected in admin; database-level immutable audit storage remains an external hardening task.
- Secret leakage: `.env` is ignored; `.env.example` contains placeholders only; release packaging rejects private-key extensions and known SSH private-key names.

External controls still required before production certification:

- WAF/CDN rate limiting and brute-force protection.
- Staging DAST scan.
- Centralized monitoring and alerting.
- Database backup immutability and restore-drill evidence.
- Legal/tax/UAT sign-off.
