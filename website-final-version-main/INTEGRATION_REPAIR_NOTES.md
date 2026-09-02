# Integration Repair Notes

Repair of the merged public website + ERP monolith. Nothing was deleted, renamed,
simplified or regenerated. Every change below is either additive or a protective
guard around existing behaviour.

## Root cause: the website was never damaged, its data bootstrap was dropped

The Django layer was structurally intact the whole time. Measured before any change:

- `manage.py check` -> clean, 0 issues
- all 22 public routes returned HTTP 200
- `collectstatic` succeeded (209 files copied, 517 post-processed)
- CSP was correctly configured; every `<script>` was nonce-covered or same-origin

The database had all 114 tables and **zero rows in every content table**, while
`sqlite_sequence` still held 50 counters, proving data had existed and been wiped.
The site was rendering an empty shell.

The confirming evidence was in `docker-compose.yml`. Its startup command ran
`migrate`, then `seed_erp_roles`, then `collectstatic`. The storefront content
seed, `manage.py seed`, was **missing from the chain**. The ERP's bootstrap
survived the merge; the website's bootstrap did not. On any freshly provisioned
database the ERP populated its roles and the public website got nothing.

## Changes

### 1. `docker-compose.yml` - restored the storefront content seed

Added `python manage.py seed` to the `web` service startup chain, between
`seed_erp_roles` and `collectstatic`.

### 2. `Dockerfile` - added the same bootstrap to the container CMD

`migrate` runs first and stays fatal. The two seed commands then run behind an
`AURAFOODS_SEED_ON_START` toggle (default `1`), each logging a warning instead of
crash-looping the container on failure.

Both seed commands are idempotent: every block is guarded by a
`if <Model>.objects.count() == 0` check, so they only populate empty tables and
will never overwrite real data. Set `AURAFOODS_SEED_ON_START=0` to disable.

### 3. `shop/admin_bootstrap.py` - made bootstrap survive an unready database

`ensure_admin_user()` is invoked while `aurafoods_erp/urls.py` is imported, which
means it writes to the database at URLconf import time. If the database is not yet
migrated or not reachable, that exception propagates out of module import and
returns HTTP 500 for every page on the site.

Added a `DatabaseError` guard that returns `None` instead of raising, plus a
`username="admin"` existence check alongside the existing `is_superuser` check.
The function's public contract is unchanged and still verified by
`shop/tests_admin_bootstrap.py`.

### 4. `aurafoods_erp/urls.py` - removed the test-database side effect

The module-scope `ensure_admin_user()` call also ran while the **test** database
was being created, silently inserting an `admin` superuser that then collided with
`frontend.tests.OperationsConsoleTests`, which creates its own `admin`
(`UNIQUE constraint failed: auth_user.username`).

The call is now wrapped in `_bootstrap_admin_on_startup()`, which skips when
running under the Django or pytest test runner and otherwise behaves exactly as
before. The guard is deliberately at the **call site**, not inside
`ensure_admin_user()`, because the project's own unit test requires the function
itself to work under tests.

### 5. `static/images/` - added 9 missing image files

These paths were referenced by `templates/base.html`, `templates/admin/dashboard.html`
and `shop/management/commands/seed.py` but were absent from disk, so the favicon and
all six category tiles rendered broken.

Added by copying existing in-repo originals; no existing file was replaced.

| Added                      | Copied from          |
| -------------------------- | -------------------- |
| `images/logo.png`          | `uploads/logo.png`   |
| `images/favicon.png`       | `uploads/logo.png`   |
| `images/placeholder.jpg`   | `images/hero-spices.jpg` |
| `images/red-chili-powder.jpg`  | `images/chili.jpg`     |
| `images/turmeric-powder.jpg`   | `images/turmeric.jpg`  |
| `images/coriander-powder.jpg`  | `images/coriander.jpg` |
| `images/garam-masala.jpg`      | `images/garam.jpg`     |
| `images/premium-blends.jpg`    | `images/chaat.jpg`     |
| `images/salt-range.jpg`        | `images/biryani.jpg`   |

Swap these for real photography at any time via the admin image upload, or by
replacing the files directly. The six category images are the ones most worth
replacing with real product shots.

### 6. `db.sqlite3` - seeded for local development

Populated with `migrate` + `seed_erp_roles` + `seed`: 8 products, 8 variants,
6 categories, 13 settings, 11 ERP role groups, plus testimonials, blog posts,
bundles, why-items, delivery zones, FAQ items and site pages.

The single `admin` user has a **deliberately unusable password** (hash begins `!`),
verified byte-level. No credential ships in this archive. Set one with:

```
python manage.py changepassword admin
```

Production is unaffected: `settings.py` requires `DATABASE_URL` when
`DJANGO_DEBUG=0` and rejects SQLite, so deployment uses Postgres and the
boot-time seed.

## Verification performed

Run against Django 5.2.16.

| Check | Result |
| --- | --- |
| `manage.py check` | no issues |
| Public routes, anonymous | 22 / 22 returned 200 |
| ERP routes, anonymous | `/erp/`, `/commerce-admin/`, `/admin/dashboard/` all 302 to login |
| ERP routes, staff session | 200 - 87,225 / 3,794 / 72,807 bytes |
| Homepage content | 45,440 bytes, 4 product cards, 6 category tiles |
| Static references | every `/static/...` path in templates resolves on disk |
| `collectstatic` | 218 files copied, 526 post-processed |
| Seed idempotency | second run inserted nothing, counts unchanged |
| Test suite | 275 tests, **271 pass** |

Before the repair the same suite showed 5 issues; 1 was a real defect
(`OperationsConsoleTests`, item 4 above) and is now fixed. No regressions.

### 4 remaining test issues are sandbox-only, not project defects

The repair environment had no network access, so Linux wheels could not be
installed and the bundled `.venv` contains Windows binaries that cannot load:

- `UploadValidationTests.test_valid_jpeg_png_and_webp_are_accepted`
- `UploadValidationTests.test_fake_image_svg_and_oversized_file_are_rejected`
- `ShopSecurityAndCheckoutTests.test_custom_admin_image_uploads_are_logged_without_secret_material`

  All three need real Pillow. `cryptography` and `Pillow` had to be stubbed to boot
  Django at all. The stubs are **not** in this archive.

- `SettingsHardeningTests.test_production_s3_settings_do_not_create_local_data_or_media_dirs`

  Needs `psycopg` with Linux `libpq`.

These four are expected to pass in your Docker build, which installs proper Linux
wheels from `requirements.txt`. **Please confirm them there** - I could not verify
them and am not claiming that I did.

## Important: run collectstatic before running tests

Django forces `DEBUG=False` during tests, which makes
`CompressedManifestStaticFilesStorage` strict. ERP templates use `{% static %}`, so
without a built manifest every ERP page raises
`ValueError: Missing staticfiles manifest entry`. Always run:

```
python manage.py collectstatic --noinput
python manage.py test
```

The public site is not affected because `templates/base.html` uses literal
`/static/...` paths that bypass the manifest. Your `Dockerfile` and
`docker-compose.yml` both already run `collectstatic`, so deployment is correct.

## Deploying

```
cp .env.example .env      # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, POSTGRES_PASSWORD
docker compose up --build
```

Then set an admin password:

```
docker compose exec web python manage.py changepassword admin
```

## Two open items for you

1. **Only one code project was supplied.** The uploaded
   `photoes_website_structure_and_pricelist.zip` is reference material (33 photos,
   a price list, a structure document), not the standalone marketing website. Work
   proceeded from the merged tree, which still contains the complete website, so no
   functionality was lost. But there is no pristine "Project ONE" to diff against,
   and `db.sqlite3` is untracked in git, so no pre-damage data was recoverable.

2. **Your real price list does not match the seed catalogue.**
   `Aura_Foods_Price_List.xlsx` lists 13 products across 100g / 250g / 500g / 1000g
   tiers; `shop/management/commands/seed.py` contains 8 demo products at different
   prices. Loading your real catalogue is a content decision, so it was not made
   unilaterally. It can be added as a separate seed command that leaves the existing
   one untouched.
