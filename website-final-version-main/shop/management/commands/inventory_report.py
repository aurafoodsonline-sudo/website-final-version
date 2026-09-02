from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum
from django.utils import timezone

from erp.models import Product, StockBatch, StockLedgerEntry
from sales.models import SalesStockReservation


class Command(BaseCommand):
    help = "Print the ERP-backed finished-goods inventory operations report."

    def add_arguments(self, parser):
        parser.add_argument("--expiry-days", type=int, default=45)
        parser.add_argument("--movement-limit", type=int, default=10)

    def handle(self, *args, **options):
        today = timezone.localdate()
        expiry_days = max(options["expiry_days"], 0)
        movement_limit = max(options["movement_limit"], 0)
        cutoff = today + timedelta(days=expiry_days)

        products = list(
            Product.objects.filter(product_type=Product.ProductType.FINISHED)
            .annotate(
                on_hand=Sum(
                    "stockbatch__quantity_on_hand",
                    filter=Q(
                        stockbatch__batch_type=StockBatch.BatchType.FINISHED,
                        stockbatch__stock_state=StockBatch.StockState.ACCEPTED,
                        stockbatch__is_blocked=False,
                    ) & (Q(stockbatch__expiry_date__isnull=True) | Q(stockbatch__expiry_date__gte=today)),
                )
            )
            .order_by("name", "code")
        )
        reserved = {
            row["batch__product_id"]: row["total"]
            for row in SalesStockReservation.objects.filter(
                status=SalesStockReservation.Status.ACTIVE,
                batch__product__product_type=Product.ProductType.FINISHED,
            )
            .values("batch__product_id")
            .annotate(total=Sum("quantity"))
        }
        for product in products:
            product.available_quantity = max(
                Decimal("0.000"), (product.on_hand or Decimal("0.000")) - reserved.get(product.pk, Decimal("0.000"))
            )

        low_stock = [p for p in products if p.is_active and p.available_quantity <= p.minimum_stock]
        inactive_or_dead = [p for p in products if not p.is_active or p.available_quantity == 0]
        base_batches = StockBatch.objects.select_related("product", "warehouse").filter(
            batch_type=StockBatch.BatchType.FINISHED,
            quantity_on_hand__gt=0,
        )
        expiring = list(base_batches.filter(expiry_date__range=(today, cutoff)).order_by("expiry_date", "batch_number"))
        expired = list(base_batches.filter(expiry_date__lt=today).order_by("expiry_date", "batch_number"))
        movements = list(
            StockLedgerEntry.objects.select_related("product", "batch", "warehouse")
            .filter(product__product_type=Product.ProductType.FINISHED)
            .order_by("-created_at", "-id")[:movement_limit]
        )

        self.stdout.write("Aura Foods ERP Finished-Goods Inventory Report")
        self.stdout.write(f"Report date: {today.isoformat()}")
        self.stdout.write(f"Expiry window: {expiry_days} days\n")
        self._write_products("LOW STOCK FINISHED SKUS", low_stock)
        self._write_batches("EXPIRING ERP BATCHES", expiring)
        self._write_batches("EXPIRED ERP BATCHES", expired)
        self._write_products("INACTIVE / ZERO-AVAILABLE FINISHED SKUS", inactive_or_dead)
        self._write_movements("RECENT ERP STOCK MOVEMENTS", movements)

    def _write_products(self, title, products):
        self.stdout.write(f"{title} ({len(products)})")
        if not products:
            self.stdout.write("  None\n")
            return
        for product in products:
            self.stdout.write(
                f"  {product.code} | {product.name} | available={product.available_quantity} | "
                f"minimum={product.minimum_stock} | active={product.is_active}"
            )
        self.stdout.write("")

    def _write_batches(self, title, batches):
        self.stdout.write(f"{title} ({len(batches)})")
        if not batches:
            self.stdout.write("  None\n")
            return
        for batch in batches:
            self.stdout.write(
                f"  {batch.batch_number} | {batch.product.code} | {batch.product.name} | "
                f"expiry={batch.expiry_date.isoformat()} | on_hand={batch.quantity_on_hand} | "
                f"state={batch.stock_state} | blocked={batch.is_blocked}"
            )
        self.stdout.write("")

    def _write_movements(self, title, movements):
        self.stdout.write(f"{title} ({len(movements)})")
        if not movements:
            self.stdout.write("  None\n")
            return
        for movement in movements:
            sign = "-" if movement.direction == StockLedgerEntry.Direction.OUT else "+"
            self.stdout.write(
                f"  {movement.created_at:%Y-%m-%d %H:%M} | {movement.product.code} | "
                f"batch={movement.batch.batch_number} | direction={movement.direction} | "
                f"quantity={sign}{movement.quantity} | "
                f"ref={movement.source_document_type}:{movement.source_document_number}"
            )
        self.stdout.write("")
