import os
import sys

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from sales.views import (
    commerce_console, commerce_contact_convert, commerce_order_reallocate, commerce_order_transition,
    commerce_refund_action, commerce_return_action, commerce_return_qa_accept,
    commerce_return_qa_reject, commerce_support_convert, commerce_verify_payment,
)
from shop.admin_bootstrap import ensure_admin_user


def _bootstrap_admin_on_startup():
    """Create the initial admin account when the app process starts.

    Skipped under the test runner: this module is imported while the test
    database is being set up, and inserting an "admin" superuser there collides
    with tests that create their own "admin" user. The bootstrap itself is
    exercised directly by shop.tests_admin_bootstrap.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    argv = [a.lower() for a in sys.argv]
    if "test" in argv or any(a == "pytest" or a.endswith("pytest") for a in argv):
        return
    ensure_admin_user()


_bootstrap_admin_on_startup()


def health_check(request):
    return JsonResponse({"status": "ok", "service": "aurafoods-erp"})


urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("erp/", include("frontend.urls")),
    path("commerce-admin/", commerce_console, name="commerce-console"),
    path("commerce-admin/orders/<int:pk>/transition/", commerce_order_transition, name="commerce-order-transition"),
    path("commerce-admin/orders/<int:pk>/reallocate/", commerce_order_reallocate, name="commerce-order-reallocate"),
    path("commerce-admin/payments/<int:pk>/verify/", commerce_verify_payment, name="commerce-payment-verify"),
    path("commerce-admin/returns/<int:pk>/approve/", commerce_return_action, name="commerce-return-approve"),
    path("commerce-admin/sales-returns/<int:pk>/qa-accept/", commerce_return_qa_accept, name="commerce-return-qa"),
    path("commerce-admin/sales-returns/<int:pk>/qa-reject/", commerce_return_qa_reject, name="commerce-return-qa-reject"),
    path("commerce-admin/refunds/<int:pk>/approve/", commerce_refund_action, name="commerce-refund-approve"),
    path("commerce-admin/crm/contact/<int:pk>/convert/", commerce_contact_convert, name="commerce-contact-convert"),
    path("commerce-admin/crm/support/<int:pk>/convert/", commerce_support_convert, name="commerce-support-convert"),
    path("django-admin/", admin.site.urls),
    path("api/sales/", include("sales.urls")),
    path("api/crm/", include("crm.urls")),
    path("api/", include("erp.api_urls")),
    path("store/", include("shop.urls")),
    path("", include("shop.urls")),
]
