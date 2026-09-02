from django.db import migrations


def map_exact_skus(apps, schema_editor):
    ProductVariant = apps.get_model("shop", "ProductVariant")
    ERPProduct = apps.get_model("erp", "Product")
    Mapping = apps.get_model("sales", "CatalogVariantMapping")
    for variant in ProductVariant.objects.filter(active=True):
        product = ERPProduct.objects.filter(code__iexact=variant.sku, product_type="finished", is_active=True).first()
        if product:
            Mapping.objects.get_or_create(
                variant_id=variant.pk,
                defaults={"erp_product_id": product.pk, "display_price": variant.price, "mrp": variant.old_price or None},
            )


class Migration(migrations.Migration):
    dependencies = [("sales", "0002_alter_salesinvoiceline_order_line")]
    operations = [migrations.RunPython(map_exact_skus, migrations.RunPython.noop)]
