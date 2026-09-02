# Integration Matrix

| Domain | ERP implementation | Portal implementation | Decision and merge action | Migration/service/UI/test status | Risk |
|---|---|---|---|---|---|
| Product/SKU | Operational `Product` | Marketing `Product`/`ProductVariant` | Keep both roles; one-to-one `CatalogVariantMapping` to finished SKU | Exact SKU migration, admin mapping, storefront stock tests | High, controlled |
| Inventory | `StockBatch`, immutable ledger services | Legacy variant/batch counters | ERP only; portal counters are non-authoritative compatibility fields | FEFO availability/reservation/dispatch/return QA tests | Critical, controlled |
| Customer | `CustomerDistributor` | Auth user and addresses | `CustomerAccountProfile` links identity to financial master | Registered and guest customer creation service | Medium |
| Order | No full prior sales order | Portal `Order`/`OrderItem` | Portal owns UX record; `SalesOrder` is financial/operational mirror | Atomic checkout integration and idempotency | High |
| Invoice/ledger | Supplier-side finance | Payment transaction only | New sales invoice, allocation, customer ledger and aging | Reports and reconciliation tests | Critical |
| Delivery | Stock issue and traceability | Shipment/status UX | Challan and dispatch allocation bridge shipment to ERP ledger | Shipping transition dispatches through ERP service | Critical |
| Returns/refunds | No customer flow | Requests | Sales return quarantine, QA stock release, refund ledger | Traceable return test | Critical |
| CRM | Customer master | Contact/support inputs | Models and services for lead-to-customer and complaint pipeline | Admin, permissioned API, reports, tests | Medium |
| Scheduler | Logged jobs | None | Add DB lease around every scheduled operation | Duplicate, expiry, success and failure tests | High |
| Storefront | None | Full responsive portal/assets | Preserve at `/`; namespace portal API at `/store/api/` | Existing portal tests and browser QA | Medium |
| Back office | ERP console | Portal staff console | ERP `/erp/`; commerce `/commerce-admin/`; Django `/django-admin/` | UI UX Pro Max operational layout | Medium |
| Release | ERP package script | Portal CI/security docs | Unified root CI, SBOM, manifest, checksum and signing readiness | Build/audit gates | High |

Legacy portal stock tables remain only for schema/history compatibility and are read-only in administration. Commerce, inventory commands, availability, reports, dispatch and returns neither read nor mutate them as operational stock truth.
