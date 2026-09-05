# Scheduled Tasks Deployment

## Commands

```bash
python manage.py refresh_expiry_statuses
python manage.py refresh_overdue_supplier_invoices
python manage.py run_scheduled_erp_maintenance
python manage.py backup_sqlite
```

Recommended cadence: full maintenance daily at 01:00, backup after maintenance, and external `/health/` monitoring every 5-15 minutes.

## Linux Cron

```cron
0 1 * * * cd /srv/aurafoods && /srv/aurafoods/.venv/bin/python manage.py run_scheduled_erp_maintenance >> /var/log/aurafoods-maintenance.log 2>&1
30 1 * * * cd /srv/aurafoods && /srv/aurafoods/.venv/bin/python manage.py backup_sqlite >> /var/log/aurafoods-backup.log 2>&1
```

Use PostgreSQL backup tooling in PostgreSQL production environments; `backup_sqlite` is only for SQLite.

## Docker

```bash
docker compose run --rm web python manage.py run_scheduled_erp_maintenance
docker compose run --rm web python manage.py backup_sqlite
```

Run scheduling from the host, orchestrator, or scheduler containers that share the same PostgreSQL database. A database lease keyed by job name prevents same-key overlap; a duplicate attempt records `skipped` and does not run child operations. The default lease is 30 minutes, so operations must be monitored and kept within that window.

## Windows Task Scheduler

```text
Program: C:\path\to\.venv\Scripts\python.exe
Arguments: manage.py run_scheduled_erp_maintenance
Start in: C:\path\to\aurafoods
```

Configure a second backup task and alert on nonzero exit codes.

## Inspection and Recovery

- UI: Scheduled Maintenance section.
- API: `/api/scheduled-task-logs/`.
- Admin: Scheduled task logs.
- Failed report: `/api/reports/failed-scheduled-jobs/`.
- Correct the environmental or data issue, then rerun the command. Jobs are safe to rerun.
- Alert when a run approaches the 30-minute lease duration; increase the explicit job TTL in code before deploying a workload expected to exceed it.

Scheduled persistence differs from report-time calculation: jobs store operational classifications and invoice status, while reports calculate current totals from source records.

`ScheduledTaskConfig.enabled=False` is enforced by the executable job functions. A disabled job creates a `skipped` run log, updates `last_run`, and performs no stock or invoice mutation.
