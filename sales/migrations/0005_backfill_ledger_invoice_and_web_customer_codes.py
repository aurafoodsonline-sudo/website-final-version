from django.db import migrations


def backfill_ledger_invoices(apps, schema_editor):
    Ledger = apps.get_model("sales", "CustomerLedgerEntry")
    Invoice = apps.get_model("sales", "SalesInvoice")
    Payment = apps.get_model("sales", "CustomerPayment")
    SalesReturn = apps.get_model("sales", "SalesReturn")
    Refund = apps.get_model("sales", "Refund")
    CreditNote = apps.get_model("sales", "CustomerCreditNote")
    DebitNote = apps.get_model("sales", "CustomerDebitNote")

    direct = {invoice.number: invoice.pk for invoice in Invoice.objects.all().only("pk", "number")}
    for entry in Ledger.objects.filter(invoice__isnull=True).iterator():
        invoice_id = None
        if entry.reference_type in {"sales_invoice", "sales_invoice_cancellation"}:
            invoice_id = direct.get(entry.reference_number)
        elif entry.reference_type == "customer_payment":
            payment = Payment.objects.filter(number=entry.reference_number).first()
            if payment:
                allocation = payment.allocations.order_by("pk").first()
                invoice_id = allocation.invoice_id if allocation else None
        elif entry.reference_type == "sales_return":
            sales_return = SalesReturn.objects.filter(number=entry.reference_number).select_related("order").first()
            if sales_return:
                invoice_id = Invoice.objects.filter(order_id=sales_return.order_id).values_list("pk", flat=True).first()
        elif entry.reference_type == "refund":
            refund = Refund.objects.filter(number=entry.reference_number).first()
            if refund:
                invoice_id = Invoice.objects.filter(order_id=refund.order_id).values_list("pk", flat=True).first()
        elif entry.reference_type == "customer_credit_note":
            note = CreditNote.objects.filter(number=entry.reference_number).first()
            if note and note.order_id:
                invoice_id = Invoice.objects.filter(order_id=note.order_id).values_list("pk", flat=True).first()
        elif entry.reference_type == "customer_debit_note":
            note = DebitNote.objects.filter(number=entry.reference_number).first()
            if note and note.order_id:
                invoice_id = Invoice.objects.filter(order_id=note.order_id).values_list("pk", flat=True).first()
        if invoice_id:
            Ledger.objects.filter(pk=entry.pk).update(invoice_id=invoice_id)


def normalize_web_customer_codes(apps, schema_editor):
    Profile = apps.get_model("sales", "CustomerAccountProfile")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    Customer = apps.get_model("erp", "CustomerDistributor")

    for profile in Profile.objects.select_related("customer").iterator():
        expected = f"WEB-U-{profile.user_id}"
        if profile.customer.code == f"WEB-{profile.user_id}" and not Customer.objects.filter(code=expected).exclude(pk=profile.customer_id).exists():
            Customer.objects.filter(pk=profile.customer_id).update(code=expected)

    profiled_customer_ids = set(Profile.objects.values_list("customer_id", flat=True))
    for order in SalesOrder.objects.select_related("shop_order", "customer").exclude(customer_id__in=profiled_customer_ids).iterator():
        expected = f"WEB-G-{order.shop_order_id}"
        if order.customer.code.startswith("WEB-") and not Customer.objects.filter(code=expected).exclude(pk=order.customer_id).exists():
            Customer.objects.filter(pk=order.customer_id).update(code=expected)


class Migration(migrations.Migration):
    dependencies = [("sales", "0004_customerledgerentry_invoice_and_more")]

    operations = [
        migrations.RunPython(backfill_ledger_invoices, migrations.RunPython.noop),
        migrations.RunPython(normalize_web_customer_codes, migrations.RunPython.noop),
    ]
