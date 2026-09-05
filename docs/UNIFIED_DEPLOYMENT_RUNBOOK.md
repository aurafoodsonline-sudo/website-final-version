# Unified Deployment Runbook

## Prerequisites

Use Python 3.12, PostgreSQL 16, HTTPS, durable S3/R2-compatible media storage, SMTP, and a secret manager. Copy `.env.example` into the deployment secret configuration; never commit `.env`.

## Database migration

1. Back up the source ERP and portal databases and retain immutable checksums.
2. Restore the chosen ERP database as the unified base.
3. Import portal `shop` tables using a reviewed data migration or database dump mapping. Preserve user primary keys or remap foreign keys explicitly.
4. Run `python manage.py migrate --plan`, review it, then run `python manage.py migrate` in a maintenance window.
5. Migration `sales.0003` maps exact case-insensitive portal SKU codes to active finished ERP product codes. Unmatched variants remain intentionally unsellable.
6. Migrations `sales.0004` and `sales.0005` add invoice-linked customer-ledger reconciliation, enforce one full-order return, backfill historical ledger links where source documents resolve, and split old web customer codes into registered (`WEB-U-*`) and guest (`WEB-G-*`) namespaces.
7. Review mappings in Django admin and resolve every intended sellable variant before opening checkout.
8. Run `python manage.py seed_erp_roles` and verify group membership.
9. Reconcile ERP batch quantities, active reservations, invoice totals, invoice-linked customer-ledger balances, and old web customer codes.

## Deploy

```bash
docker compose build
docker compose run --rm web python manage.py check --deploy --fail-level WARNING
docker compose up -d
```

Run scheduled commands from one or more workers/cron controllers; database leases prevent same-key overlap:

```bash
python manage.py run_scheduled_erp_maintenance
```

## Smoke checks

- `/health/` returns 200.
- `/`, `/shop/`, product, cart, login and contact pages render.
- An unmapped or expired SKU cannot be quoted.
- A mapped checkout creates a reservation and invoice without reducing physical stock.
- Shipping creates a challan and exactly one ERP sales-dispatch ledger row per allocation.
- Cancellation releases reservations; return remains quarantined until QA.
- Customer and staff object ownership/permission checks return 403/404 where expected.

## Rollback

Stop writes, retain the failed database, restore the pre-migration backup, deploy the prior image, and verify stock and financial control totals. Never reverse posted stock or ledger transactions by deleting rows.
