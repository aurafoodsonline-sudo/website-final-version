from django.contrib import admin

from . import models


class ReadOnlySalesAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.CatalogVariantMapping)
class CatalogMappingAdmin(admin.ModelAdmin):
    list_display = ("variant", "erp_product", "is_active", "public_stock_visibility")
    list_filter = ("is_active", "public_stock_visibility")
    search_fields = ("variant__sku", "erp_product__code", "erp_product__name")


@admin.register(models.SalesOrder)
class SalesOrderAdmin(ReadOnlySalesAdmin):
    list_display = ("number", "customer", "order_date", "channel", "status", "total")
    list_filter = ("status", "channel", "order_date")
    search_fields = ("number", "customer__code", "customer__business_name", "shop_order__reference")


@admin.register(models.SalesInvoice)
class SalesInvoiceAdmin(ReadOnlySalesAdmin):
    list_display = ("number", "customer", "invoice_date", "due_date", "amount", "status")
    list_filter = ("status", "invoice_date", "due_date")


for model in (
    models.CustomerAccountProfile, models.SalesOrderLine, models.SalesStockReservation,
    models.SalesInvoiceLine, models.CustomerPayment, models.CustomerPaymentAllocation,
    models.CustomerLedgerEntry, models.DeliveryChallan, models.DeliveryChallanLine,
    models.DispatchAllocation, models.SalesReturn, models.SalesReturnLine, models.Refund,
    models.DeliveryStatusLog, models.CustomerCreditNote, models.CustomerDebitNote,
):
    admin.site.register(model, ReadOnlySalesAdmin)
