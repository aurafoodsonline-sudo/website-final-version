from __future__ import annotations

from decimal import DecimalException

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler
import logging

logger = logging.getLogger("erp.api")


def api_exception_handler(exc, context):
    """
    Custom DRF exception handler.
    Converts Django-layer exceptions to clean API responses.
    No invalid object ID may produce an unhandled 500 error.
    """
    response = exception_handler(exc, context)
    if response is not None:
        return response

    if isinstance(exc, DjangoValidationError):
        return Response({"detail": exc.messages}, status=400)

    if isinstance(exc, ObjectDoesNotExist):
        # e.g. Supplier.objects.get(pk=999) when 999 doesn't exist
        model_name = exc.__class__.__name__.replace("DoesNotExist", "")
        logger.warning("ObjectDoesNotExist in API: %s | %s", model_name, str(exc))
        return Response(
            {"detail": f"The requested {model_name or 'object'} was not found."},
            status=404,
        )

    if isinstance(exc, KeyError):
        return Response({"detail": f"Missing required field: {exc.args[0]}"}, status=400)

    if isinstance(exc, (ValueError, TypeError, DecimalException)):
        return Response({"detail": "Invalid request payload."}, status=400)

    # Log unhandled server errors for diagnostics without leaking details
    logger.error("Unhandled API exception: %s", str(exc), exc_info=True)
    return None
