# Deployment Runbook

Repository-level deployment order:

1. Create `.env` from `.env.example`.
2. Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, HTTPS, CSRF, SMTP, and storage variables.
3. Run `python manage.py check --deploy`.
4. Run `python manage.py migrate --noinput`.
5. Run `python manage.py seed_erp_roles`.
6. Run `python manage.py collectstatic --noinput`.
7. Start Gunicorn.
8. Verify `/health/`, login, role permissions, report CSV export, and media write path.

Docker compose:

- Compose uses PostgreSQL and env-driven credentials.
- `POSTGRES_PASSWORD` must be set in `.env`; no production-like password is hard-coded.
- The web image runs as a non-root user and exposes a container healthcheck.

PostgreSQL backup and restore:

```bash
pg_dump "$DATABASE_URL" --format=custom --file=aurafoods.dump
pg_restore --clean --if-exists --dbname="$DATABASE_URL" aurafoods.dump
```

SQLite helpers are local-only:

```powershell
.\.venv\Scripts\python.exe manage.py backup_sqlite
.\.venv\Scripts\python.exe manage.py restore_sqlite backups\aurafoods-YYYYMMDD-HHMMSS.sqlite3 --confirm
```

Rollback checklist:

- Keep previous image tag and migration state.
- Confirm latest database backup completed before deploy.
- Roll web service back to previous image.
- Restore database only if schema/data corruption is confirmed and approved.
- Re-run `/health/`, login, report export, and stock-ledger reconciliation smoke tests.

Staging smoke test:

- `python manage.py check --deploy`
- `python manage.py test erp frontend -v 2`
- `python -m pip check`
- `python -m pip_audit --local --progress-spinner off`
- `python manage.py check_media_storage --write-test`
- `python manage.py seed_erp_roles`
- `python manage.py seed_aurafoods_demo`
- `python manage.py backup_sqlite` for local-only backup command smoke.

This runbook supports an application-level deployment-ready release candidate. Production certification still requires external infrastructure and sign-off evidence.
