# Performance and Report Scaling

Implemented repository-side controls:

- Indexes added for document numbers, supplier/status, product/batch type, warehouse/type, expiry date, transaction dates, and source document references.
- Stock reports use queryset aggregation for ledger in/out quantities instead of per-row ledger lookups.
- Report endpoints support `limit` and `offset` for JSON responses, capped at 1000 rows.
- CSV exports are permission-checked before generation.

Expected scale:

- This small-scale ERP release candidate is designed for thousands to low hundreds of thousands of ledger rows.
- For larger datasets, move long CSV exports to async jobs with object-storage output and audit logs.

Recommended staging checks:

- Run report smoke tests after seeding demo data.
- Add query-count thresholds around supplier ledger, aging, stock, and FEFO reports when representative data volume is available.
