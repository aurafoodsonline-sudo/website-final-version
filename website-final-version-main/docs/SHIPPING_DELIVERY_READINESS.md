# Shipping and Delivery Readiness

Full sales, delivery challan, courier, vehicle, and customer/distributor workflows are P2 future scope for this inventory and purchase release candidate.

Application-side extension points now ready:

- Finished goods batches are warehouse-backed, expiry-aware, and ledger-backed.
- FEFO dispatch allocation suggests finished batches by earliest non-expired expiry date.
- Blocked and expired batches are excluded from normal FEFO allocation.
- Batch traceability links finished goods back to powder, raw material, GRN, and supplier.

Future minimal dispatch workflow:

- Customer or distributor master.
- Delivery challan document with status draft/submitted/posted/cancelled.
- FEFO stock reservation before dispatch.
- Dispatch quantity and stock ledger issue.
- Courier or vehicle reference.
- Sales return readiness using finished batch parent traceability.
