from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand

from erp.models import Product, StockBatch, UnitOfMeasure, Warehouse
from shop.models import ProductVariant
from sales.models import CatalogVariantMapping


class Command(BaseCommand):
    help = "Seed both source demos and create demo-only ERP mappings/stock for local evaluation."

    def handle(self, *args, **options):
        call_command("seed_aurafoods_demo", verbosity=0)
        call_command("seed", verbosity=0)
        unit, _ = UnitOfMeasure.objects.get_or_create(code="EA", defaults={"name": "Each", "unit_type": "count"})
        warehouse, _ = Warehouse.objects.get_or_create(code="DEMO-FG", defaults={"name": "Demo Finished Goods"})
        mapped = 0
        for variant in ProductVariant.objects.filter(active=True).select_related("product"):
            product, _ = Product.objects.get_or_create(
                code=variant.sku.upper(),
                defaults={
                    "name": f"{variant.product.name} {variant.display_weight}",
                    "product_type": Product.ProductType.FINISHED,
                    "base_unit": unit,
                    "grammage": variant.weight_value if variant.weight_unit == "g" else variant.weight_value * 1000,
                    "mrp": variant.old_price or variant.price,
                    "sale_price": variant.price,
                },
            )
            if product.product_type != Product.ProductType.FINISHED:
                self.stdout.write(self.style.WARNING(f"Skipped non-finished ERP code collision: {variant.sku}"))
                continue
            CatalogVariantMapping.objects.update_or_create(
                variant=variant,
                defaults={"erp_product": product, "display_price": variant.price, "mrp": variant.old_price or None, "is_active": True},
            )
            StockBatch.objects.get_or_create(
                product=product, batch_number="DEMO-SEED", batch_type=StockBatch.BatchType.FINISHED,
                defaults={
                    "warehouse": warehouse, "quantity_on_hand": Decimal("100.000"),
                    "unit_cost": (variant.price * Decimal("0.55")).quantize(Decimal("0.0001")),
                    "source_document_type": "DEMO_SEED", "source_document_number": "LOCAL-DEMO",
                },
            )
            mapped += 1
        self.stdout.write(self.style.SUCCESS(f"Unified demo ready: {mapped} portal variants mapped to ERP finished stock."))
