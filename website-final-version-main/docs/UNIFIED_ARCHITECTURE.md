# Unified Architecture

## Ownership

- `erp`: operational SKU master, all stock and batches, supplier finance, production, packing, costing, permissions, audit, scheduler.
- `shop`: public content, SEO, catalog presentation, carts, customer identity, checkout UX, customer order/support pages.
- `sales`: variant-to-SKU mapping, customer master link, order mirror, FEFO reservation, invoices, payments, receivables, challans, dispatch, returns, refunds, aging and sales reports.
- `crm`: leads, opportunities, interactions, follow-ups, complaints, segments, conversions and activity reports.
- `frontend`: existing ERP operations console.

## Commerce transaction

1. Server-side pricing validates a cart.
2. Every sellable variant must have one active mapping to an active finished ERP SKU.
3. Checkout creates the portal order and items in one database transaction.
4. Sales services lock eligible batches and reserve in FEFO order. Physical stock is unchanged.
5. A posted invoice creates a positive customer-ledger receivable.
6. Verified payment creates a negative ledger entry and allocation.
7. Shipping transition calls the sales dispatch service. It locks reservations, calls the ERP stock service, creates stock ledger rows and a delivery challan allocation.
8. Cancellation before dispatch releases reservations only.
9. A return creates a negative customer-ledger return entry and quarantined return lines. Stock is not available.
10. QA release traces quantities to dispatched batches and posts ERP `SALES_RETURN_QA` stock-in rows.
11. Refund creates a positive ledger entry, offsetting the return credit when cash is paid back.

Positive customer ledger balance means the customer owes Aura Foods.

## Security boundaries

Public users can access storefront content and only their own account/order/support records. ERP, sales and CRM APIs require authentication plus explicit ERP action permissions. Sales transactional models are read-only in Django admin; mutations use service workflows. Production settings fail closed for secrets, hosts, PostgreSQL, MFA, and configured object storage.

## Scheduler

Each scheduled operation acquires a database lease keyed by job name. An unexpired holder causes a skipped log; expired leases are recovered; success releases the lease; failure marks it failed. This supports multiple application or worker containers sharing PostgreSQL.
