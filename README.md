# Aura Foods Unified ERP + Commerce Platform

One Django 5.2 application combining the Aura Foods ERP, public storefront, customer accounts, ERP-backed commerce, sales ledger, delivery workflow, CRM, and release controls.

## Surfaces

- Storefront: `/`
- ERP operations: `/erp/`
- Commerce and CRM console: `/commerce-admin/`
- Portal staff console: `/admin/dashboard/`
- Django administration: `/django-admin/`
- ERP API: `/api/`
- Sales API/reports: `/api/sales/`
- CRM API/reports: `/api/crm/`
- Health check: `/health/`

ERP `Product`, `StockBatch`, and `StockLedgerEntry` are the only operational inventory truth. A `CatalogVariantMapping` links public variants to finished ERP SKUs. Checkout creates FEFO reservations; dispatch alone reduces stock and posts the ERP ledger. Returns stay quarantined until QA explicitly releases them.

## Local start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_erp_roles
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver
```

On Linux/macOS use `.venv/bin/python`.

## Verification and release

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test -v 2
python -m pip check
python -m pip_audit -r requirements.txt
python scripts/build_release_package.py
```

See `docs/UNIFIED_ARCHITECTURE.md`, `docs/UNIFIED_DEPLOYMENT_RUNBOOK.md`, `docs/INTEGRATION_MATRIX.md`, and `docs/SBOM_AND_SIGNING.md`.

Final repository audit evidence: 263/263 Django tests passed. See `docs/FINAL_ADVERSARIAL_AUDIT.md` and `docs/UNIFIED_RELEASE_SCORECARDS.md`. Live browser QA remains externally blocked and is not claimed.
