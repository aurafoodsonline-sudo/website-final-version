import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aurafoods_erp.settings')
django.setup()

from decimal import Decimal
from django.utils import timezone
from erp.models import Product as ERPProduct, UnitOfMeasure, Warehouse, StockBatch, StockLedgerEntry
from shop.models import Product as ShopProduct, ProductVariant
from sales.models import CatalogVariantMapping

# 1. Units
kg, _ = UnitOfMeasure.objects.get_or_create(code='kg', defaults={'name': 'Kilogram', 'unit_type': 'weight', 'decimal_places': 3, 'is_active': True})
g, _ = UnitOfMeasure.objects.get_or_create(code='g', defaults={'name': 'Gram', 'unit_type': 'weight', 'decimal_places': 0, 'is_active': True})

# 2. Warehouse
wh, _ = Warehouse.objects.get_or_create(code='MAIN', defaults={'name': 'Main Warehouse', 'location': 'Main', 'is_active': True})

# 3. Create ERP finished products for each shop product + map default variant
for sp in ShopProduct.objects.all():
    dv = sp.variants.filter(sku__endswith='-default').first() or sp.variants.first()
    if not dv:
        continue
    
    erp_code = dv.sku.split('-')[0] + '-' + dv.sku.split('-')[1]
    
    grammage_g = Decimal(str(dv.weight_value)) if dv.weight_unit == 'g' else Decimal(str(dv.weight_value)) * 1000
    
    erp_prod, created = ERPProduct.objects.get_or_create(
        code=erp_code,
        defaults={
            'name': sp.name,
            'product_type': ERPProduct.ProductType.FINISHED,
            'base_unit': kg,
            'grammage': grammage_g,
            'net_weight': grammage_g,
            'pack_type': 'pouch',
            'is_active': True,
        }
    )
    
    # Map default variant
    CatalogVariantMapping.objects.get_or_create(
        variant=dv,
        defaults={'erp_product': erp_prod, 'is_active': True}
    )
    
    # 4. Create batch + 50kg stock
    batch_num = f"INIT-{timezone.localdate().strftime('%Y%m%d')}-{erp_code}"
    batch, _ = StockBatch.objects.get_or_create(
        product=erp_prod,
        batch_number=batch_num,
        batch_type='finished',
        defaults={
            'stock_state': 'accepted',
            'warehouse': wh,
            'quantity_on_hand': Decimal('50.000'),
            'unit_cost': Decimal('0.0000'),
            'manufacturing_date': timezone.localdate(),
        }
    )
    
    # 5. Ledger entry
    StockLedgerEntry.objects.get_or_create(
        product=erp_prod,
        batch=batch,
        warehouse=wh,
        source_document_type='STOCK_ADJUSTMENT',
        source_document_number=batch_num,
        defaults={
            'direction': StockLedgerEntry.Direction.IN,
            'quantity': Decimal('50.000'),
            'unit_cost': Decimal('0.0000'),
            'transaction_date': timezone.localdate(),
            'description': 'Initial 50kg stock load',
        }
    )
    
    print(f"OK: {sp.name} ({erp_code}) -> 50 kg in ERP")

print("Done. All products have 50 kg in ERP.")