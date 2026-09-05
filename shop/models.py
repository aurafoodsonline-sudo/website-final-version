import hashlib
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import IntegrityError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Setting(models.Model):
    key = models.CharField(max_length=100, primary_key=True)
    value = models.TextField(default="")

    class Meta:
        db_table = "settings"


class Category(models.Model):
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    image = models.CharField(max_length=500, default="")
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "categories"
        ordering = ["sort_order"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["slug"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            # django.utils.text.slugify (not shop.views.slugify) so the result
            # stays ASCII and therefore matches the `<slug:slug>` URL converter.
            # A name with no Latin characters slugifies to '' — fall back to a
            # constant prefix so the unique constraint is never handed an empty
            # string, which is exactly what broke migration 0015.
            base_slug = slugify(self.name)[:210] or "category"
            slug = base_slug
            counter = 1
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Product(models.Model):
    slug = models.SlugField(unique=True, max_length=200)
    name = models.CharField(max_length=200)
    tagline = models.CharField(max_length=500, default="")
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    old_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    weight = models.CharField(max_length=50, default="200g")
    grammage_options = models.JSONField(default=dict, blank=True)
    image = models.CharField(max_length=500, default="")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    description = models.TextField(default="")
    ingredients = models.TextField(default="")
    usage = models.TextField(default="")
    best_seller = models.BooleanField(default=False)
    new_arrival = models.BooleanField(default=False)
    featured = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "products"
        indexes = [
            models.Index(fields=["active", "category"]),
            models.Index(fields=["featured", "active"]),
        ]

    @property
    def active_variants(self):
        cached = getattr(self, "_prefetched_objects_cache", {})
        if "variants" in cached:
            variants = cached["variants"]
            return [variant for variant in variants if variant.active]
        return list(self.variants.filter(active=True).order_by("sort_order", "id"))

    @property
    def sellable_variants(self):
        return [variant for variant in self.active_variants if variant.is_sellable]

    @property
    def default_variant(self):
        variants = self.sellable_variants or self.active_variants
        return variants[0] if variants else None

    @property
    def display_price(self):
        variant = self.default_variant
        return variant.public_price if variant else self.price

    @property
    def display_old_price(self):
        variant = self.default_variant
        if variant and variant.public_mrp:
            return variant.public_mrp
        return self.old_price

    @property
    def display_weight(self):
        variant = self.default_variant
        return variant.display_weight if variant else self.weight

    @property
    def in_stock(self):
        return any(variant.is_sellable for variant in self.active_variants)


class ProductVariant(models.Model):
    UNIT_GRAMS = "g"
    UNIT_KILOGRAMS = "kg"
    WEIGHT_UNIT_CHOICES = (
        (UNIT_GRAMS, "Grams"),
        (UNIT_KILOGRAMS, "Kilograms"),
    )

    product = models.ForeignKey(
        Product, related_name="variants", on_delete=models.CASCADE
    )
    sku = models.CharField(max_length=64, unique=True)
    weight_value = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    weight_unit = models.CharField(
        max_length=10, choices=WEIGHT_UNIT_CHOICES, default=UNIT_GRAMS
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    old_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    active = models.BooleanField(default=True)
    sellable = models.BooleanField(default=True)
    stock_quantity = models.PositiveIntegerField(
        default=100,
        help_text="Legacy portal value retained for migration compatibility; ERP stock drives availability.",
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text="Legacy portal threshold; use ERP Product minimum_stock for operations.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    image = models.CharField(max_length=500, default="", blank=True)

    class Meta:
        db_table = "product_variants"
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["product", "active"]),
            models.Index(fields=["sku"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "weight_value", "weight_unit"],
                name="unique_product_weight_variant",
            )
        ]

    @property
    def display_weight(self):
        weight = format(self.weight_value, "f")
        if "." in weight:
            weight = weight.rstrip("0").rstrip(".")
        return f"{weight}{self.weight_unit}"

    @property
    def effective_image(self):
        return self.image or self.product.image

    @property
    def public_price(self):
        from sales.models import CatalogVariantMapping
        try:
            mapping = self.erp_mapping
        except CatalogVariantMapping.DoesNotExist:
            return self.price
        return mapping.display_price if mapping.is_active and mapping.display_price is not None else self.price

    @property
    def public_mrp(self):
        from sales.models import CatalogVariantMapping
        try:
            mapping = self.erp_mapping
        except CatalogVariantMapping.DoesNotExist:
            return self.old_price
        return mapping.mrp if mapping.is_active and mapping.mrp is not None else self.old_price

    @property
    def is_sellable(self):
        return self.has_sellable_stock(1)

    @property
    def active_batch_quantity(self):
        if hasattr(self, "_erp_available_quantity"):
            return self._erp_available_quantity
        from sales.models import CatalogVariantMapping
        mapping = CatalogVariantMapping.objects.select_related("erp_product").filter(variant=self, is_active=True).first()
        if not mapping:
            return Decimal("0.000")
        from sales.services import check_finished_sku_availability
        return check_finished_sku_availability(mapping.erp_product)

    @property
    def has_batches(self):
        return self.batches.exists()

    @property
    def batch_available_quantity(self):
        return self.active_batch_quantity

    def has_sellable_stock(self, quantity=1):
        if not (self.active and self.sellable):
            return False
        if hasattr(self, "_erp_available_quantity"):
            return self._erp_available_quantity >= Decimal(str(quantity))
        from sales.models import CatalogVariantMapping
        mapping = CatalogVariantMapping.objects.select_related("erp_product").filter(variant=self, is_active=True).first()
        if not mapping:
            return False
        from sales.services import check_finished_sku_availability
        return check_finished_sku_availability(mapping.erp_product, quantity)


class ProductBatch(models.Model):
    """Legacy portal batch history. Read-only; not an operational stock source."""
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_RECALLED = "recalled"
    STATUS_DEPLETED = "depleted"
    STATUS_BLOCKED = "blocked"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_RECALLED, "Recalled"),
        (STATUS_DEPLETED, "Depleted"),
        (STATUS_BLOCKED, "Blocked"),
    )

    product_variant = models.ForeignKey(
        ProductVariant, related_name="batches", on_delete=models.CASCADE
    )
    batch_number = models.CharField(max_length=100)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    shelf_life_months = models.PositiveIntegerField(default=0)
    supplier_name = models.CharField(max_length=200, blank=True, default="")
    received_quantity = models.PositiveIntegerField(default=0)
    available_quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "product_batches"
        ordering = ["expiry_date", "id"]
        indexes = [
            models.Index(fields=["batch_number"]),
            models.Index(fields=["product_variant", "status", "expiry_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(available_quantity__gte=0),
                name="batch_available_quantity_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(reserved_quantity__gte=0),
                name="batch_reserved_quantity_non_negative",
            ),
        ]

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()

    @property
    def is_sellable(self):
        return (
            self.status == self.STATUS_ACTIVE
            and not self.is_expired
            and self.available_quantity > 0
        )

    def __str__(self):
        return f"{self.product_variant.sku} / {self.batch_number}"


class StockLedger(models.Model):
    """Legacy portal movement history. New stock movements post only to ERP."""
    MOVEMENT_PURCHASE = "purchase"
    MOVEMENT_ADJUSTMENT = "adjustment"
    MOVEMENT_SALE = "sale"
    MOVEMENT_CANCELLATION_RESTORE = "cancellation_restore"
    MOVEMENT_RETURN_RESTORE = "return_restore"
    MOVEMENT_EXPIRY_WRITEOFF = "expiry_writeoff"
    MOVEMENT_DAMAGE_WRITEOFF = "damage_writeoff"
    MOVEMENT_MANUAL_CORRECTION = "manual_correction"
    MOVEMENT_CHOICES = (
        (MOVEMENT_PURCHASE, "Purchase"),
        (MOVEMENT_ADJUSTMENT, "Adjustment"),
        (MOVEMENT_SALE, "Sale"),
        (MOVEMENT_CANCELLATION_RESTORE, "Cancellation restore"),
        (MOVEMENT_RETURN_RESTORE, "Return restore"),
        (MOVEMENT_EXPIRY_WRITEOFF, "Expiry writeoff"),
        (MOVEMENT_DAMAGE_WRITEOFF, "Damage writeoff"),
        (MOVEMENT_MANUAL_CORRECTION, "Manual correction"),
    )

    product_variant = models.ForeignKey(
        ProductVariant, related_name="stock_ledger", on_delete=models.CASCADE
    )
    batch = models.ForeignKey(
        ProductBatch,
        related_name="stock_ledger",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    movement_type = models.CharField(max_length=40, choices=MOVEMENT_CHOICES)
    quantity_delta = models.IntegerField()
    reference_type = models.CharField(max_length=80, blank=True, default="")
    reference_id = models.CharField(max_length=80, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_ledger"
        indexes = [
            models.Index(fields=["product_variant", "created_at"]),
            models.Index(fields=["reference_type", "reference_id"]),
        ]


class Bundle(models.Model):
    name = models.CharField(max_length=200)
    items = models.TextField(default="")
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    old_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    save_percent = models.IntegerField(default=0)
    image = models.CharField(max_length=500, default="")

    class Meta:
        db_table = "bundles"


class Testimonial(models.Model):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=200, default="")
    text = models.TextField()
    rating = models.IntegerField(default=5)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "testimonials"


class BlogPost(models.Model):
    slug = models.SlugField(unique=True, max_length=200)
    title = models.CharField(max_length=300)
    category = models.CharField(max_length=100, default="General")
    read_time = models.CharField(max_length=20, default="5 min")
    excerpt = models.TextField(default="")
    content = models.TextField(default="")
    image = models.CharField(max_length=500, default="")
    date = models.DateField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "blog_posts"


class WhyItem(models.Model):
    icon = models.CharField(max_length=50, default="leaf")
    title = models.CharField(max_length=200)
    description = models.TextField(default="")
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "why_items"
        ordering = ["sort_order"]


class ContactMessage(models.Model):
    STATUS_NEW = "new"
    STATUS_SPAM = "spam"
    STATUS_REVIEWED = "reviewed"
    STATUS_CHOICES = (
        (STATUS_NEW, "New"),
        (STATUS_SPAM, "Spam"),
        (STATUS_REVIEWED, "Reviewed"),
    )

    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=50, default="")
    message = models.TextField()
    spam_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contact_messages"


class SiteRating(models.Model):
    rating = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "site_ratings"


class SitePage(models.Model):
    page = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=300, default="")
    subtitle = models.CharField(max_length=500, default="")
    content = models.TextField(default="")

    class Meta:
        db_table = "site_pages"


class Order(models.Model):
    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_PROCESSING = "processing"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    customer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_orders",
    )
    customer_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50)
    city = models.CharField(max_length=100)
    address = models.TextField()
    payment_method = models.CharField(max_length=50, default="cod")
    notes = models.TextField(default="")
    reference = models.CharField(max_length=32, unique=True, blank=True, default="")
    idempotency_key = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    delivery_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    PAYMENT_UNPAID = "unpaid"
    PAYMENT_AWAITING_VERIFICATION = "awaiting_verification"
    PAYMENT_PAID = "paid"
    PAYMENT_FAILED = "failed"
    PAYMENT_REFUNDED = "refunded"
    PAYMENT_STATUS_CHOICES = (
        (PAYMENT_UNPAID, "Unpaid"),
        (PAYMENT_AWAITING_VERIFICATION, "Awaiting verification"),
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_FAILED, "Failed"),
        (PAYMENT_REFUNDED, "Refunded"),
    )
    payment_status = models.CharField(
        max_length=40,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_UNPAID,
    )
    suspicious_order = models.BooleanField(default=False)
    fraud_review_required = models.BooleanField(default=False)
    risk_note = models.CharField(max_length=300, blank=True, default="")
    stock_restored_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders"
        indexes = [
            models.Index(fields=["customer_user", "created_at"]),
            models.Index(fields=["reference"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["payment_status"]),
        ]

    def save(self, *args, **kwargs):
        if self.reference:
            return super().save(*args, **kwargs)

        for _ in range(5):
            self.reference = secrets.token_hex(8)
            try:
                return super().save(*args, **kwargs)
            except IntegrityError:
                self.reference = ""

        raise IntegrityError("Unable to generate a unique order reference.")


class CustomerAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="saved_addresses",
        on_delete=models.CASCADE,
    )
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=50)
    city = models.CharField(max_length=100)
    address = models.TextField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_addresses"
        indexes = [
            models.Index(fields=["user", "is_default"]),
        ]
        ordering = ["-is_default", "-created_at"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            CustomerAddress.objects.filter(user=self.user, is_default=True).exclude(id=self.id).update(is_default=False)

    def __str__(self):
        return f"{self.full_name} - {self.city}"


class CustomerEmailVerification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="email_verifications",
        on_delete=models.CASCADE,
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_email_verifications"
        indexes = [
            models.Index(fields=["user", "verified_at"]),
            models.Index(fields=["expires_at"]),
        ]

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    @classmethod
    def create_for_user(cls, user, ttl_hours=48):
        token = secrets.token_urlsafe(32)
        verification = cls.objects.create(
            user=user,
            token_hash=cls.hash_token(token),
            expires_at=timezone.now() + timezone.timedelta(hours=ttl_hours),
        )
        return verification, token

    @property
    def is_usable(self):
        return self.verified_at is None and self.expires_at >= timezone.now()


class CustomerPasswordReset(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="password_resets",
        on_delete=models.CASCADE,
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_password_resets"
        indexes = [
            models.Index(fields=["user", "used_at"]),
            models.Index(fields=["expires_at"]),
        ]

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    @classmethod
    def create_for_user(cls, user, ttl_hours=2):
        token = secrets.token_urlsafe(32)
        reset = cls.objects.create(
            user=user,
            token_hash=cls.hash_token(token),
            expires_at=timezone.now() + timezone.timedelta(hours=ttl_hours),
        )
        return reset, token

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at >= timezone.now()


class DeliveryZone(models.Model):
    name = models.CharField(max_length=120)
    city_pattern = models.CharField(
        max_length=300,
        help_text="Comma-separated city names or prefixes matched case-insensitively.",
    )
    base_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    free_delivery_min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    estimated_days_min = models.PositiveIntegerField(default=1)
    estimated_days_max = models.PositiveIntegerField(default=3)
    courier_hint = models.CharField(max_length=200, blank=True, default="")
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "delivery_zones"
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["active", "sort_order"]),
        ]

    def matches_city(self, city):
        normalized = str(city or "").strip().lower()
        if not normalized:
            return False
        patterns = [part.strip().lower() for part in self.city_pattern.split(",") if part.strip()]
        return any(normalized == pattern or normalized.startswith(pattern) for pattern in patterns)

    def charge_for_subtotal(self, subtotal):
        amount = Decimal(str(subtotal or "0.00"))
        if self.free_delivery_min and amount >= self.free_delivery_min:
            return Decimal("0.00")
        return self.base_charge

    @property
    def eta_label(self):
        if self.estimated_days_min == self.estimated_days_max:
            return f"{self.estimated_days_min} day"
        return f"{self.estimated_days_min}-{self.estimated_days_max} days"

    def __str__(self):
        return self.name


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    variant = models.ForeignKey(
        ProductVariant,
        related_name="order_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    product_id = models.IntegerField(default=0)
    product_name = models.CharField(max_length=200)
    quantity = models.IntegerField(default=1)
    weight_option = models.CharField(max_length=50, default="")
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        db_table = "order_items"


class PaymentTransaction(models.Model):
    PROVIDER_COD = "cod"
    PROVIDER_JAZZCASH = "jazzcash"
    PROVIDER_EASYPAISA = "easypaisa"
    PROVIDER_BANK_TRANSFER = "bank_transfer"
    PROVIDER_MANUAL = "manual"
    PROVIDER_CHOICES = (
        (PROVIDER_COD, "Cash on delivery"),
        (PROVIDER_JAZZCASH, "JazzCash manual verification"),
        (PROVIDER_EASYPAISA, "Easypaisa manual verification"),
        (PROVIDER_BANK_TRANSFER, "Bank transfer manual verification"),
        (PROVIDER_MANUAL, "Manual"),
    )
    STATUS_PENDING = "pending"
    STATUS_AWAITING_VERIFICATION = "awaiting_verification"
    STATUS_VERIFIED = "verified"
    STATUS_FAILED = "failed"
    STATUS_REFUNDED = "refunded"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_AWAITING_VERIFICATION, "Awaiting verification"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REFUNDED, "Refunded"),
    )

    order = models.ForeignKey(Order, related_name="payment_transactions", on_delete=models.CASCADE)
    provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default=STATUS_PENDING)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    provider_reference = models.CharField(max_length=200, blank=True, default="")
    raw_payload = models.JSONField(default=dict, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_payments",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payment_transactions"
        indexes = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["provider", "status"]),
        ]


class OrderStatusLog(models.Model):
    order = models.ForeignKey(Order, related_name="status_logs", on_delete=models.CASCADE)
    old_status = models.CharField(max_length=20, blank=True, default="")
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_status_changes",
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_status_logs"
        indexes = [
            models.Index(fields=["order", "created_at"]),
        ]


class ReturnRequest(models.Model):
    STATUS_REQUESTED = "requested"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_RECEIVED = "received"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = (
        (STATUS_REQUESTED, "Requested"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_RECEIVED, "Received"),
        (STATUS_CLOSED, "Closed"),
    )

    order = models.ForeignKey(Order, related_name="return_requests", on_delete=models.CASCADE)
    reason = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "return_requests"


class RefundRequest(models.Model):
    STATUS_REQUESTED = "requested"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_PROCESSED = "processed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_REQUESTED, "Requested"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_FAILED, "Failed"),
    )

    order = models.ForeignKey(Order, related_name="refund_requests", on_delete=models.CASCADE)
    payment_transaction = models.ForeignKey(
        PaymentTransaction,
        related_name="refund_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    reason = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "refund_requests"


class Shipment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"
    STATUS_SHIPPED = "shipped"
    STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_RETURNING = "returning"
    STATUS_RETURNED = "returned"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_READY, "Ready for dispatch"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_OUT_FOR_DELIVERY, "Out for delivery"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed delivery"),
        (STATUS_RETURNING, "Returning"),
        (STATUS_RETURNED, "Returned"),
    )

    order = models.OneToOneField(Order, related_name="shipment", on_delete=models.CASCADE)
    zone = models.ForeignKey(
        DeliveryZone,
        related_name="shipments",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    courier_name = models.CharField(max_length=120, blank=True, default="")
    tracking_number = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    estimated_delivery_min = models.DateField(null=True, blank=True)
    estimated_delivery_max = models.DateField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_reason = models.CharField(max_length=300, blank=True, default="")
    public_note = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shipments"
        indexes = [
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["tracking_number"]),
        ]

    @property
    def eta_label(self):
        if not self.estimated_delivery_min or not self.estimated_delivery_max:
            return ""
        if self.estimated_delivery_min == self.estimated_delivery_max:
            return self.estimated_delivery_min.isoformat()
        return f"{self.estimated_delivery_min.isoformat()} to {self.estimated_delivery_max.isoformat()}"


class SupportTicket(models.Model):
    CATEGORY_GENERAL = "general"
    CATEGORY_SHIPPING = "shipping"
    CATEGORY_RETURN = "return"
    CATEGORY_REFUND = "refund"
    CATEGORY_COMPLAINT = "complaint"
    CATEGORY_WHOLESALE = "wholesale"
    CATEGORY_CHOICES = (
        (CATEGORY_GENERAL, "General question"),
        (CATEGORY_SHIPPING, "Shipping/tracking"),
        (CATEGORY_RETURN, "Return request"),
        (CATEGORY_REFUND, "Refund request"),
        (CATEGORY_COMPLAINT, "Complaint"),
        (CATEGORY_WHOLESALE, "Wholesale"),
    )
    STATUS_OPEN = "open"
    STATUS_IN_REVIEW = "in_review"
    STATUS_WAITING_CUSTOMER = "waiting_customer"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_IN_REVIEW, "In review"),
        (STATUS_WAITING_CUSTOMER, "Waiting for customer"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
    )

    public_reference = models.CharField(max_length=32, unique=True, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="support_tickets",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    order = models.ForeignKey(
        Order,
        related_name="support_tickets",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default=CATEGORY_GENERAL)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_OPEN)
    priority = models.CharField(max_length=20, default="normal")
    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True, default="")
    subject = models.CharField(max_length=200)
    message = models.TextField()
    admin_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_tickets"
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["order", "category"]),
            models.Index(fields=["status", "updated_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.public_reference:
            return super().save(*args, **kwargs)
        for _ in range(5):
            self.public_reference = f"SUP-{secrets.token_hex(4).upper()}"
            try:
                return super().save(*args, **kwargs)
            except IntegrityError:
                self.public_reference = ""
        raise IntegrityError("Unable to generate a unique support reference.")


class FAQItem(models.Model):
    question = models.CharField(max_length=240)
    answer = models.TextField()
    category = models.CharField(max_length=80, default="General")
    sort_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "faq_items"
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["active", "sort_order"]),
        ]

    def __str__(self):
        return self.question


class SpiceProductProfile(models.Model):
    FORM_WHOLE = "whole"
    FORM_GROUND = "ground"
    FORM_BLEND = "blend"
    FORM_MASALA = "masala"
    FORM_HERB = "herb"
    FORM_SALT = "salt"
    FORM_OTHER = "other"
    FORM_CHOICES = (
        (FORM_WHOLE, "Whole"),
        (FORM_GROUND, "Ground"),
        (FORM_BLEND, "Blend"),
        (FORM_MASALA, "Masala"),
        (FORM_HERB, "Herb"),
        (FORM_SALT, "Salt"),
        (FORM_OTHER, "Other"),
    )
    HEAT_NONE = "none"
    HEAT_MILD = "mild"
    HEAT_MEDIUM = "medium"
    HEAT_HOT = "hot"
    HEAT_EXTRA_HOT = "extra_hot"
    HEAT_CHOICES = (
        (HEAT_NONE, "None"),
        (HEAT_MILD, "Mild"),
        (HEAT_MEDIUM, "Medium"),
        (HEAT_HOT, "Hot"),
        (HEAT_EXTRA_HOT, "Extra hot"),
    )

    product = models.OneToOneField(Product, related_name="spice_profile", on_delete=models.CASCADE)
    spice_form = models.CharField(max_length=30, choices=FORM_CHOICES, default=FORM_OTHER)
    organic_claim = models.BooleanField(default=False)
    premium_claim = models.BooleanField(default=False)
    purity_claim_text = models.CharField(max_length=300, blank=True, default="")
    claim_evidence_note = models.TextField(blank=True, default="")
    claim_approved = models.BooleanField(default=False)
    heat_level = models.CharField(max_length=30, choices=HEAT_CHOICES, default=HEAT_NONE)
    flavor_notes = models.TextField(blank=True, default="")
    aroma_notes = models.TextField(blank=True, default="")
    ingredient_disclosure = models.TextField(blank=True, default="")
    allergen_statement = models.TextField(blank=True, default="")
    storage_instructions = models.TextField(blank=True, default="")
    usage_instructions = models.TextField(blank=True, default="")
    cuisine_tags = models.CharField(max_length=500, blank=True, default="")
    recipe_suitability_tags = models.CharField(max_length=500, blank=True, default="")
    packaging_type = models.CharField(max_length=200, blank=True, default="")
    packaging_size_note = models.CharField(max_length=300, blank=True, default="")
    food_grade_packaging_note = models.TextField(blank=True, default="")
    freshness_note = models.TextField(blank=True, default="")
    shelf_life_months = models.PositiveIntegerField(default=0)
    expiry_display_policy = models.CharField(max_length=300, blank=True, default="")
    manufacturing_display_policy = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "spice_product_profiles"


class PolicyPage(models.Model):
    TYPE_PRIVACY = "privacy"
    TYPE_TERMS = "terms"
    TYPE_RETURN = "return"
    TYPE_REFUND = "refund"
    TYPE_SHIPPING = "shipping"
    TYPE_CANCELLATION = "cancellation"
    TYPE_COOKIE = "cookie"
    TYPE_FOOD_DISCLOSURE = "food_disclosure"
    TYPE_ALLERGEN = "allergen"
    TYPE_BUSINESS_IDENTITY = "business_identity"
    PAGE_TYPE_CHOICES = (
        (TYPE_PRIVACY, "Privacy policy"),
        (TYPE_TERMS, "Terms and conditions"),
        (TYPE_RETURN, "Return policy"),
        (TYPE_REFUND, "Refund policy"),
        (TYPE_SHIPPING, "Shipping policy"),
        (TYPE_CANCELLATION, "Cancellation policy"),
        (TYPE_COOKIE, "Cookie policy"),
        (TYPE_FOOD_DISCLOSURE, "Food product disclosure"),
        (TYPE_ALLERGEN, "Allergen disclosure"),
        (TYPE_BUSINESS_IDENTITY, "Business identity"),
    )

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=160, unique=True)
    content = models.TextField(default="")
    page_type = models.CharField(max_length=40, choices=PAGE_TYPE_CHOICES)
    is_published = models.BooleanField(default=True)
    requires_checkout_visibility = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_policy_pages",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "policy_pages"
        ordering = ["page_type", "title"]
        indexes = [
            models.Index(fields=["slug", "is_published"]),
            models.Index(fields=["page_type", "is_published"]),
        ]

    def __str__(self):
        return self.title


class StaffMFADevice(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="mfa_devices",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=120, default="Authenticator app")
    secret = models.CharField(max_length=255)
    confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "staff_mfa_devices"
        indexes = [
            models.Index(fields=["user", "confirmed"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.name}"

    def save(self, *args, **kwargs):
        from shop.services.mfa_crypto import encrypt_totp_secret

        self.secret = encrypt_totp_secret(self.secret)
        super().save(*args, **kwargs)


class AdminActivityLog(models.Model):
    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_CHOICES = (
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_activity_logs",
    )
    action = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100, blank=True, default="")
    object_repr = models.CharField(max_length=300, blank=True, default="")
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default=SEVERITY_INFO,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_activity_logs"
        indexes = [
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["severity", "created_at"]),
        ]
