from django.contrib import admin
from django.forms.models import BaseInlineFormSet
from django.core.exceptions import ValidationError

from .models import (
    AdminActivityLog,
    BlogPost,
    Bundle,
    Category,
    ContactMessage,
    CustomerEmailVerification,
    CustomerPasswordReset,
    DeliveryZone,
    FAQItem,
    Order,
    OrderStatusLog,
    PaymentTransaction,
    PolicyPage,
    Product,
    ProductBatch,
    ProductVariant,
    RefundRequest,
    ReturnRequest,
    Setting,
    Shipment,
    SpiceProductProfile,
    StaffMFADevice,
    StockLedger,
    SupportTicket,
    Testimonial,
    WhyItem,
)


class ReadOnlyTransactionalAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ProductVariantInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen_weights = set()
        product = self.instance
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE', False):
                continue
            weight_value = form.cleaned_data.get('weight_value')
            weight_unit = form.cleaned_data.get('weight_unit')
            if weight_value is not None and weight_unit:
                key = (weight_value, weight_unit)
                if key in seen_weights:
                    raise ValidationError(f'Duplicate weight variant: {weight_value}{weight_unit}. Each product can only have one variant per weight.')
                existing_qs = ProductVariant.objects.filter(product=product, weight_value=weight_value, weight_unit=weight_unit)
                if form.instance and form.instance.pk:
                    existing_qs = existing_qs.exclude(pk=form.instance.pk)
                if existing_qs.exists():
                    raise ValidationError(f'Weight variant {weight_value}{weight_unit} already exists for this product.')
                seen_weights.add(key)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    formset = ProductVariantInlineFormSet
    extra = 0
    fields = ['weight_value', 'weight_unit', 'price', 'old_price', 'stock_quantity', 'low_stock_threshold', 'sellable', 'active', 'sort_order', 'image']
    readonly_fields = ['low_stock_threshold', 'sku']
    can_delete = True
    show_change_link = True
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'category', 'best_seller', 'active']
    list_filter = ['category', 'best_seller', 'new_arrival']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductVariantInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AdminActivityLog.objects.create(
            actor=request.user,
            action='product_update' if change else 'product_create',
            model_name='Product',
            object_id=str(obj.id),
            object_repr=obj.name,
            severity=AdminActivityLog.SEVERITY_WARNING if change else AdminActivityLog.SEVERITY_INFO,
        )


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['product', 'sku', 'display_weight', 'price', 'stock_quantity', 'low_stock_threshold', 'sellable', 'active']
    list_filter = ['active', 'sellable', 'weight_unit']
    search_fields = ['sku', 'product__name']
    readonly_fields = ['low_stock_threshold']
    list_editable = ['sellable', 'active', 'price', 'stock_quantity']

    def save_model(self, request, obj, form, change):
        old_price = None
        old_stock = None
        if change:
            previous = ProductVariant.objects.filter(id=obj.id).first()
            if previous:
                old_price = previous.price
                old_stock = previous.stock_quantity
        super().save_model(request, obj, form, change)
        AdminActivityLog.objects.create(
            actor=request.user,
            action='variant_update' if change else 'variant_create',
            model_name='ProductVariant',
            object_id=str(obj.id),
            object_repr=obj.sku,
            old_value={'price': str(old_price), 'stock_quantity': old_stock} if change else None,
            new_value={'price': str(obj.price), 'stock_quantity': obj.stock_quantity},
            severity=AdminActivityLog.SEVERITY_CRITICAL if change and old_price != obj.price else AdminActivityLog.SEVERITY_WARNING,
        )

@admin.register(ProductBatch)
class ProductBatchAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['batch_number', 'product_variant', 'expiry_date', 'available_quantity', 'status']
    list_filter = ['status', 'expiry_date']
    search_fields = ['batch_number', 'product_variant__sku', 'product_variant__product__name']

@admin.register(StockLedger)
class StockLedgerAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['product_variant', 'movement_type', 'quantity_delta', 'reference_type', 'reference_id', 'created_at']
    list_filter = ['movement_type', 'created_at']
    search_fields = ['product_variant__sku', 'reference_id', 'note']
    readonly_fields = ['created_at']

@admin.register(Order)
class OrderAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['reference', 'customer_name', 'status', 'payment_status', 'total', 'created_at']
    list_filter = ['status', 'payment_status', 'created_at']
    search_fields = ['reference', 'customer_name', 'phone']

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['order', 'provider', 'status', 'amount', 'verified_by', 'verified_at']
    list_filter = ['provider', 'status']

@admin.register(OrderStatusLog)
class OrderStatusLogAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['order', 'old_status', 'new_status', 'changed_by', 'created_at']
    readonly_fields = ['created_at']

@admin.register(ReturnRequest)
class ReturnRequestAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['order', 'status', 'requested_at', 'resolved_at']
    list_filter = ['status']

@admin.register(RefundRequest)
class RefundRequestAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['order', 'amount', 'status', 'requested_at', 'resolved_at']
    list_filter = ['status']


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ['name', 'city_pattern', 'base_charge', 'free_delivery_min', 'estimated_days_min', 'estimated_days_max', 'active']
    list_filter = ['active']


@admin.register(Shipment)
class ShipmentAdmin(ReadOnlyTransactionalAdmin):
    list_display = ['order', 'status', 'courier_name', 'tracking_number', 'estimated_delivery_min', 'estimated_delivery_max', 'updated_at']
    list_filter = ['status', 'zone']
    search_fields = ['order__reference', 'tracking_number', 'courier_name']


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ['public_reference', 'category', 'status', 'priority', 'email', 'order', 'created_at']
    list_filter = ['category', 'status', 'priority', 'created_at']
    search_fields = ['public_reference', 'email', 'subject', 'order__reference']


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ['question', 'category', 'sort_order', 'active', 'updated_at']
    list_filter = ['category', 'active']


@admin.register(CustomerEmailVerification)
class CustomerEmailVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'verified_at', 'expires_at', 'created_at']
    readonly_fields = ['token_hash', 'created_at']


@admin.register(CustomerPasswordReset)
class CustomerPasswordResetAdmin(admin.ModelAdmin):
    list_display = ['user', 'used_at', 'expires_at', 'created_at']
    readonly_fields = ['token_hash', 'created_at']

@admin.register(SpiceProductProfile)
class SpiceProductProfileAdmin(admin.ModelAdmin):
    list_display = ['product', 'spice_form', 'heat_level', 'claim_approved']
    list_filter = ['spice_form', 'heat_level', 'claim_approved']

@admin.register(AdminActivityLog)
class AdminActivityLogAdmin(admin.ModelAdmin):
    list_display = ['actor', 'action', 'severity', 'model_name', 'object_id', 'created_at']
    list_filter = ['severity', 'action', 'model_name', 'created_at']
    readonly_fields = ['actor', 'action', 'severity', 'model_name', 'object_id', 'object_repr', 'old_value', 'new_value', 'ip_address', 'user_agent', 'created_at']


@admin.register(PolicyPage)
class PolicyPageAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'page_type', 'is_published', 'requires_checkout_visibility', 'updated_at']
    list_filter = ['page_type', 'is_published', 'requires_checkout_visibility']
    prepopulated_fields = {'slug': ('title',)}

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        old_value = None
        if change:
            previous = PolicyPage.objects.filter(id=obj.id).first()
            if previous:
                old_value = {
                    'title': previous.title,
                    'slug': previous.slug,
                    'is_published': previous.is_published,
                }
        super().save_model(request, obj, form, change)
        AdminActivityLog.objects.create(
            actor=request.user,
            action='policy_update' if change else 'policy_create',
            model_name='PolicyPage',
            object_id=str(obj.id),
            object_repr=obj.title,
            old_value=old_value,
            new_value={'title': obj.title, 'slug': obj.slug, 'is_published': obj.is_published},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )


@admin.register(StaffMFADevice)
class StaffMFADeviceAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'confirmed', 'created_at', 'last_used_at']
    list_filter = ['confirmed', 'created_at']
    search_fields = ['user__username', 'user__email', 'name']
    readonly_fields = ['created_at', 'last_used_at']

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'sort_order']

@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'save_percent']

@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'rating', 'active']

@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'date', 'active']
    prepopulated_fields = {'slug': ('title',)}

@admin.register(WhyItem)
class WhyItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'sort_order']

@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ['key', 'value']

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'spam_status', 'created_at']
    list_filter = ['spam_status', 'created_at']
    readonly_fields = ['name', 'email', 'phone', 'message', 'ip_address', 'user_agent', 'created_at']
