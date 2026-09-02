from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import DeliveryChallanViewSet, SalesInvoiceViewSet, SalesOrderViewSet, SalesReportView, SalesReturnViewSet

router = DefaultRouter()
router.register("orders", SalesOrderViewSet, basename="sales-order")
router.register("invoices", SalesInvoiceViewSet, basename="sales-invoice")
router.register("challans", DeliveryChallanViewSet, basename="delivery-challan")
router.register("returns", SalesReturnViewSet, basename="sales-return")

urlpatterns = router.urls + [path("reports/<slug:report_name>/", SalesReportView.as_view(), name="sales-report")]
