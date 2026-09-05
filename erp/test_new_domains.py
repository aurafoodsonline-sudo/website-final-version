from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .domain_reports import (
    customer_master_report,
    daily_production_log_report,
    production_packing_summary_report,
    production_wastage_summary_report,
    scheduled_task_log_report,
    supplier_rate_variance_report,
)
from .domain_services import (
    activate_supplier_price_agreement,
    approve_daily_production_log,
    approve_supplier_price_agreement,
    cancel_supplier_price_agreement,
    calculate_rate_variance,
    evaluate_supplier_rate,
    expire_supplier_price_agreements,
    find_applicable_supplier_price_agreement,
    set_customer_blocked,
    submit_daily_production_log,
    submit_supplier_price_agreement,
)
from .export import rows_to_csv
from .models import (
    CashBankAccount,
    CustomerDistributor,
    DailyProductionLog,
    DocumentState,
    GRNLine,
    PackingOrder,
    PackagingBOM,
    Product,
    ProductionOrder,
    PurchaseOrderLine,
    ScheduledTaskConfig,
    ScheduledTaskLog,
    StockBatch,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierPayment,
    SupplierPriceAgreement,
    UnitOfMeasure,
    Warehouse,
)
from .scheduled_jobs import (
    _run_logged,
    refresh_expiry_statuses,
    refresh_overdue_supplier_invoices,
    run_scheduled_erp_maintenance,
)
from .services import PurchaseLineInput, create_grn, create_purchase_order, post_supplier_invoice


User = get_user_model()


class NewDomainBase(TestCase):
    def setUp(self):
        self.kg = UnitOfMeasure.objects.create(code="KG", name="Kilogram")
        self.unit = UnitOfMeasure.objects.create(code="EA", name="Each", unit_type="count")
        self.warehouse = Warehouse.objects.create(code="MAIN", name="Main")
        self.supplier = Supplier.objects.create(code="SUP-1", name="Primary Supplier")
        self.raw = Product.objects.create(code="RAW-1", name="Raw Chili", product_type="raw", base_unit=self.kg)
        self.packaging = Product.objects.create(code="PKG-1", name="Pouch", product_type="packaging", base_unit=self.unit)
        self.powder = Product.objects.create(code="PWD-1", name="Chili Powder", product_type="powder", base_unit=self.kg)
        self.finished = Product.objects.create(
            code="FG-1", name="Chili 100g", product_type="finished", base_unit=self.unit,
            grammage=Decimal("100"), shelf_life_days=180,
        )
        self.user = User.objects.create_user(username="operator", password="test-pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def grant(self, *codenames):
        content_type = ContentType.objects.get_for_model(Supplier)
        for codename in codenames:
            permission, _ = Permission.objects.get_or_create(
                content_type=content_type,
                codename=codename,
                defaults={"name": f"ERP {codename}"},
            )
            self.user.user_permissions.add(permission)
        for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            if hasattr(self.user, cache_name):
                delattr(self.user, cache_name)

    def agreement(self, *, number="RATE-1", rate="100", status="active", effective=None, expiry=None):
        today = timezone.localdate()
        return SupplierPriceAgreement.objects.create(
            agreement_number=number,
            supplier=self.supplier,
            product=self.raw,
            item_type=SupplierPriceAgreement.ItemType.RAW_SPICE,
            agreed_rate=Decimal(rate),
            currency="PKR",
            unit=self.kg,
            effective_date=effective or today,
            expiry_date=expiry or today + timedelta(days=30),
            tolerance_percentage=Decimal("5"),
            status=status,
            created_by=self.user,
        )


class SupplierPriceAgreementTests(NewDomainBase):
    def test_create_draft_through_api(self):
        self.grant("supplier_rate.create")
        response = self.client.post("/api/supplier-price-agreements/", {
            "supplier": self.supplier.pk,
            "product": self.raw.pk,
            "agreed_rate": "100.0000",
            "unit": self.kg.pk,
            "effective_date": str(timezone.localdate()),
            "expiry_date": str(timezone.localdate() + timedelta(days=30)),
            "rate_type": "fixed",
            "tolerance_percentage": "5.000",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        agreement = SupplierPriceAgreement.objects.get()
        self.assertEqual(agreement.status, "draft")
        self.assertEqual(agreement.item_type, "raw_spice")

    def test_approve_and_activate_workflow(self):
        item = self.agreement(status="draft")
        submit_supplier_price_agreement(agreement=item, user=self.user)
        approve_supplier_price_agreement(agreement=item, user=self.user)
        activated = activate_supplier_price_agreement(agreement=item, user=self.user)
        self.assertEqual(activated.status, "active")
        self.assertEqual(activated.approved_by, self.user)

    def test_unauthorized_user_cannot_approve(self):
        item = self.agreement(status="pending_approval")
        response = self.client.post(f"/api/supplier-price-agreements/{item.pk}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_cancel_requires_approval_permission_and_reason(self):
        item = self.agreement(status="active")
        url = f"/api/supplier-price-agreements/{item.pk}/cancel/"
        self.assertEqual(self.client.post(url, {"reason": "Commercial withdrawal"}, format="json").status_code, 403)
        self.grant("supplier_rate.approve")
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        response = self.client.post(url, {"reason": "Commercial withdrawal"}, format="json")
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.status, "cancelled")

    def test_activation_supersedes_overlapping_rate_and_lookup_uses_new(self):
        old = self.agreement(number="RATE-OLD")
        new = self.agreement(number="RATE-NEW", rate="95", status="approved")
        activate_supplier_price_agreement(agreement=new, user=self.user)
        old.refresh_from_db()
        self.assertEqual(old.status, "superseded")
        self.assertEqual(
            find_applicable_supplier_price_agreement(
                supplier=self.supplier, product=self.raw, unit=self.kg, transaction_date=timezone.localdate()
            ).pk,
            new.pk,
        )

    def test_expiry_and_date_bounded_lookup(self):
        today = timezone.localdate()
        expired = self.agreement(
            number="RATE-EXPIRED", status="active",
            effective=today - timedelta(days=10), expiry=today - timedelta(days=1),
        )
        self.assertEqual(expire_supplier_price_agreements(as_of=today), 1)
        expired.refresh_from_db()
        self.assertEqual(expired.status, "expired")
        self.assertIsNone(find_applicable_supplier_price_agreement(
            supplier=self.supplier, product=self.raw, unit=self.kg, transaction_date=today,
        ))

    def test_variance_and_override_requirement(self):
        self.agreement(rate="100")
        with self.assertRaises(ValidationError):
            evaluate_supplier_rate(supplier=self.supplier, product=self.raw, actual_rate=Decimal("110"))
        result = evaluate_supplier_rate(
            supplier=self.supplier, product=self.raw, actual_rate=Decimal("110"), override_reason="Owner approved"
        )
        self.assertEqual(result["variance_amount"], Decimal("10.0000"))
        self.assertEqual(result["variance_flag"], "unfavorable")

    def test_purchase_order_snapshots_expected_rate(self):
        agreement = self.agreement(rate="100")
        order = create_purchase_order(supplier=self.supplier, lines=[PurchaseLineInput(
            product=self.raw, ordered_quantity=Decimal("10"), received_quantity=Decimal("0"),
            accepted_quantity=Decimal("0"), unit_cost=Decimal("103"), batch_number="",
        )], user=self.user)
        line = PurchaseOrderLine.objects.get(purchase_order=order)
        self.assertEqual(line.rate_agreement, agreement)
        self.assertEqual(line.agreed_rate_snapshot, Decimal("100"))
        self.assertEqual(line.rate_variance_percentage, Decimal("3"))

    def test_grn_invoice_carries_rate_comparison(self):
        agreement = self.agreement(rate="100")
        grn = create_grn(supplier=self.supplier, warehouse=self.warehouse, lines=[PurchaseLineInput(
            product=self.raw, ordered_quantity=Decimal("10"), received_quantity=Decimal("10"),
            accepted_quantity=Decimal("10"), unit_cost=Decimal("102"), batch_number="RAW-B1",
        )], user=self.user)
        invoice = post_supplier_invoice(supplier=self.supplier, amount=Decimal("1020"), grn=grn, user=self.user)
        line = SupplierInvoiceLine.objects.get(invoice=invoice)
        self.assertEqual(line.rate_agreement, agreement)
        self.assertEqual(line.rate_variance_amount, Decimal("2"))

    def test_direct_purchase_api_captures_rate_comparison(self):
        agreement = self.agreement(rate="100")
        self.grant("grn.create")
        response = self.client.post("/api/grns/direct_purchase/", {
            "supplier": self.supplier.pk,
            "warehouse": self.warehouse.pk,
            "lines": [{
                "product": self.raw.pk, "ordered_quantity": "5", "received_quantity": "5",
                "accepted_quantity": "5", "unit_cost": "103", "batch_number": "DIRECT-1",
            }],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        line = GRNLine.objects.get(grn_id=response.data["id"])
        self.assertEqual(line.rate_agreement, agreement)
        self.assertEqual(line.rate_variance_percentage, Decimal("3"))

    def test_variance_report_and_csv_permission(self):
        self.test_purchase_order_snapshots_expected_rate()
        report = supplier_rate_variance_report(
            supplier=self.supplier, item_type="raw_spice", source_type="PO",
            date_from=timezone.localdate(), date_to=timezone.localdate(),
        )
        self.assertEqual(report["totals"]["comparisons"], 1)
        self.grant("report.supplier_rate")
        response = self.client.get("/api/reports/supplier-rate-variance/?export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertEqual(self.client.get("/api/reports/supplier-rate-comparison/").status_code, 200)
        self.assertEqual(
            self.client.get("/api/reports/item-supplier-rate-comparison/?source_type=PO&item_type=raw_spice").status_code,
            200,
        )


class DailyProductionLogTests(NewDomainBase):
    def production_order(self):
        batch = StockBatch.objects.create(
            product=self.raw, batch_number="RAW-PROD", batch_type="raw", warehouse=self.warehouse,
            source_document_type="OPENING", source_document_number="OPEN-1", quantity_on_hand=Decimal("100"),
        )
        return ProductionOrder.objects.create(
            number="PROD-1", raw_batch=batch, powder_product=self.powder, warehouse=self.warehouse,
            issued_quantity=Decimal("50"), expected_output_quantity=Decimal("45"),
            actual_output_quantity=Decimal("44"), wastage_quantity=Decimal("6"), status="approved",
        )

    def log(self, status="draft"):
        return DailyProductionLog.objects.create(
            log_number="PLOG-1", log_date=timezone.localdate(), shift="morning", supervisor=self.user,
            raw_quantity_issued=Decimal("50"), powder_quantity_received=Decimal("45"),
            finished_quantity_packed=Decimal("400"), grinding_wastage_quantity=Decimal("5"),
            packing_wastage_quantity=Decimal("1"), status=status,
        )

    def test_create_log_autosummarizes_linked_production_order(self):
        self.grant("production_log.create")
        order = self.production_order()
        response = self.client.post("/api/production-logs/", {
            "log_date": str(timezone.localdate()), "shift": "morning", "supervisor": self.user.pk,
            "production_order": order.pk, "operator": "Ali",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        log = DailyProductionLog.objects.get()
        self.assertEqual(log.raw_quantity_issued, Decimal("50"))
        self.assertEqual(log.powder_quantity_received, Decimal("44"))
        report = daily_production_log_report(product=self.raw, production_order=order)
        self.assertEqual(report["totals"]["logs"], 1)
        self.assertEqual(report["rows"][0]["planned_output"], Decimal("45"))
        self.assertEqual(report["rows"][0]["output_variance"], Decimal("-1"))
        self.grant("report.production_log")
        response = self.client.get(
            f"/api/reports/operator-production-log/?product={self.raw.pk}&production_order={order.pk}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["totals"]["logs"], 1)

    def test_submit_approve_lock_and_calculations(self):
        item = self.log()
        submit_daily_production_log(production_log=item, user=self.user)
        locked = approve_daily_production_log(production_log=item, user=self.user)
        self.assertEqual(locked.status, "locked")
        self.assertEqual(locked.yield_percentage, Decimal("90.00"))
        self.assertEqual(locked.wastage_percentage, Decimal("12.00"))

    def test_unauthorized_approval_denied(self):
        item = self.log(status="submitted")
        response = self.client.post(f"/api/production-logs/{item.pk}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_locked_log_cannot_be_edited(self):
        self.grant("production_log.create")
        item = self.log(status="locked")
        response = self.client.patch(f"/api/production-logs/{item.pk}/", {"remarks": "changed"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_shift_report_filter(self):
        self.log()
        data = daily_production_log_report(shift="morning")
        self.assertEqual(data["totals"]["logs"], 1)
        self.assertEqual(data["rows"][0]["yield_percentage"], Decimal("90.00"))
        self.assertEqual(daily_production_log_report(shift="night")["rows"], [])

    def test_filtered_summary_totals_reconcile_with_returned_rows(self):
        included = self.log()
        DailyProductionLog.objects.create(
            log_number="PLOG-NO-WASTE", log_date=timezone.localdate(), shift="night", supervisor=self.user,
            raw_quantity_issued=Decimal("20"), powder_quantity_received=Decimal("20"),
        )
        wastage = production_wastage_summary_report()
        self.assertEqual(wastage["totals"]["logs"], len(wastage["rows"]))
        self.assertEqual(wastage["totals"]["logs"], 1)
        self.assertEqual(wastage["totals"]["grinding_wastage"], included.grinding_wastage_quantity)
        packing = production_packing_summary_report()
        self.assertEqual(packing["totals"]["logs"], len(packing["rows"]))
        self.assertEqual(packing["totals"]["finished_quantity_packed"], included.finished_quantity_packed)

    def test_create_log_autosummarizes_linked_packing_order(self):
        self.grant("production_log.create")
        powder_batch = StockBatch.objects.create(
            product=self.powder, batch_number="PWD-PACK", batch_type="powder", warehouse=self.warehouse,
            source_document_type="PRODUCTION", source_document_number="PROD-X", quantity_on_hand=Decimal("50"),
        )
        bom = PackagingBOM.objects.create(
            finished_product=self.finished, powder_product=self.powder,
            powder_quantity_per_unit=Decimal("0.1"), version=1,
        )
        packing = PackingOrder.objects.create(
            number="PACK-1", bom=bom, powder_batch=powder_batch, warehouse=self.warehouse,
            planned_units=Decimal("100"), completed_units=Decimal("95"), wastage_quantity=Decimal("5"),
        )
        response = self.client.post("/api/production-logs/", {
            "log_date": str(timezone.localdate()), "shift": "evening", "supervisor": self.user.pk,
            "packing_order": packing.pk,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        log = DailyProductionLog.objects.get()
        self.assertEqual(log.finished_quantity_packed, Decimal("95"))
        self.assertEqual(log.packing_wastage_quantity, Decimal("5"))


class CustomerDistributorTests(NewDomainBase):
    def customer(self, code="CUS-1", customer_type="retailer"):
        return CustomerDistributor.objects.create(
            code=code, business_name="Metro Foods", customer_type=customer_type,
            sales_channel="retail" if customer_type == "retailer" else "distributor", city="Lahore",
        )

    def test_create_customer_and_duplicate_code_validation(self):
        self.grant("customer.create")
        payload = {
            "code": "CUS-1", "business_name": "Metro Foods", "customer_type": "retailer",
            "sales_channel": "retail", "city": "Lahore", "country": "Pakistan",
        }
        first = self.client.post("/api/customers/", payload, format="json")
        second = self.client.post("/api/customers/", {**payload, "code": "cus-1"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerDistributor.objects.bulk_create([
                CustomerDistributor(
                    code="cus-1", business_name="Duplicate", customer_type="retailer", sales_channel="retail"
                )
            ])

    def test_create_distributor_and_block_unblock(self):
        customer = self.customer(customer_type="distributor")
        self.assertEqual(customer.sales_channel, "distributor")
        set_customer_blocked(customer=customer, blocked=True, user=self.user)
        customer.refresh_from_db()
        self.assertEqual(customer.status, "blocked")
        set_customer_blocked(customer=customer, blocked=False, user=self.user)
        customer.refresh_from_db()
        self.assertEqual(customer.status, "active")

    def test_customer_read_and_block_permissions(self):
        customer = self.customer()
        self.assertEqual(self.client.get("/api/customers/").status_code, 403)
        self.grant("customer.view")
        self.assertEqual(self.client.get("/api/customers/?city=Lahore").status_code, 200)
        self.assertEqual(self.client.post(f"/api/customers/{customer.pk}/block/", {}, format="json").status_code, 403)
        self.assertIn(self.client.get("/api/customers/not-a-number/").status_code, {400, 404})

    def test_customer_deactivate_and_activate_require_edit_permission(self):
        customer = self.customer()
        deactivate_url = f"/api/customers/{customer.pk}/deactivate/"
        self.assertEqual(self.client.post(deactivate_url, {}, format="json").status_code, 403)
        self.grant("customer.edit")
        self.assertEqual(self.client.post(deactivate_url, {}, format="json").status_code, 200)
        customer.refresh_from_db()
        self.assertEqual(customer.status, "inactive")
        self.assertEqual(self.client.post(f"/api/customers/{customer.pk}/activate/", {}, format="json").status_code, 200)
        customer.refresh_from_db()
        self.assertEqual(customer.status, "active")

    def test_unauthorized_create_and_shipping_address_creation(self):
        customer = self.customer()
        self.assertEqual(self.client.post("/api/customers/", {}, format="json").status_code, 403)
        self.grant("customer.create")
        response = self.client.post("/api/customer-shipping-addresses/", {
            "customer": customer.pk,
            "address_label": "Main Warehouse",
            "recipient_contact": "Receiving Desk",
            "address": "Industrial Area",
            "city": "Lahore",
            "country": "Pakistan",
            "is_default": True,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(customer.shipping_addresses.count(), 1)

    def test_customer_report_filter_and_csv(self):
        self.customer()
        self.customer(code="DIS-1", customer_type="distributor")
        report = customer_master_report(customer_type="distributor")
        self.assertEqual(report["totals"]["customers"], 1)
        self.grant("report.customer_master")
        response = self.client.get("/api/reports/customer-master/?export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/reports/blocked-customers/").status_code, 200)
        self.assertEqual(self.client.get("/api/reports/distributor-readiness/").status_code, 200)
        self.assertEqual(self.client.get("/api/reports/customer-by-channel/?sales_channel=retail").status_code, 200)
        self.assertEqual(self.client.get("/api/reports/customer-by-location/?city=Lahore").status_code, 200)


class ScheduledTaskTests(NewDomainBase):
    def batch(self, number, expiry):
        return StockBatch.objects.create(
            product=self.finished, batch_number=number, batch_type="finished", warehouse=self.warehouse,
            source_document_type="PACKING_COMPLETE", source_document_number=number,
            quantity_on_hand=Decimal("10"), expiry_date=expiry,
        )

    def test_expiry_refresh_classifies_and_is_idempotent(self):
        expired = self.batch("EXP", timezone.localdate() - timedelta(days=1))
        near = self.batch("NEAR", timezone.localdate() + timedelta(days=5))
        first = refresh_expiry_statuses()
        second = refresh_expiry_statuses()
        expired.refresh_from_db(); near.refresh_from_db()
        self.assertEqual(expired.expiry_status, "expired")
        self.assertTrue(expired.is_blocked)
        self.assertEqual(near.expiry_status, "near_expiry")
        self.assertIn("expired_blocked=0", second.message)
        self.assertEqual(first.status, "success")

    def test_overdue_refresh_is_idempotent(self):
        invoice = SupplierInvoice.objects.create(
            number="INV-OLD", supplier=self.supplier, invoice_date=timezone.localdate() - timedelta(days=20),
            due_date=timezone.localdate() - timedelta(days=2), amount=Decimal("100"), status=DocumentState.POSTED,
        )
        first = refresh_overdue_supplier_invoices()
        second = refresh_overdue_supplier_invoices()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "overdue")
        self.assertIn("overdue_updated=1", first.message)
        self.assertIn("overdue_updated=0", second.message)

    def test_maintenance_creates_parent_and_child_logs(self):
        log = run_scheduled_erp_maintenance()
        self.assertEqual(log.status, "success")
        self.assertEqual(ScheduledTaskLog.objects.count(), 3)

    def test_disabled_config_is_logged_as_skipped_without_mutation(self):
        batch = self.batch("DISABLED", timezone.localdate() - timedelta(days=1))
        ScheduledTaskConfig.objects.create(
            job_name="refresh_expiry_statuses", enabled=False,
            frequency_description="Daily", command_name="refresh_expiry_statuses",
        )
        log = refresh_expiry_statuses()
        batch.refresh_from_db()
        self.assertEqual(log.status, "skipped")
        self.assertFalse(batch.is_blocked)

    def test_failed_job_is_logged_safely(self):
        with self.assertRaises(RuntimeError):
            _run_logged(
                job_name="failing_test", job_type="other", triggered_by="system",
                operation=lambda: (_ for _ in ()).throw(RuntimeError("safe failure")),
            )
        log = ScheduledTaskLog.objects.get(job_name="failing_test")
        self.assertEqual(log.status, "failed")
        self.assertIn("RuntimeError", log.error_details)

    def test_unauthorized_manual_run_denied(self):
        response = self.client.post("/api/scheduled-task-logs/run-maintenance/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_job_log_report_and_permission(self):
        refresh_expiry_statuses()
        self.assertEqual(scheduled_task_log_report()["totals"]["runs"], 1)
        self.assertEqual(self.client.get("/api/reports/scheduled-task-log/").status_code, 403)
        self.grant("report.scheduled_task")
        self.assertEqual(self.client.get("/api/reports/scheduled-task-log/").status_code, 200)


class SecurityRegressionTests(NewDomainBase):
    def test_csv_export_neutralizes_formula_strings_without_stringifying_numbers(self):
        content = rows_to_csv([
            {"name": "=HYPERLINK(\"https://invalid.example\")", "note": " @SUM(1,1)", "amount": Decimal("-5.25")}
        ])
        self.assertIn("'=HYPERLINK", content)
        self.assertIn("' @SUM(1,1)", content)
        self.assertIn("-5.25", content)

    def test_sensitive_supplier_and_cash_bank_fields_require_finance_permission(self):
        self.supplier.account_number = "PK00-SECRET"
        self.supplier.iban = "PK00-IBAN-SECRET"
        self.supplier.payable_balance = Decimal("1200")
        self.supplier.advance_balance = Decimal("300")
        self.supplier.save()
        account = CashBankAccount.objects.create(
            code="BANK-SEC", name="Restricted Bank", account_type="bank",
            account_number="001122", iban="PK99-SECRET", balance=Decimal("5000"),
        )

        supplier_response = self.client.get("/api/suppliers/")
        self.assertEqual(supplier_response.status_code, 200)
        supplier_row = supplier_response.json()[0]
        for field in ("account_number", "iban", "payable_balance", "advance_balance"):
            self.assertNotIn(field, supplier_row)
        self.assertEqual(self.client.get("/api/cash-bank-accounts/").status_code, 403)

        self.grant("reports.view_financial")
        supplier_row = self.client.get("/api/suppliers/").json()[0]
        self.assertEqual(supplier_row["account_number"], "PK00-SECRET")
        self.assertEqual(supplier_row["payable_balance"], "1200.00")
        cash_response = self.client.get("/api/cash-bank-accounts/")
        self.assertEqual(cash_response.status_code, 200)
        self.assertEqual(cash_response.json()[0]["id"], account.pk)

    def test_supplier_return_report_uses_financial_permission_gate(self):
        url = "/api/reports/supplier-return/"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant("reports.view_inventory")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant("reports.view_financial")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_printable_receipt_is_permission_controlled_escaped_and_csp_safe(self):
        payment = SupplierPayment.objects.create(
            number="PAY-XSS", supplier=self.supplier, payment_type="advance", amount=Decimal("10"),
            reference_number='<img src=x onerror="alert(1)">', reason="<script>alert(1)</script>",
            created_by=self.user,
        )
        url = f"/api/payments/{payment.pk}/printable-receipt/"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant("reports.view_financial")
        self.assertIn(self.client.get("/api/payments/not-a-number/printable-receipt/").status_code, {400, 404})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertNotIn("<img src=x", body)
        self.assertNotIn("onclick=", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertRegex(
            body,
            r'<script src="/static/frontend/receipt(?:\.[0-9a-f]+)?\.js" defer></script>',
        )
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
