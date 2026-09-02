from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register("units-of-measure", views.UnitOfMeasureViewSet, basename="unitofmeasure")
router.register("warehouses", views.WarehouseViewSet)
router.register("products", views.ProductViewSet)
router.register("suppliers", views.SupplierViewSet)
router.register("cash-bank-accounts", views.CashBankAccountViewSet)
router.register("purchase-orders", views.PurchaseOrderViewSet)
router.register("purchase-requirements", views.PurchaseRequirementViewSet)
router.register("grns", views.GRNViewSet)
router.register("invoices", views.SupplierInvoiceViewSet, basename="supplierinvoice")
router.register("payments", views.SupplierPaymentViewSet, basename="supplierpayment")
router.register("stock-batches", views.StockBatchViewSet)
router.register("boms", views.PackagingBOMViewSet, basename="packagingbom")
router.register("adjustments", views.AdjustmentDocumentViewSet)
router.register("recipes", views.RecipeViewSet)
router.register("landed-costs", views.LandedCostViewSet, basename="landedcost")
router.register("physical-stock-counts", views.PhysicalStockCountViewSet, basename="physicalstockcount")
router.register("supplier-price-agreements", views.SupplierPriceAgreementViewSet, basename="supplierpriceagreement")
router.register("production-logs", views.DailyProductionLogViewSet, basename="dailyproductionlog")
router.register("customers", views.CustomerDistributorViewSet, basename="customerdistributor")
router.register("customer-shipping-addresses", views.CustomerShippingAddressViewSet, basename="customershippingaddress")
router.register("scheduled-task-configs", views.ScheduledTaskConfigViewSet, basename="scheduledtaskconfig")
router.register("scheduled-task-logs", views.ScheduledTaskLogViewSet, basename="scheduledtasklog")

urlpatterns = [
    path("production/receive-powder/", views.receive_powder, name="receive-powder"),
    path("receive-powder/", views.receive_powder, name="receive-powder-alt"),
    path("opening-stock/", views.opening_stock_view, name="opening-stock"),
    path("reports/<slug:report_name>/", views.report_view, name="report-view"),
    # Report URLs for documentation clarity (handled via reports/<name>/ but listed here)
    # supplier-return: GET /api/reports/supplier-return/
    # grn-cancel: POST /api/grns/{id}/cancel/ (auto-registered by GRNViewSet router)
    # physical-stock-counts: /api/physical-stock-counts/ (registered via router above)
]

urlpatterns += router.urls
