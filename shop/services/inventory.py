from django.core.exceptions import ImproperlyConfigured


class InventoryService:
    """Compatibility trap for the retired portal inventory engine.

    Finished-goods availability, reservations, dispatch, cancellation, and
    return stock effects belong to ``sales.services`` and ``erp.services``.
    Keeping these methods fail-closed prevents a future caller from reviving a
    second stock truth while preserving the historical import path.
    """

    @staticmethod
    def _retired(*args, **kwargs):
        raise ImproperlyConfigured(
            "shop.services.inventory is retired; use ERP-backed sales services."
        )

    active_batches = _retired
    allocate_from_batches = _retired
    deduct_stock = _retired
    restore_stock_for_order = _retired
