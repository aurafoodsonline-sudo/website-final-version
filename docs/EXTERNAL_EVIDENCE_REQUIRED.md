# External Evidence Required

Do not record secret values in this file. Track only variable names, owners, access status, verification method, and required proof.

| Area | Owner / Source | Access Status | Verification Method | Evidence Required |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | Database / DevOps owner | Missing | Run migrations and DB-backed tests against PostgreSQL | Migration logs and test pass output |
| `DJANGO_SECRET_KEY` | DevOps owner | Missing for production | `manage.py check --deploy` with non-dev secret | Deploy-check output with no secret warning |
| `DJANGO_ALLOWED_HOSTS` | Hosting owner | Missing for production | Staging smoke test | Host/origin proof |
| Object storage | Storage owner | Local dev only | `manage.py check_media_storage --write-test` against production storage | Upload/read/delete output |
| SMTP | Email/domain owner | Missing | Registration/password reset delivery test | SMTP logs and delivered email proof |
| DNS/domain | Domain owner | Missing | DNS record verification | Screenshot/export of DNS config |
| WAF/CDN | Security/hosting owner | Missing | Rate-limit/bot-defense verification | Provider config proof |
| Search Console | Marketing/SEO owner | Missing | Property verification and sitemap submission | Search Console proof |
| Legal approval | Business/legal owner | Missing | Review policies, claims, tax/invoice notes | Signed/dated approval |
| UAT owner | Business/product owner | Missing | Run P0 workflow UAT checklist | UAT sign-off |
| Backup/restore | DevOps owner | Local docs only | Restore drill against staging database/media | Restore log |

