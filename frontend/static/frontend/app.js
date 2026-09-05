/* ═══════════════════════════════════════════════════════════════════════════
   AuraFoods ERP — Operations Console JavaScript
   UI/UX Pro Max: Selectors, confirmations, loading states, error handling
   ═══════════════════════════════════════════════════════════════════════════ */

"use strict";

// ── CSRF & toast ─────────────────────────────────────────────────────────────
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
const toastEl   = document.getElementById("toast");

function showToast(message, type = "default") {
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.className = "";
  if (type === "error")   toastEl.classList.add("error");
  if (type === "success") toastEl.classList.add("success-toast");
  toastEl.classList.add("show");
  clearTimeout(toastEl._timer);
  toastEl._timer = setTimeout(() => toastEl.classList.remove("show"), 4500);
}

// ── Confirmation modal ────────────────────────────────────────────────────────
const overlay = document.getElementById("confirm-modal-overlay");
const confirmTitle   = document.getElementById("confirm-title");
const confirmMessage = document.getElementById("confirm-message");
const confirmOkBtn   = document.getElementById("confirm-ok");
const confirmCancelBtn = document.getElementById("confirm-cancel");
let confirmReturnFocus = null;

function openConfirm(title, message, onOk, danger = true) {
  confirmReturnFocus = document.activeElement;
  confirmTitle.textContent   = title;
  confirmMessage.textContent = message;
  confirmOkBtn.className     = "btn " + (danger ? "btn-danger" : "btn-primary");
  confirmOkBtn.textContent   = danger ? "Confirm & Post" : "Proceed";
  overlay.classList.add("open");
  overlay.setAttribute("aria-hidden", "false");
  confirmOkBtn.onclick = () => { closeConfirm(); onOk(); };
  confirmCancelBtn.onclick = closeConfirm;
  overlay.onclick = (e) => { if (e.target === overlay) closeConfirm(); };
  confirmCancelBtn.focus();
}
function closeConfirm() {
  overlay.classList.remove("open");
  overlay.setAttribute("aria-hidden", "true");
  if (confirmReturnFocus && typeof confirmReturnFocus.focus === "function") confirmReturnFocus.focus();
}

// Escape key closes modal
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && overlay.classList.contains("open")) closeConfirm();
});

// ── API helper ────────────────────────────────────────────────────────────────
async function apiRequest(endpoint, payload, method = "POST") {
  const res = await fetch(endpoint, {
    method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
      "Accept": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
  if (!res.ok) throw new Error(body.detail || JSON.stringify(body));
  return body;
}

async function apiPost(endpoint, payload) {
  return apiRequest(endpoint, payload, "POST");
}

async function apiGet(endpoint) {
  const res = await fetch(endpoint, {
    credentials: "same-origin",
    headers: { "Accept": "application/json", "X-CSRFToken": csrfToken },
  });
  const text = await res.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
  if (!res.ok) throw new Error(body.detail || JSON.stringify(body));
  return body;
}

// ── Button loading state helpers ──────────────────────────────────────────────
function setBtnLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn._original = btn.textContent;
    btn.disabled = true;
    btn.classList.add("btn-loading");
    btn.textContent = "Posting…";
  } else {
    btn.disabled = false;
    btn.classList.remove("btn-loading");
    btn.textContent = btn._original || "Submit";
  }
}

// ── Form value extractor ──────────────────────────────────────────────────────
function getVal(form, name) {
  const el = form.elements[name];
  if (!el) return undefined;
  const v = el.value.trim();
  return v === "" ? undefined : v;
}
function getNum(form, name, fallback = undefined) {
  const v = getVal(form, name);
  return v === undefined ? fallback : v;
}

// ── Field validation ──────────────────────────────────────────────────────────
function validateRequired(form, fieldNames) {
  let valid = true;
  fieldNames.forEach(name => {
    const el = form.elements[name];
    if (!el) return;
    const empty = el.value.trim() === "" || el.value === "0" && el.tagName === "SELECT";
    el.classList.toggle("invalid", empty);
    if (empty) valid = false;
  });
  return valid;
}

// ── Tab navigation ────────────────────────────────────────────────────────────
document.querySelectorAll(".tab-button").forEach(btn => {
  btn.addEventListener("click", () => {
    const panel = btn.dataset.tab;
    const container = btn.closest(".panel") || document;
    container.querySelectorAll(".tab-button").forEach(b => b.classList.toggle("active", b === btn));
    container.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === panel));
  });
});

// ── Sidebar nav active state ──────────────────────────────────────────────────
document.querySelectorAll(".nav-stack a[href^='#']").forEach(link => {
  link.addEventListener("click", () => {
    document.querySelectorAll(".nav-stack a").forEach(a => a.classList.remove("active"));
    link.classList.add("active");
    const rail = document.getElementById("primary-navigation");
    const toggle = document.querySelector(".mobile-nav-toggle");
    rail?.classList.remove("open");
    toggle?.setAttribute("aria-expanded", "false");
  });
});

const mobileNavToggle = document.querySelector(".mobile-nav-toggle");
const primaryNavigation = document.getElementById("primary-navigation");
if (mobileNavToggle && primaryNavigation) {
  mobileNavToggle.addEventListener("click", () => {
    const isOpen = primaryNavigation.classList.toggle("open");
    mobileNavToggle.setAttribute("aria-expanded", String(isOpen));
    mobileNavToggle.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
  });
}

// ── Reload helper (with delay for toast visibility) ──────────────────────────
function delayedReload(ms = 1000) {
  setTimeout(() => window.location.reload(), ms);
}

// ═══════════════════════════════════════════════════════════════════════════
// FORM SUBMIT HANDLERS — one per P0 workflow
// ═══════════════════════════════════════════════════════════════════════════

// ── 1. Direct Purchase / GRN ─────────────────────────────────────────────────
const fDirectPurchase = document.getElementById("f-direct-purchase");
if (fDirectPurchase) {
  fDirectPurchase.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fDirectPurchase, ["supplier","warehouse","product","batch_number","ordered_quantity","received_quantity","accepted_quantity","unit_cost"])) {
      showToast("Please fill all required fields.", "error"); return;
    }
    openConfirm(
      "Confirm Direct Purchase",
      `Post GRN for supplier "${fDirectPurchase.elements.supplier.options[fDirectPurchase.elements.supplier.selectedIndex]?.text}"? This will create stock and a supplier invoice.`,
      async () => {
        const btn = fDirectPurchase.querySelector("button[type=submit]");
        setBtnLoading(btn, true);
        try {
          const body = await apiPost("/api/grns/direct_purchase/", {
            supplier: getVal(fDirectPurchase, "supplier"),
            warehouse: getVal(fDirectPurchase, "warehouse"),
            lines: [{
              product: getVal(fDirectPurchase, "product"),
              ordered_quantity: getNum(fDirectPurchase, "ordered_quantity"),
              received_quantity: getNum(fDirectPurchase, "received_quantity"),
              accepted_quantity: getNum(fDirectPurchase, "accepted_quantity"),
              rejected_quantity: getNum(fDirectPurchase, "rejected_quantity", "0"),
              unit_cost: getNum(fDirectPurchase, "unit_cost"),
              rate_override_reason: getVal(fDirectPurchase, "rate_override_reason"),
              batch_number: getVal(fDirectPurchase, "batch_number"),
              expiry_date: getVal(fDirectPurchase, "expiry_date"),
            }],
          });
          showToast(`GRN ${body.number} created successfully.`, "success");
          fDirectPurchase.reset();
          delayedReload();
        } catch (err) { showToast(err.message, "error"); }
        finally { setBtnLoading(btn, false); }
      }
    );
  });
}

// ── 2. GRN Quality Inspection ────────────────────────────────────────────────
const fQualityInspect = document.getElementById("f-quality-inspect");
if (fQualityInspect) {
  fQualityInspect.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fQualityInspect, ["grn_id"])) {
      showToast("Select a GRN.", "error"); return;
    }
    openConfirm("Confirm Quality Inspection", "Post quality inspection for this GRN? This action cannot be reversed.", async () => {
      const btn = fQualityInspect.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const grnId = getVal(fQualityInspect, "grn_id");
        const body = await apiPost(`/api/grns/${grnId}/inspect_quality/`, {
          deduction_amount: getNum(fQualityInspect, "deduction_amount", "0"),
        });
        showToast(`Quality inspection posted for GRN ${body.grn}.`, "success");
        fQualityInspect.reset();
        delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 3. GRN Approve ───────────────────────────────────────────────────────────
const fApproveGrn = document.getElementById("f-approve-grn");
if (fApproveGrn) {
  fApproveGrn.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fApproveGrn, ["grn_id","warehouse"])) {
      showToast("Select GRN and warehouse.", "error"); return;
    }
    openConfirm("Confirm GRN Approval", "Approve this GRN? Stock will be received into inventory and invoice created.", async () => {
      const btn = fApproveGrn.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const grnId = getVal(fApproveGrn, "grn_id");
        const body = await apiPost(`/api/grns/${grnId}/approve/`, {
          warehouse: getVal(fApproveGrn, "warehouse"),
          create_invoice: true,
        });
        showToast(`GRN ${body.number} approved.`, "success");
        delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 4. Supplier Advance ───────────────────────────────────────────────────────
const fAdvance = document.getElementById("f-supplier-advance");
if (fAdvance) {
  fAdvance.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fAdvance, ["supplier","cash_bank_account","amount"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    const supName = fAdvance.elements.supplier.options[fAdvance.elements.supplier.selectedIndex]?.text || "";
    const amount  = getNum(fAdvance, "amount");
    openConfirm("Confirm Advance Payment", `Post advance of ${amount} to ${supName}? This will reduce cash/bank balance.`, async () => {
      const btn = fAdvance.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const body = await apiPost("/api/payments/advance/", {
          supplier: getVal(fAdvance, "supplier"),
          cash_bank_account: getVal(fAdvance, "cash_bank_account"),
          amount,
        });
        showToast(`Advance ${body.number} posted.`, "success");
        fAdvance.reset();
        delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 5. Pay Invoice ───────────────────────────────────────────────────────────
const fPayInvoice = document.getElementById("f-pay-invoice");
if (fPayInvoice) {
  fPayInvoice.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fPayInvoice, ["supplier","cash_bank_account","invoice","amount"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    const invText = fPayInvoice.elements.invoice.options[fPayInvoice.elements.invoice.selectedIndex]?.text || "";
    openConfirm("Confirm Invoice Payment", `Post payment against invoice ${invText}?`, async () => {
      const btn = fPayInvoice.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const body = await apiPost("/api/payments/pay_invoice/", {
          supplier: getVal(fPayInvoice, "supplier"),
          cash_bank_account: getVal(fPayInvoice, "cash_bank_account"),
          invoice: getVal(fPayInvoice, "invoice"),
          amount: getNum(fPayInvoice, "amount"),
        });
        showToast(`Payment ${body.number} posted.`, "success");
        fPayInvoice.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 6. Adjust Advance ────────────────────────────────────────────────────────
const fAdjAdvance = document.getElementById("f-adjust-advance");
if (fAdjAdvance) {
  fAdjAdvance.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fAdjAdvance, ["supplier","invoice","amount"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    openConfirm("Confirm Advance Adjustment", "Adjust advance against selected invoice? This changes both advance and payable balances.", async () => {
      const btn = fAdjAdvance.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const body = await apiPost("/api/payments/adjust_advance/", {
          supplier: getVal(fAdjAdvance, "supplier"),
          invoice: getVal(fAdjAdvance, "invoice"),
          amount: getNum(fAdjAdvance, "amount"),
        });
        showToast(`Advance adjustment ${body.number} posted.`, "success");
        fAdjAdvance.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 7. Reverse Payment ───────────────────────────────────────────────────────
const fReverse = document.getElementById("f-reverse-payment");
if (fReverse) {
  fReverse.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fReverse, ["payment_id"])) {
      showToast("Select a payment to reverse.", "error"); return;
    }
    openConfirm("⚠ Reverse Payment", "This will REVERSE the selected payment and restore all balances. This cannot be undone.", async () => {
      const btn = fReverse.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const pid = getVal(fReverse, "payment_id");
        const body = await apiPost(`/api/payments/${pid}/reverse/`, {
          reason: getVal(fReverse, "reason") || "Payment reversal",
        });
        showToast(`Reversal ${body.number} posted.`, "success");
        fReverse.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 8. Issue Raw to Grinding ──────────────────────────────────────────────────
const fIssueGrinding = document.getElementById("f-issue-grinding");
if (fIssueGrinding) {
  fIssueGrinding.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fIssueGrinding, ["raw_batch","powder_product","issued_quantity","expected_output_quantity"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    const batchText = fIssueGrinding.elements.raw_batch.options[fIssueGrinding.elements.raw_batch.selectedIndex]?.text || "";
    openConfirm("Confirm Issue to Grinding", `Issue ${getNum(fIssueGrinding,"issued_quantity")} kg from batch "${batchText}" to grinding? Stock will be deducted.`, async () => {
      const btn = fIssueGrinding.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const bid = getVal(fIssueGrinding, "raw_batch");
        const body = await apiPost(`/api/stock-batches/${bid}/issue_to_grinding/`, {
          powder_product: getVal(fIssueGrinding, "powder_product"),
          issued_quantity: getNum(fIssueGrinding, "issued_quantity"),
          expected_output_quantity: getNum(fIssueGrinding, "expected_output_quantity"),
        });
        showToast(`Production order ${body.production_order} created.`, "success");
        fIssueGrinding.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 9. Receive Powder Output ──────────────────────────────────────────────────
const fReceivePowder = document.getElementById("f-receive-powder");
if (fReceivePowder) {
  fReceivePowder.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fReceivePowder, ["production_order","actual_output_quantity","powder_batch_number"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    openConfirm("Confirm Powder Receipt", "Receive powder output? Wastage will be calculated from issued vs output.", async () => {
      const btn = fReceivePowder.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const body = await apiPost("/api/receive-powder/", {
          production_order: getVal(fReceivePowder, "production_order"),
          actual_output_quantity: getNum(fReceivePowder, "actual_output_quantity"),
          wastage_quantity: getNum(fReceivePowder, "wastage_quantity", "0"),
          powder_batch_number: getVal(fReceivePowder, "powder_batch_number"),
          expiry_date: getVal(fReceivePowder, "expiry_date"),
        });
        showToast(`Powder batch ${body.powder_batch} received.`, "success");
        fReceivePowder.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 10. Complete Packing ─────────────────────────────────────────────────────
const fPacking = document.getElementById("f-complete-packing");
if (fPacking) {
  fPacking.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fPacking, ["bom","powder_batch","completed_units","finished_batch_number"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    openConfirm("Confirm Packing Completion", "Mark packing order as complete? Finished goods stock will be created.", async () => {
      const btn = fPacking.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const bomId = getVal(fPacking, "bom");
        const pkgProduct = getVal(fPacking, "packaging_product");
        const pkgBatch   = getVal(fPacking, "packaging_batch");
        const body = await apiPost(`/api/boms/${bomId}/complete_packing/`, {
          powder_batch: getVal(fPacking, "powder_batch"),
          completed_units: getNum(fPacking, "completed_units"),
          wastage_units: getNum(fPacking, "wastage_units", "0"),
          finished_batch_number: getVal(fPacking, "finished_batch_number"),
          packaging_batches: pkgProduct && pkgBatch ? [{ product: pkgProduct, batch: pkgBatch }] : [],
        });
        showToast(`Packing order ${body.packing_order} — batch ${body.finished_batch} created.`, "success");
        fPacking.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 11. Stock Adjustment ─────────────────────────────────────────────────────
const fStockAdj = document.getElementById("f-stock-adjustment");
if (fStockAdj) {
  fStockAdj.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fStockAdj, ["batch_id","counted_quantity"])) {
      showToast("Select batch and enter counted quantity.", "error"); return;
    }
    openConfirm("Confirm Stock Adjustment", "Post stock adjustment? The batch quantity will be updated to match physical count.", async () => {
      const btn = fStockAdj.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const bid = getVal(fStockAdj, "batch_id");
        const body = await apiPost(`/api/stock-batches/${bid}/stock_adjustment/`, {
          counted_quantity: getNum(fStockAdj, "counted_quantity"),
          reason: getVal(fStockAdj, "reason") || "Stock adjustment",
        });
        showToast(`Adjustment ${body.number} posted.`, "success");
        fStockAdj.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 12. Debit Note ───────────────────────────────────────────────────────────
const fDebitNote = document.getElementById("f-debit-note");
if (fDebitNote) {
  fDebitNote.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fDebitNote, ["supplier","amount"])) {
      showToast("Fill required fields.", "error"); return;
    }
    openConfirm("Confirm Debit Note", "Post debit note against supplier? This reduces supplier payable.", async () => {
      const btn = fDebitNote.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const body = await apiPost("/api/adjustments/debit-note/", {
          supplier: getVal(fDebitNote, "supplier"),
          invoice: getVal(fDebitNote, "invoice"),
          amount: getNum(fDebitNote, "amount"),
          reason: getVal(fDebitNote, "reason") || "Debit note",
        });
        showToast(`Debit note ${body.number} posted.`, "success");
        fDebitNote.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── 13. Credit Note ──────────────────────────────────────────────────────────
const fCreditNote = document.getElementById("f-credit-note");
if (fCreditNote) {
  fCreditNote.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validateRequired(fCreditNote, ["supplier","amount","balance_effect"])) {
      showToast("Fill required fields including balance effect.", "error"); return;
    }
    openConfirm("Confirm Credit Note", "Post credit note? Review balance effect carefully before proceeding.", async () => {
      const btn = fCreditNote.querySelector("button[type=submit]");
      setBtnLoading(btn, true);
      try {
        const body = await apiPost("/api/adjustments/credit-note/", {
          supplier: getVal(fCreditNote, "supplier"),
          invoice: getVal(fCreditNote, "invoice"),
          amount: getNum(fCreditNote, "amount"),
          balance_effect: getVal(fCreditNote, "balance_effect"),
          reason: getVal(fCreditNote, "reason") || "Credit note",
        });
        showToast(`Credit note ${body.number} posted.`, "success");
        fCreditNote.reset(); delayedReload();
      } catch (err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── Report runner ─────────────────────────────────────────────────────────────
const fReport = document.getElementById("f-report");
const reportOutput = document.getElementById("report-output");

if (fReport) {
  fReport.addEventListener("submit", async (e) => {
    e.preventDefault();
    const reportName = getVal(fReport, "report_name");
    if (!reportName) { showToast("Select a report.", "error"); return; }

    const params = new URLSearchParams();
    ["date_from","date_to","supplier","warehouse","product","quantity"].forEach(k => {
      const v = getVal(fReport, k);
      if (v) params.set(k, v);
    });
    if (fReport.elements.include_blocked?.checked) params.set("include_blocked","1");
    if (fReport.elements.include_expired?.checked) params.set("include_expired","1");

    const btn = fReport.querySelector("button[type=submit]");
    const exportBtn = document.getElementById("btn-export-csv");
    setBtnLoading(btn, true);
    if (reportOutput) reportOutput.innerHTML = '<div class="empty-state"><span class="spinner"></span><p>Loading report…</p></div>';

    try {
      const data = await apiGet(`/api/reports/${reportName}/?${params.toString()}&limit=500`);
      renderReport(data, reportName);
      if (exportBtn) {
        exportBtn.onclick = () => {
          window.location.href = `/api/reports/${reportName}/?${params.toString()}&export=csv`;
        };
        exportBtn.style.display = "";
      }
    } catch (err) {
      showToast(err.message, "error");
      if (reportOutput) reportOutput.innerHTML = `<div class="empty-state"><p class="text-muted">${err.message}</p></div>`;
    } finally { setBtnLoading(btn, false); }
  });
}

function renderReport(data, name) {
  if (!reportOutput) return;
  const rows = data.rows || [];
  if (!rows.length) {
    reportOutput.innerHTML = '<div class="empty-state"><span class="empty-icon">📊</span><p>No data found for the selected filters.</p></div>';
    return;
  }
  const cols = Object.keys(rows[0]);
  const numCols = new Set(cols.filter(c => typeof rows[0][c] === "number" || /amount|cost|value|qty|quantity|balance|payable|advance|effect/.test(c)));
  let html = '<div class="table-wrapper"><table class="data-table"><thead><tr>';
  cols.forEach(c => { html += `<th>${c.replace(/_/g," ").replace(/\b\w/g,l=>l.toUpperCase())}</th>`; });
  html += "</tr></thead><tbody>";
  rows.forEach(row => {
    html += "<tr>";
    cols.forEach(c => {
      const v = row[c];
      const cls = numCols.has(c) ? " num" : "";
      const disp = v === null || v === undefined ? "" : typeof v === "number" ? Number(v).toLocaleString("en-PK", {minimumFractionDigits:2,maximumFractionDigits:3}) : v;
      html += `<td class="${cls}">${disp}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table></div>";
  // Totals
  if (data.totals && Object.keys(data.totals).length) {
    html += '<div class="report-totals">';
    Object.entries(data.totals).forEach(([k,v]) => {
      html += `<span>${k.replace(/_/g," ")}: <strong>${typeof v==="number"?v.toLocaleString("en-PK",{minimumFractionDigits:2}):v}</strong></span>`;
    });
    if (data.pagination) html += `<span>Showing ${rows.length} of ${data.pagination.total_rows} rows</span>`;
    html += "</div>";
  }
  reportOutput.innerHTML = html;
}

// ── Dynamic invoice list when supplier is selected ────────────────────────────
function wireSupplierInvoiceFilter(supplierSelectId, invoiceSelectId) {
  const supEl = document.getElementById(supplierSelectId);
  const invEl = document.getElementById(invoiceSelectId);
  if (!supEl || !invEl) return;
  supEl.addEventListener("change", async () => {
    const sid = supEl.value;
    invEl.innerHTML = '<option value="">— loading… —</option>';
    if (!sid) { invEl.innerHTML = '<option value="">— select supplier first —</option>'; return; }
    try {
      const data = await apiGet(`/api/invoices/?supplier=${sid}&limit=50`);
      const items = data.results || (Array.isArray(data) ? data : []);
      invEl.innerHTML = '<option value="">— select invoice —</option>';
      items.forEach(inv => {
        invEl.innerHTML += `<option value="${inv.id}">${inv.number} — ${inv.amount} (${inv.status})</option>`;
      });
    } catch { invEl.innerHTML = '<option value="">— could not load invoices —</option>'; }
  });
}
wireSupplierInvoiceFilter("pay-invoice-supplier", "pay-invoice-invoice");
wireSupplierInvoiceFilter("adj-advance-supplier", "adj-advance-invoice");
wireSupplierInvoiceFilter("debit-note-supplier", "debit-note-invoice");
wireSupplierInvoiceFilter("credit-note-supplier", "credit-note-invoice");

// ── Dynamic payment list for reversal ────────────────────────────────────────
const revSupEl = document.getElementById("reverse-payment-supplier");
const revPayEl = document.getElementById("reverse-payment-id");
if (revSupEl && revPayEl) {
  revSupEl.addEventListener("change", async () => {
    const sid = revSupEl.value;
    revPayEl.innerHTML = '<option value="">— loading… —</option>';
    if (!sid) { revPayEl.innerHTML = '<option value="">— select supplier first —</option>'; return; }
    try {
      const data = await apiGet(`/api/payments/?supplier=${sid}&limit=50`);
      const items = data.results || (Array.isArray(data) ? data : []);
      revPayEl.innerHTML = '<option value="">— select payment —</option>';
      items.filter(p=>p.status!=="reversed").forEach(p => {
        revPayEl.innerHTML += `<option value="${p.id}">${p.number} — ${p.payment_type} — ${p.amount}</option>`;
      });
    } catch { revPayEl.innerHTML = '<option value="">— could not load payments —</option>'; }
  });
}

// ── Supplier opening balance ──────────────────────────────────────────────────
const fSupOpPayable = document.getElementById("f-supplier-opening-payable");
if (fSupOpPayable) {
  fSupOpPayable.addEventListener("submit", e => {
    e.preventDefault();
    if (!validateRequired(fSupOpPayable,["supplier","amount"])) { showToast("Fill required fields.","error"); return; }
    openConfirm("Post Opening Payable","Post opening payable balance for this supplier?", async()=>{
      const btn=fSupOpPayable.querySelector("button[type=submit]"); setBtnLoading(btn,true);
      try {
        const sid=getVal(fSupOpPayable,"supplier");
        const body=await apiPost(`/api/suppliers/${sid}/post_opening_payable/`,{amount:getNum(fSupOpPayable,"amount")});
        showToast(`Opening balance ${body.opening_balance} posted.`,"success");
        fSupOpPayable.reset(); delayedReload();
      } catch(err){showToast(err.message,"error");} finally{setBtnLoading(btn,false);}
    });
  });
}

const fSupOpAdvance = document.getElementById("f-supplier-opening-advance");
if (fSupOpAdvance) {
  fSupOpAdvance.addEventListener("submit", e => {
    e.preventDefault();
    if (!validateRequired(fSupOpAdvance,["supplier","amount"])) { showToast("Fill required fields.","error"); return; }
    openConfirm("Post Opening Advance","Post opening advance balance for this supplier?", async()=>{
      const btn=fSupOpAdvance.querySelector("button[type=submit]"); setBtnLoading(btn,true);
      try {
        const sid=getVal(fSupOpAdvance,"supplier");
        const body=await apiPost(`/api/suppliers/${sid}/post_opening_advance/`,{amount:getNum(fSupOpAdvance,"amount")});
        showToast(`Opening advance ${body.opening_balance} posted.`,"success");
        fSupOpAdvance.reset(); delayedReload();
      } catch(err){showToast(err.message,"error");} finally{setBtnLoading(btn,false);}
    });
  });
}

// ── Cash/bank opening ────────────────────────────────────────────────────────
const fCashOpening = document.getElementById("f-cash-opening");
if (fCashOpening) {
  fCashOpening.addEventListener("submit", e => {
    e.preventDefault();
    if (!validateRequired(fCashOpening,["account","amount"])) { showToast("Fill required fields.","error"); return; }
    openConfirm("Post Cash/Bank Opening","Post opening balance for this account?", async()=>{
      const btn=fCashOpening.querySelector("button[type=submit]"); setBtnLoading(btn,true);
      try {
        const aid=getVal(fCashOpening,"account");
        const body=await apiPost(`/api/cash-bank-accounts/${aid}/post_opening/`,{amount:getNum(fCashOpening,"amount")});
        showToast(`Opening balance posted. Account balance: ${body.account_balance}.`,"success");
        fCashOpening.reset(); delayedReload();
      } catch(err){showToast(err.message,"error");} finally{setBtnLoading(btn,false);}
    });
  });
}

// ── Print receipt quick-link ──────────────────────────────────────────────────
const fPrintReceipt = document.getElementById("f-print-receipt");
if (fPrintReceipt) {
  fPrintReceipt.addEventListener("submit", e => {
    e.preventDefault();
    const pid = getVal(fPrintReceipt, "payment_id_print");
    if (!pid) { showToast("Select a payment.", "error"); return; }
    window.open(`/api/payments/${pid}/printable-receipt/`, "_blank");
  });
}

console.info("AuraFoods ERP console loaded.");

// ── Opening Stock ─────────────────────────────────────────────────────────────
const fOpeningStock = document.getElementById("f-opening-stock");
if (fOpeningStock) {
  fOpeningStock.addEventListener("submit", e => {
    e.preventDefault();
    const prod = fOpeningStock.elements.product?.options[fOpeningStock.elements.product.selectedIndex]?.text || "";
    if (!validateRequired(fOpeningStock, ["product","warehouse","batch_number","quantity","unit_cost"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    openConfirm("Post Opening Stock", `Post opening stock for ${prod}? This creates a batch and a stock ledger entry that cannot be duplicated.`, async () => {
      const btn = fOpeningStock.querySelector("button[type=submit]"); setBtnLoading(btn, true);
      try {
        const data = {};
        ["product","warehouse","supplier","batch_number","quantity","unit_cost","expiry_date","manufacturing_date","remarks"].forEach(k => {
          const v = getVal(fOpeningStock, k);
          if (v) data[k] = v;
        });
        const body = await apiPost("/api/opening-stock/", data);
        showToast(`Opening stock batch ${body.batch_number} posted (qty ${body.quantity}).`, "success");
        fOpeningStock.reset(); delayedReload();
      } catch(err) { showToast(err.message, "error"); }
      finally { setBtnLoading(btn, false); }
    });
  });
}

// ── Create Recipe ─────────────────────────────────────────────────────────────
const fCreateRecipe = document.getElementById("f-create-recipe");
if (fCreateRecipe) {
  fCreateRecipe.addEventListener("submit", async e => {
    e.preventDefault();
    if (!validateRequired(fCreateRecipe, ["code","name","finished_product","standard_batch_size","batch_unit","effective_date"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    const btn = fCreateRecipe.querySelector("button[type=submit]"); setBtnLoading(btn, true);
    try {
      const data = Object.fromEntries(new FormData(fCreateRecipe).entries());
      data.is_confidential = fCreateRecipe.elements.is_confidential?.checked ? true : false;
      data.status = "draft";
      await apiPost("/api/recipes/", data);
      showToast("Recipe created. Go to Django Admin to add ingredients and activate.", "success");
      fCreateRecipe.reset(); delayedReload();
    } catch(err) { showToast(err.message, "error"); }
    finally { setBtnLoading(btn, false); }
  });
}

// ── Create Purchase Requirement ───────────────────────────────────────────────
const fCreateReq = document.getElementById("f-create-requirement");
if (fCreateReq) {
  fCreateReq.addEventListener("submit", async e => {
    e.preventDefault();
    if (!validateRequired(fCreateReq, ["product","required_quantity","source"])) {
      showToast("Fill all required fields.", "error"); return;
    }
    const btn = fCreateReq.querySelector("button[type=submit]"); setBtnLoading(btn, true);
    try {
      const data = Object.fromEntries(new FormData(fCreateReq).entries());
      data.status = "draft";
      await apiPost("/api/purchase-requirements/", data);
      showToast("Purchase requirement raised.", "success");
      fCreateReq.reset(); delayedReload();
    } catch(err) { showToast(err.message, "error"); }
    finally { setBtnLoading(btn, false); }
  });
}

// New-domain forms share the same accessible loading, error, and confirmation behavior.
document.querySelectorAll("form[data-json-form]").forEach(form => {
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    openConfirm(
      "Confirm submission",
      "Review the selected business references and values before continuing.",
      async () => {
        const button = form.querySelector("button[type='submit']");
        setBtnLoading(button, true);
        const payload = Object.fromEntries(new FormData(form).entries());
        Object.keys(payload).forEach(key => {
          if (payload[key] === "") delete payload[key];
        });
        try {
          await apiRequest(form.dataset.endpoint, payload, form.dataset.method || "POST");
          showToast("Saved successfully.", "success");
          form.reset();
          delayedReload();
        } catch (error) {
          showToast(error.message, "error");
        } finally {
          setBtnLoading(button, false);
        }
      },
      false,
    );
  });
});

document.querySelectorAll("[data-confirm-post]").forEach(button => {
  button.addEventListener("click", () => {
    openConfirm(
      button.dataset.confirmTitle || "Confirm action",
      "This action is permission-controlled and will be recorded in the audit trail or job log.",
      async () => {
        setBtnLoading(button, true);
        try {
          await apiPost(button.dataset.confirmPost, {});
          showToast("Action completed successfully.", "success");
          delayedReload();
        } catch (error) {
          showToast(error.message, "error");
        } finally {
          setBtnLoading(button, false);
        }
      },
      true,
    );
  });
});

const productionLogDate = document.querySelector("#f-production-log input[name='log_date']");
if (productionLogDate && !productionLogDate.value) {
  productionLogDate.value = new Date().toISOString().slice(0, 10);
}

const currentFilters = new URLSearchParams(window.location.search);
document.querySelectorAll(".filter-toolbar select[name]").forEach(select => {
  const selectedValue = currentFilters.get(select.name);
  if (selectedValue !== null) select.value = selectedValue;
});

// Stock and master-data forms use the same CSP-safe external script as all P0 workflows.
function wireStockForm(formId, actionFn, requiredFields) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!validateRequired(form, requiredFields)) {
      showToast("Fill all required fields.", "error");
      return;
    }
    openConfirm(
      "Confirm Stock Operation",
      "Post this stock operation? It will update batch quantities and create a ledger entry.",
      async () => {
        const button = form.querySelector("button[type='submit']");
        setBtnLoading(button, true);
        try {
          const body = await actionFn(form, getVal(form, "batch_id"));
          showToast(`Posted: ${body.number || body.document || "operation completed"}.`, "success");
          form.reset();
          delayedReload(1200);
        } catch (error) {
          showToast(error.message, "error");
        } finally {
          setBtnLoading(button, false);
        }
      },
    );
  });
}

wireStockForm("f-physical-count", (form, batchId) => apiPost(`/api/stock-batches/${batchId}/physical_count/`, {
  counted_quantity: getNum(form, "counted_quantity"), reason: getVal(form, "reason") || "Physical count",
}), ["batch_id", "counted_quantity", "reason"]);
wireStockForm("f-supplier-return", (form, batchId) => apiPost(`/api/stock-batches/${batchId}/supplier_return/`, {
  quantity: getNum(form, "quantity"), amount: getNum(form, "amount", "0"),
  reason: getVal(form, "reason") || "Supplier return", invoice: getVal(form, "invoice") || null,
}), ["batch_id", "quantity", "reason"]);
wireStockForm("f-repack", (form, batchId) => apiPost(`/api/stock-batches/${batchId}/repack/`, {
  quantity: getNum(form, "quantity"), finished_product: getVal(form, "finished_product"),
  new_batch_number: getVal(form, "new_batch_number"), loss_quantity: getNum(form, "loss_quantity", "0"),
  reason: getVal(form, "reason") || "Repacking",
}), ["batch_id", "quantity", "finished_product", "new_batch_number", "reason"]);
wireStockForm("f-relabel", (form, batchId) => apiPost(`/api/stock-batches/${batchId}/relabel/`, {
  new_label_version: getVal(form, "new_label_version"), reason: getVal(form, "reason") || "Relabeling",
}), ["batch_id", "new_label_version", "reason"]);
wireStockForm("f-rework", (form, batchId) => apiPost(`/api/stock-batches/${batchId}/rework/`, {
  input_quantity: getNum(form, "input_quantity"), output_product: getVal(form, "output_product"),
  output_quantity: getNum(form, "output_quantity"), output_batch_number: getVal(form, "output_batch_number"),
  reason: getVal(form, "reason") || "Rework",
}), ["batch_id", "input_quantity", "output_product", "output_quantity", "output_batch_number", "reason"]);

function wireMasterForm(formId, endpoint) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const button = form.querySelector("button[type='submit']");
    setBtnLoading(button, true);
    const payload = Object.fromEntries(new FormData(form).entries());
    Object.keys(payload).forEach(key => { if (payload[key] === "") delete payload[key]; });
    try {
      await apiPost(endpoint, payload);
      showToast("Created successfully.", "success");
      form.reset();
      delayedReload(1200);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setBtnLoading(button, false);
    }
  });
}

wireMasterForm("f-create-supplier", "/api/suppliers/");
wireMasterForm("f-create-product", "/api/products/");
wireMasterForm("f-create-warehouse", "/api/warehouses/");
wireMasterForm("f-create-account", "/api/cash-bank-accounts/");
wireMasterForm("f-create-uom", "/api/units-of-measure/");
