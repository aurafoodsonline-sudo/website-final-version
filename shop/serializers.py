from rest_framework import serializers

from .models import (
    BlogPost,
    Bundle,
    Category,
    ContactMessage,
    Product,
    ProductVariant,
    Setting,
    Testimonial,
    WhyItem,
)


class ProductVariantSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(source="public_price", max_digits=18, decimal_places=2, read_only=True)
    old_price = serializers.DecimalField(source="public_mrp", max_digits=18, decimal_places=2, read_only=True)
    display_weight = serializers.CharField(read_only=True)
    image = serializers.SerializerMethodField()
    is_sellable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "sku",
            "weight_value",
            "weight_unit",
            "display_weight",
            "price",
            "old_price",
            "sort_order",
            "image",
            "is_sellable",
        ]

    def get_image(self, obj):
        return obj.effective_image


class PublicProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    variants = serializers.SerializerMethodField()
    display_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    display_old_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    display_weight = serializers.CharField(read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    default_variant_id = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "slug",
            "name",
            "tagline",
            "description",
            "ingredients",
            "usage",
            "image",
            "category",
            "category_name",
            "best_seller",
            "new_arrival",
            "featured",
            "variants",
            "display_price",
            "display_old_price",
            "display_weight",
            "in_stock",
            "default_variant_id",
        ]

    def get_variants(self, obj):
        return ProductVariantSerializer(obj.active_variants, many=True).data

    def get_default_variant_id(self, obj):
        variant = obj.default_variant
        return variant.id if variant else None


class CategorySerializer(serializers.ModelSerializer):
    count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "image", "sort_order", "count"]

    def get_count(self, obj):
        return obj.product_set.filter(active=True).count()


class BundleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bundle
        fields = ["id", "name", "items", "price", "old_price", "save_percent", "image"]


class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = ["id", "name", "city", "text", "rating"]


class BlogPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = ["id", "slug", "title", "category", "read_time", "excerpt", "content", "image", "date"]


class WhyItemSerializer(serializers.ModelSerializer):
    svg = serializers.SerializerMethodField()

    class Meta:
        model = WhyItem
        fields = ["id", "icon", "title", "description", "sort_order", "svg"]

    def get_svg(self, obj):
        paths = {
            "leaf": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
            "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
            "sparkles": '<path d="M12 2l2.4 7.2h7.6l-6 4.8 2.4 7.2-6-4.8-6 4.8 2.4-7.2-6-4.8h7.6z"/>',
            "award": '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
            "truck": '<rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>',
            "flame": '<path d="M8.5 14.5A2.5 2.5 0 0011 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 11-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 002.5 2.5z"/>',
        }
        return paths.get(obj.icon, "")


class SettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Setting
        fields = ["key", "value"]


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["id", "name", "email", "phone", "message", "spam_status", "created_at"]


class AdminProductSerializer(PublicProductSerializer):
    admin_variants = serializers.SerializerMethodField()

    class Meta(PublicProductSerializer.Meta):
        fields = PublicProductSerializer.Meta.fields + [
            "price",
            "old_price",
            "weight",
            "grammage_options",
            "active",
            "admin_variants",
        ]

    def get_admin_variants(self, obj):
        return [
            {
                "id": variant.id,
                "sku": variant.sku,
                "display_weight": variant.display_weight,
                "weight_value": str(variant.weight_value),
                "weight_unit": variant.weight_unit,
                "price": str(variant.price),
                "old_price": str(variant.old_price),
                "active": variant.active,
                "sellable": variant.sellable,
                "sort_order": variant.sort_order,
                "stock_quantity": variant.stock_quantity,
            }
            for variant in obj.variants.all().order_by("sort_order", "id")
        ]


ProductSerializer = PublicProductSerializer
