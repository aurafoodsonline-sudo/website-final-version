# AuraFoods ERP — Financial & Stock Posting Matrix

**Convention:** Positive supplier balance = business owes money to supplier (payable).
All services consistently follow this convention. Reports derive balance the same way.

---

## FINANCIAL POSTING MATRIX

| # | Transaction | Supplier Payable | Supplier Advance | Cash/Bank | Inventory |
|---|-------------|-----------------|-----------------|-----------|-----------|
| 7.1 | Supplier Invoice | +amount | — | — | +accepted_qty × rate |
| 7.2 | Supplier Payment | -amount | — | -amount | — |
| 7.3 | Supplier Advance | — | +amount | -amount | — |
| 7.4 | Advance Adjustment | -amount | -amount | — | — |
| 7.5 | Debit Note | -amount | — | — | depends on reason |
| 7.6 | Credit Note | per balance_effect | per balance_effect | — | depends on reason |
| 7.7 | Supplier Return | -amount (via DN) | — | — | -returned_qty |
| 7.8 | Payment Reversal | +original_amount | — | +original_amount | — |
| — | Opening Payable | +amount | — | — | — |
| — | Opening Advance | — | +amount | — | — |
| — | Opening Cash/Bank | — | — | +amount | — |

### Service → Ledger Effect Mapping

```
post_supplier_invoice()       → payable_effect=+amount, advance_effect=0, cash_bank_effect=0
post_supplier_payment()       → payable_effect=-amount, advance_effect=0, cash_bank_effect=-amount
post_supplier_advance()       → payable_effect=0, advance_effect=+amount, cash_bank_effect=-amount
adjust_supplier_advance()     → payable_effect=-amount, advance_effect=-amount, cash_bank_effect=0
post_debit_note()             → payable_effect=-amount, advance_effect=0, cash_bank_effect=0
post_credit_note()            → per balance_effect declaration
post_supplier_return()        → payable_effect=-amount (via debit note), stock reduced
reverse_supplier_payment()    → restores original payment effects with opposite sign
```

### Credit Note Balance Effects (spec 29.2)

| balance_effect | payable | advance | cash_bank |
|---------------|---------|---------|-----------|
| increase_payable | +amount | 0 | 0 |
| decrease_payable | -amount | 0 | 0 |
| increase_advance | 0 | +amount | 0 |
| decrease_advance | 0 | -amount | 0 |
| supplier_refund_due | -amount | 0 | 0 |
| supplier_replacement_due | -amount | 0 | 0 |
| informational_only | 0 | 0 | 0 |

---

## STOCK POSTING MATRIX

| # | Transaction | Raw Stock | Powder Stock | Packaging Stock | Finished Stock |
|---|-------------|-----------|-------------|----------------|---------------|
| 8.1 | GRN Acceptance | +accepted_qty | — | — | — |
| 8.2 | Quality Rejection | move to rejected state | — | — | — |
| 8.3 | Issue to Grinding | -issued_qty | — | — | — |
| 8.4 | Powder Receipt | — | +actual_output | — | — |
| 8.5 | Packing Completion | — | -powder_consumed | -pkg_consumed | +completed_units |
| 8.6 | Supplier Return | -returned_qty (rejected state) | — | — | — |
| 8.7 | Stock Adj (increase) | +adj_qty | +adj_qty | +adj_qty | +adj_qty |
| 8.8 | Stock Adj (decrease) | -adj_qty | -adj_qty | -adj_qty | -adj_qty |
| 8.9 | Expiry Blocking | move to expired state | — | — | move to expired |
| 8.10 | Repacking | -source_qty | (optional) | -pkg_consumed | +new_qty |
| 8.11 | Relabeling | — | — | (consume label) | label_version updated |
| 8.12 | Rework | -input_qty | — | — | +output_qty |
| — | Opening Stock | +opening_qty | +opening_qty | +opening_qty | +opening_qty |

### Stock State Transitions (spec 3.25 / 6.1)

```
accepted → issued          (issue_raw_material_to_grinding)
accepted → rejected        (quality inspection decision)
accepted → hold            (quality hold)
accepted → damaged         (damage posting)
accepted → expired         (expiry date passed)
accepted → blocked         (manual block)
accepted → supplier_returnable  (QI decision = returned_to_supplier)
issued   → (consumed)      (after grinding — batch qty reduced)
rejected → supplier_returnable  (supplier return workflow)
```

### Blocking Rules (spec 6.1)
- States that block normal issue: `rejected, damaged, blocked, expired, hold, supplier_returnable`
- Enforced in: `issue_raw_material_to_grinding()`, `complete_packing_order()`
- Expiry check: `expiry_date < today` → issue blocked

---

## COSTING RULES (spec 9.x)

```
Raw purchase cost         = accepted_quantity × unit_cost
Yield-adjusted powder cost = total_raw_cost / actual_output_quantity
Finished SKU unit cost    = (powder_consumed × powder_unit_cost + packaging_cost) / completed_units
Packing wastage allocation = included in per-unit cost through division by completed_units
```

---

## STATE MACHINES

### GRN (spec 10.2)
```
created → quality_pending → approved → (closed)
                         ↓
                      cancelled
```
GRN is created directly in `quality_pending` (goods received, QI awaited).

### Purchase Order (spec 10.1)
```
draft → pending_approval → approved → partially_received → fully_received → closed
     ↓                  ↓         ↓
  cancelled          cancelled  cancelled (only if no active GRN)
```

### Production Order (spec 10.7)
```
issued → powder_received → closed
       ↓
   cancelled (only if no powder received)
```

### Packing Order (spec 10.8)
```
draft → issued → completed → closed
      ↓                   ↓
   cancelled           reversed (controlled)
```

### Supplier Invoice (spec 10.4)
```
draft → posted → partially_paid → fully_paid
              ↓
           overdue
              ↓
          reversed
```

---

## DOCUMENT NUMBERING (spec section 12)

| Document | Prefix | Example |
|----------|--------|---------|
| Purchase Order | PO | PO-000001 |
| GRN | GRN | GRN-000001 |
| Production Order | PROD | PROD-000001 |
| Packing Order | PACK | PACK-000001 |
| Supplier Invoice | INV | INV-000001 |
| Supplier Payment | PAY | PAY-000001 |
| Advance Payment | ADV | ADV-000001 |
| Debit Note | DN | DN-000001 |
| Credit Note | CN | CN-000001 |
| Stock Adjustment | ADJ | ADJ-000001 |
| Physical Stock Count | PSC | PSC-000001 |
| Opening Balance | OPEN | OPEN-000001 |
| Purchase Requirement | PR | PR-000001 |

All numbers generated via `next_document_number()` using `select_for_update()` on `DocumentSequence` — concurrency-safe.
