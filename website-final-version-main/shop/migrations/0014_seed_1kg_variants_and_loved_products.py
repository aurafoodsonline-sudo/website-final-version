from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations

LOVED_PRODUCTS = [
    {
        "slug": "sabut-kashmiri-lal-mirch",
        "name": "Sabut Kashmiri Lal Mirch",
        "tagline": "Whole Kashmiri chillies, hand-sorted for deep red color and balanced heat.",
        "description": (
            "Whole Kashmiri red chillies selected from the Kunri plains of Sindh. "
            "Sun-dried and hand-sorted, they deliver the deep crimson color and "
            "aromatic, medium heat that Pakistani kitchens love."
        ),
        "ingredients": "100% whole red chillies. No additives, no preservatives.",
        "usage": "Soak in warm water before grinding for authentic Indian/Pakistani curry color, or grind dry for a coarser chili flake.",
        "price": "320.00",
        "old_price": "400.00",
        "image": "/static/uploads/product10.jpeg",
        "variants": [
            ("200g", "70.00", "90.00"),
            ("500g", "160.00", "200.00"),
            ("1kg", "320.00", "400.00"),
        ],
    },
    {
        "slug": "aura-special-lal-mirch-pisi-lal-mirch",
        "name": "Aura Special Lal Mirch (Pisi Lal Mirch)",
        "tagline": "Finely ground special-grade lal mirch for everyday cooking.",
        "description": (
            "Our signature finely ground red chili powder. Stone-ground from "
            "hand-cleaned Sindh chillies and packed within days to lock in "
            "color, heat, and aroma."
        ),
        "ingredients": "100% ground red chillies. No additives, no preservatives.",
        "usage": "Add to curries, daals, and marinades. Store in an airtight jar away from direct sunlight.",
        "price": "450.00",
        "old_price": "550.00",
        "image": "/static/uploads/product01.jpeg",
        "variants": [
            ("200g", "100.00", "125.00"),
            ("500g", "240.00", "280.00"),
            ("1kg", "450.00", "550.00"),
        ],
    },
]


def seed_kg_variants_and_loved_products(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    ProductVariant = apps.get_model("shop", "ProductVariant")
    Category = apps.get_model("shop", "Category")

    def ensure_kg_variant(product, price, old_price, sort_order=999, image=""):
        if ProductVariant.objects.filter(
            product_id=product.id,
            weight_value=Decimal("1.00"),
            weight_unit="kg",
        ).exists():
            return
        ProductVariant.objects.create(
            product_id=product.id,
            sku=f"AURA-{product.id}-1kg",
            weight_value=Decimal("1.00"),
            weight_unit="kg",
            price=price,
            old_price=old_price,
            active=True,
            sellable=True,
            sort_order=sort_order,
            image=image,
        )

    for product in Product.objects.all():
        variant = ProductVariant.objects.filter(product_id=product.id).order_by("sort_order", "id").first()
        if variant and variant.weight_unit == "g":
            grams = variant.weight_value
        elif variant:
            grams = variant.weight_value * Decimal("1000")
        else:
            grams = Decimal("200")
        factor = (Decimal("1000") / grams).quantize(Decimal("0.001"))
        base_price = variant.price if variant else product.price
        base_old_price = variant.old_price if variant else product.old_price
        price = (base_price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        old_price = (base_old_price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ensure_kg_variant(product, price, old_price)

    red_chili = Category.objects.filter(name="Red Chili Powder").first()

    for spec in LOVED_PRODUCTS:
        if Product.objects.filter(slug=spec["slug"]).exists():
            continue
        product = Product.objects.create(
            slug=spec["slug"],
            name=spec["name"],
            tagline=spec["tagline"],
            description=spec["description"],
            ingredients=spec["ingredients"],
            usage=spec["usage"],
            price=Decimal(spec["price"]),
            old_price=Decimal(spec["old_price"]),
            weight="1kg",
            image=spec["image"],
            category_id=red_chili.id if red_chili else None,
            best_seller=True,
            new_arrival=False,
            featured=True,
            active=True,
        )
        for sort_order, (weight_label, price, old_price) in enumerate(spec["variants"]):
            if weight_label.endswith("kg"):
                weight_value = Decimal(weight_label[:-2])
                weight_unit = "kg"
            else:
                weight_value = Decimal(weight_label[:-1])
                weight_unit = "g"
            ProductVariant.objects.create(
                product_id=product.id,
                sku=f"AURA-{product.id}-{weight_label}",
                weight_value=weight_value,
                weight_unit=weight_unit,
                price=Decimal(price),
                old_price=Decimal(old_price),
                active=True,
                sellable=True,
                sort_order=sort_order,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0013_alter_productvariant_low_stock_threshold_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_kg_variants_and_loved_products, migrations.RunPython.noop),
    ]
