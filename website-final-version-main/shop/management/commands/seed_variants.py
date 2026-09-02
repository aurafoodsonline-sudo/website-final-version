import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aurafoods_erp.settings')
django.setup()

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from shop.models import Product, ProductVariant
from sales.models import CatalogVariantMapping
from erp.models import Product as ERPProduct

TARGET_WEIGHTS = [
    (100, 'g'),
    (250, 'g'),
    (500, 'g'),
    (1, 'kg'),
]

def get_weight_in_grams(w_val, w_unit):
    """Convert weight to grams for price calculation"""
    if w_unit == 'kg':
        return Decimal(str(w_val)) * 1000
    return Decimal(str(w_val))

class Command(BaseCommand):
    help = 'Seed 100g/250g/500g/1kg variants for all products and map to ERP'

    @transaction.atomic
    def handle(self, *args, **options):
        for sp in Product.objects.all():
            mapped_var = sp.variants.filter(
                erp_mapping__is_active=True
            ).select_related('erp_mapping__erp_product').first()
            
            if not mapped_var:
                self.stdout.write(f'⚠ No ERP mapping for {sp.name}, skipping')
                continue
            
            erp_prod = mapped_var.erp_mapping.erp_product
            self.stdout.write(f'Processing: {sp.name} -> ERP: {erp_prod.code}')
            
            # Find base price from existing 1kg variant or ERP sale_price
            base_price = Decimal('0.00')
            base_weight_g = Decimal('1000')  # 1kg in grams
            
            # Try to get price from existing 1kg variant
            existing_1kg = sp.variants.filter(weight_value=1, weight_unit='kg').first()
            if existing_1kg and existing_1kg.price and existing_1kg.price > 0:
                base_price = existing_1kg.price
            elif erp_prod.sale_price and erp_prod.sale_price > 0:
                base_price = erp_prod.sale_price
                # If ERP has grammage, adjust base weight
                if erp_prod.grammage and erp_prod.grammage > 0:
                    base_weight_g = erp_prod.grammage
            
            for w_val, w_unit in TARGET_WEIGHTS:
                if w_unit == 'kg':
                    suffix = f'{int(w_val)}kg'
                else:
                    suffix = f'{w_val}g'
                sku = f'{erp_prod.code}-{suffix}'
                
                # Calculate proportional price
                weight_g = get_weight_in_grams(w_val, w_unit)
                if base_price > 0 and base_weight_g > 0:
                    # Price proportional to weight
                    calc_price = (base_price * weight_g / base_weight_g).quantize(Decimal('0.01'))
                else:
                    calc_price = Decimal('0.00')
                
                var, created = ProductVariant.objects.get_or_create(
                    product=sp,
                    weight_value=Decimal(str(w_val)),
                    weight_unit=w_unit,
                    defaults={
                        'sku': sku,
                        'price': calc_price,
                        'old_price': Decimal('0.00'),
                        'active': True,
                        'sellable': True,
                        'stock_quantity': 100,
                        'low_stock_threshold': 10,
                        'sort_order': 1 if w_val == 100 else 2 if w_val == 250 else 3 if w_val == 500 else 4,
                    }
                )
                
                if not created:
                    var.sku = sku
                    var.price = calc_price
                    var.active = True
                    var.sellable = True
                    var.stock_quantity = 100
                    var.sort_order = 1 if w_val == 100 else 2 if w_val == 250 else 3 if w_val == 500 else 4
                    var.save()
                
                CatalogVariantMapping.objects.get_or_create(
                    variant=var,
                    defaults={'erp_product': erp_prod, 'is_active': True}
                )
                self.stdout.write(f'  [OK] {sku}: {w_val}{w_unit} @ {calc_price}')
        
        self.stdout.write(self.style.SUCCESS('\n[SUCCESS] All products now have 100g, 250g, 500g, 1kg variants active with prices.'))

if __name__ == '__main__':
    Command().run_from_argv(['manage.py', 'seed_variants'])