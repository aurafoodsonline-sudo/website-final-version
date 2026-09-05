import json
import re
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required as django_staff_member_required
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Max, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from rest_framework import permissions, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from erp.permissions import has_erp_permission
from sales.models import CatalogVariantMapping

from .models import (
    AdminActivityLog,
    BlogPost,
    Bundle,
    Category,
    ContactMessage,
    CustomerAddress,
    CustomerEmailVerification,
    CustomerPasswordReset,
    DeliveryZone,
    FAQItem,
    Order,
    PolicyPage,
    Product,
    ProductVariant,
    RefundRequest,
    ReturnRequest,
    Setting,
    Shipment,
    SiteRating,
    SupportTicket,
    Testimonial,
    WhyItem,
)
from .permissions import CRMSourcePermission, ReadOnlyOrStaffPermission
from .serializers import (
    AdminProductSerializer,
    BlogPostSerializer,
    BundleSerializer,
    CategorySerializer,
    ContactMessageSerializer,
    ProductSerializer,
    SettingSerializer,
    TestimonialSerializer,
    WhyItemSerializer,
)


def staff_member_required(function=None, login_url="/admin/login/"):
    """Protect legacy portal administration with the unified ERP configuration permission."""
    def decorator(view_func):
        @django_staff_member_required(login_url=login_url)
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not has_erp_permission(request.user, "admin.configure"):
                raise PermissionDenied("Portal administration requires admin.configure permission.")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator(function) if function else decorator
from .services.orders import OrderPlacementService
from .services.pricing import CartQuoteError, OrderPricingService, parse_decimal, parse_weight_to_variant
from .services.shipping import ShippingService
from .services.customer_notifications import (
    send_customer_password_reset_email,
    send_customer_verification_email,
)
from .services.lifecycle import OrderLifecycleService
from .services.mfa import confirmed_device_for, staff_mfa_required, verify_staff_token
from .services.audit import log_admin_activity
from .services.uploads import save_uploaded_image


SITE_URL = "https://aurafoods.pk"
SITE_NAME = "Aura Foods"
DEFAULT_IMAGE = "/static/images/hero-spices.jpg"

REQUIRED_POLICY_PAGES = [
    {
        "slug": "privacy-policy",
        "title": "Privacy Policy",
        "page_type": PolicyPage.TYPE_PRIVACY,
        "checkout": True,
        "content": "Aura Foods collects only the information needed to process orders, respond to support requests, and protect the store from abuse. Customer contact and delivery details are used for fulfillment and are not sold.",
    },
    {
        "slug": "terms-and-conditions",
        "title": "Terms and Conditions",
        "page_type": PolicyPage.TYPE_TERMS,
        "checkout": True,
        "content": "Orders are accepted subject to product availability, verified pricing, lawful use of the website, and the checkout terms shown at purchase time.",
    },
    {
        "slug": "return-policy",
        "title": "Return Policy",
        "page_type": PolicyPage.TYPE_RETURN,
        "checkout": True,
        "content": "Food products can be returned only when they are unopened, damaged in transit, incorrectly supplied, or otherwise eligible under applicable consumer protection rules.",
    },
    {
        "slug": "refund-policy",
        "title": "Refund Policy",
        "page_type": PolicyPage.TYPE_REFUND,
        "checkout": True,
        "content": "Approved refunds are processed after order review and payment verification. Refund timing depends on the original payment channel.",
    },
    {
        "slug": "shipping-policy",
        "title": "Shipping Policy",
        "page_type": PolicyPage.TYPE_SHIPPING,
        "checkout": True,
        "content": "Delivery charges, free-delivery thresholds, and availability are confirmed server-side during checkout. Delivery timelines may vary by city and courier conditions.",
    },
    {
        "slug": "cancellation-policy",
        "title": "Cancellation Policy",
        "page_type": PolicyPage.TYPE_CANCELLATION,
        "checkout": True,
        "content": "Orders may be cancelled before processing or dispatch. Once food products are packed or shipped, cancellation may be restricted.",
    },
    {
        "slug": "cookie-policy",
        "title": "Cookie Policy",
        "page_type": PolicyPage.TYPE_COOKIE,
        "checkout": False,
        "content": "Aura Foods uses necessary cookies for cart, session, CSRF protection, and checkout security. Analytics or marketing cookies should only be enabled with appropriate consent controls.",
    },
    {
        "slug": "food-product-disclosure",
        "title": "Food Product Disclosure",
        "page_type": PolicyPage.TYPE_FOOD_DISCLOSURE,
        "checkout": False,
        "content": "Spice product information, storage guidance, ingredient notes, shelf-life, batch, and freshness details should be reviewed before purchase. Product claims require internal approval before publication.",
    },
    {
        "slug": "allergen-disclosure",
        "title": "Allergen Disclosure",
        "page_type": PolicyPage.TYPE_ALLERGEN,
        "checkout": False,
        "content": "Spices may be packed in facilities that handle common allergens. Customers with allergies should review each product disclosure and contact Aura Foods before ordering.",
    },
    {
        "slug": "business-identity",
        "title": "Business Identity",
        "page_type": PolicyPage.TYPE_BUSINESS_IDENTITY,
        "checkout": False,
        "content": "Aura Foods operates as a spices and food-products seller serving customers through its website, phone, WhatsApp, and published contact channels.",
    },
]


def seo_context(title, desc, url, image=DEFAULT_IMAGE):
    return {
        "meta": {
            "title": f"{title} - {SITE_NAME}",
            "description": desc,
            "url": url,
            "image": image,
        },
        "policy_links": policy_links(),
    }


def policy_links(checkout_only=False):
    configured = {
        page.slug: page
        for page in PolicyPage.objects.filter(is_published=True).only("title", "slug", "requires_checkout_visibility")
    }
    links = []
    for fallback in REQUIRED_POLICY_PAGES:
        page = configured.get(fallback["slug"])
        checkout_visible = page.requires_checkout_visibility if page else fallback["checkout"]
        if checkout_only and not checkout_visible:
            continue
        links.append(
            {
                "title": page.title if page else fallback["title"],
                "slug": page.slug if page else fallback["slug"],
                "url": f"/policies/{page.slug if page else fallback['slug']}/",
            }
        )
    return links


def org_schema():
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": SITE_NAME,
        "url": SITE_URL,
        "logo": f"{SITE_URL}/static/uploads/logo.png?v=3",
        "description": "Pure and premium organic spices from Pakistan.",
        "areaServed": "Pakistan",
        "contactPoint": {
            "@type": "ContactPoint",
            "telephone": "+92-335-2832967",
            "contactType": "customer service",
            "availableLanguage": ["English", "Urdu"],
        },
        "sameAs": [
            "https://wa.me/923352832967",
            "https://www.instagram.com/aurafoodsonline",
            "https://www.facebook.com/share/1Ctuc2U2rj/",
        ],
    }


def breadcrumb_schema(items):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
            for i, (name, url) in enumerate(items)
        ],
    }


def product_schema(product, reviews_avg=0, reviews_count=0):
    variant = product.default_variant
    image = variant.effective_image if variant else product.image
    schema = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name,
        "description": product.tagline or product.description,
        "image": f"{SITE_URL}{image}" if image.startswith("/") else image,
        "sku": variant.sku if variant else f"AURA-{product.id}",
        "brand": {"@type": "Brand", "name": SITE_NAME},
        "offers": {
            "@type": "Offer",
            "url": f"{SITE_URL}/product/{product.slug}/",
            "priceCurrency": "PKR",
            "price": str(product.display_price),
            "availability": (
                "https://schema.org/InStock"
                if product.in_stock
                else "https://schema.org/OutOfStock"
            ),
            "itemCondition": "https://schema.org/NewCondition",
            "seller": {"@type": "Organization", "name": SITE_NAME},
        },
    }
    if product.category:
        schema["category"] = product.category.name
    if reviews_count > 0:
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": round(reviews_avg, 1),
            "bestRating": 5,
            "ratingCount": reviews_count,
        }
    return schema


def website_schema():
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": SITE_URL,
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{SITE_URL}/search/?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }


def blog_posting_schema(post):
    return {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "description": post.excerpt,
        "image": f"{SITE_URL}{post.image}" if post.image.startswith("/") else post.image,
        "datePublished": post.date.isoformat() if hasattr(post.date, "isoformat") else str(post.date),
        "author": {"@type": "Organization", "name": SITE_NAME},
        "publisher": {"@type": "Organization", "name": SITE_NAME},
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"{SITE_URL}/blog/{post.slug}"},
    }


def slugify(text):
    value = str(text).lower().strip()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[\s_]+", "-", value)
    return re.sub(r"-+", "-", value)


def cats_with_slugs(cats):
    return [
        {
            "id": category.id,
            "name": category.name,
            "image": category.image,
            "slug": category.slug,
            "count": (
                category.active_product_count
                if hasattr(category, "active_product_count")
                else category.product_set.filter(active=True).count()
            ),
        }
        for category in cats
    ]


def catalog_queryset():
    return (
        Product.objects.filter(active=True)
        .select_related("category")
        .prefetch_related(
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.select_related("erp_mapping__erp_product").order_by("sort_order", "id"),
            )
        )
        .order_by("-featured", "id")
    )


def hydrate_catalog_availability(products):
    from sales.services import finished_sku_availability_map

    variants = [variant for product in products for variant in product.variants.all()]
    product_ids = []
    for variant in variants:
        try:
            mapping = variant.erp_mapping
        except CatalogVariantMapping.DoesNotExist:
            mapping = None
        if mapping and mapping.is_active and mapping.erp_product.is_active:
            product_ids.append(mapping.erp_product_id)
    availability = finished_sku_availability_map(product_ids)
    for variant in variants:
        try:
            mapping = variant.erp_mapping
        except CatalogVariantMapping.DoesNotExist:
            mapping = None
        variant._erp_available_quantity = (
            availability.get(mapping.erp_product_id, Decimal("0.000"))
            if mapping and mapping.is_active and mapping.erp_product.is_active
            else Decimal("0.000")
        )
    return products


def first_active_variant(product):
    return product.default_variant


def decimal_to_json(value):
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def throttle_request(request, scope, limit=60, window_seconds=60):
    identifier = request.session.session_key or request.META.get("REMOTE_ADDR", "unknown")
    cache_key = f"throttle:{scope}:{identifier}"
    count = cache.get(cache_key, 0)
    if count >= limit:
        return False
    cache.set(cache_key, count + 1, timeout=window_seconds)
    return True


def request_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or "unknown"


def log_admin_event(request, action, object_repr="", new_value=None, severity=AdminActivityLog.SEVERITY_INFO):
    log_admin_activity(
        request=request,
        action=action,
        model_name="Security",
        object_repr=object_repr[:300],
        new_value=new_value,
        severity=severity,
    )


def audit_snapshot(instance, fields):
    if not instance:
        return None
    return {field: str(getattr(instance, field, "")) for field in fields}


def admin_login_cache_keys(request, username):
    identity = f"{(username or '').strip().lower()}:{request_ip(request)}"
    return f"admin-login-fails:{identity}", f"admin-login-lock:{identity}"


def cart_quote_payload(quote):
    free_delivery_min, _delivery_charge = OrderPricingService.get_delivery_settings()
    lines = []
    for line in quote.lines:
        variant = line.variant
        product = variant.product
        available_quantity = variant.batch_available_quantity
        lines.append(
            {
                "product_name": product.name,
                "product_slug": product.slug,
                "product_url": f"/product/{product.slug}/",
                "image": variant.effective_image,
                "variant_id": variant.id,
                "variant_label": variant.display_weight,
                "unit_price": decimal_to_json(line.unit_price),
                "quantity": line.quantity,
                "line_subtotal": decimal_to_json(line.subtotal),
                "stock_status": "in_stock" if available_quantity >= line.quantity else "low_stock",
                "available_quantity": available_quantity,
            }
        )
    return {
        "ok": True,
        "lines": lines,
        "subtotal": decimal_to_json(quote.subtotal),
        "delivery_charge": decimal_to_json(quote.delivery_charge),
        "discount": "0.00",
        "tax": "0.00",
        "grand_total": decimal_to_json(quote.total),
        "free_delivery_threshold": decimal_to_json(free_delivery_min),
        "warnings": [],
        "errors": [],
    }


def build_grammage_map(request):
    weights = request.POST.getlist("grammage_weight")
    prices = request.POST.getlist("grammage_price")
    grammage = {}
    for index, weight_label in enumerate(weights):
        weight_label = (weight_label or "").strip()
        if not weight_label:
            continue
        price_raw = prices[index] if index < len(prices) else None
        value = parse_decimal(price_raw or None)
        if value > 0:
            grammage[weight_label] = decimal_to_json(value)
    return grammage


def build_product_payload(request, product=None):
    name = request.POST.get("name", product.name if product else "").strip()
    tagline = request.POST.get("tagline", product.tagline if product else "").strip()
    price = parse_decimal(request.POST.get("price", product.price if product else "0"))
    old_price = parse_decimal(request.POST.get("old_price", product.old_price if product else "0"))
    weight = request.POST.get("weight", product.weight if product else "200g").strip() or "200g"
    category_id = request.POST.get("category_id", product.category_id if product else None)
    category_id = int(category_id) if str(category_id).isdigit() else None

    return {
        "slug": slugify(name),
        "name": name,
        "tagline": tagline,
        "price": price,
        "old_price": old_price,
        "weight": weight,
        "grammage_options": build_grammage_map(request),
        "category_id": category_id,
        "description": request.POST.get("description", product.description if product else "").strip(),
        "ingredients": request.POST.get("ingredients", product.ingredients if product else "").strip(),
        "usage": request.POST.get("usage", product.usage if product else "").strip(),
        "best_seller": bool(request.POST.get("best_seller")),
        "new_arrival": bool(request.POST.get("new_arrival")),
        "active": request.POST.get("active") == "1",
        "featured": request.POST.get("featured") == "1",
    }


def sync_product_variants(product):
    if product.variants.exists():
        return

    variants_payload = []
    if product.grammage_options:
        for sort_order, (weight_label, price_value) in enumerate(product.grammage_options.items()):
            price = parse_decimal(price_value)
            weight_value, weight_unit = parse_weight_to_variant(weight_label)
            if weight_value is None:
                continue
            variants_payload.append(
                {
                    "sku": f"AURA-{product.id}-{slugify(weight_label)}",
                    "weight_value": weight_value,
                    "weight_unit": weight_unit,
                    "price": price,
                    "old_price": product.old_price,
                    "sort_order": sort_order,
                }
            )
    else:
        weight_value, weight_unit = parse_weight_to_variant(product.weight)
        if weight_value is None:
            weight_value = Decimal("200")
            weight_unit = ProductVariant.UNIT_GRAMS
        variants_payload.append(
            {
                "sku": f"AURA-{product.id}-{slugify(product.weight or 'default')}",
                "weight_value": weight_value,
                "weight_unit": weight_unit,
                "price": product.price,
                "old_price": product.old_price,
                "sort_order": 0,
            }
        )

    active_skus = []
    for payload in variants_payload:
        active_skus.append(payload["sku"])
        ProductVariant.objects.update_or_create(
            sku=payload["sku"],
            defaults={
                "product": product,
                "weight_value": payload["weight_value"],
                "weight_unit": payload["weight_unit"],
                "price": payload["price"],
                "old_price": payload["old_price"],
                "sort_order": payload["sort_order"],
                "active": True,
                "sellable": True,
            },
        )

    product.variants.exclude(sku__in=active_skus).update(active=False)


def apply_variant_form(product, request):
    ids = request.POST.getlist("variant_ids")
    weights = request.POST.getlist("variant_weight")
    prices = request.POST.getlist("variant_price")
    old_prices = request.POST.getlist("variant_old_price")
    row_keys = request.POST.getlist("variant_row_key")

    def value_at(values, index):
        return values[index] if index < len(values) else "0"

    next_sort_order = (
        ProductVariant.objects.filter(product=product).aggregate(max_order=Max("sort_order"))["max_order"] or 0
    ) + 1
    for index, variant_id in enumerate(ids):
        weight_label = (weights[index] if index < len(weights) else "").strip()
        price = parse_decimal(value_at(prices, index))
        old_price = parse_decimal(value_at(old_prices, index))
        # Each row carries its own unique key, so we look its checkboxes up
        # directly instead of matching flat getlist() results by position.
        # (Checked/unchecked rows submit a different number of values for
        # repeated checkbox names, which silently corrupted the old
        # index-based matching.)
        row_key = row_keys[index] if index < len(row_keys) else str(index)
        active = request.POST.get(f"variant_active__{row_key}") == "1"
        sellable = request.POST.get(f"variant_sellable__{row_key}") == "1"

        if str(variant_id).isdigit():
            variant = ProductVariant.objects.filter(id=int(variant_id), product=product).first()
            if not variant:
                continue
            variant.price = price
            variant.old_price = old_price
            variant.active = active
            variant.sellable = sellable
            variant.save()
            continue

        weight_value, weight_unit = parse_weight_to_variant(weight_label)
        if weight_value is None:
            continue
        variant = ProductVariant.objects.filter(
            product=product, weight_value=weight_value, weight_unit=weight_unit
        ).first()
        if variant:
            variant.price = price
            variant.old_price = old_price
            variant.active = active
            variant.sellable = sellable
            variant.save()
        else:
            ProductVariant.objects.create(
                product=product,
                sku=f"AURA-{product.id}-{slugify(weight_label)}",
                weight_value=weight_value,
                weight_unit=weight_unit,
                price=price,
                old_price=old_price,
                active=active,
                sellable=sellable,
                sort_order=next_sort_order,
            )
            next_sort_order += 1


def handle_removed_variants(product, request):
    raw = request.POST.get("removed_variant_ids", "")
    removed_ids = [int(value) for value in raw.split(",") if value.strip().isdigit()]
    if not removed_ids:
        return
    from .models import OrderItem

    for variant in ProductVariant.objects.filter(id__in=removed_ids, product=product):
        referenced = OrderItem.objects.filter(variant=variant).exists()
        mapped = CatalogVariantMapping.objects.filter(variant=variant).exists()
        if referenced or mapped:
            variant.active = False
            variant.save(update_fields=["active"])
        else:
            variant.delete()


PUBLIC_SETTING_KEYS = {
    "about_content", "about_title", "address", "analytics_measurement_id",
    "delivery_charge", "email", "free_delivery_min", "hero_badge",
    "hero_image", "hero_subtitle", "hero_title", "phone", "site_name",
    "site_tagline", "story_image", "story_location", "whatsapp",
}


def public_settings():
    return {
        setting.key: setting.value
        for setting in Setting.objects.filter(key__in=PUBLIC_SETTING_KEYS)
    }


def home(request):
    products = list(catalog_queryset()[:50])
    hydrate_catalog_availability(products)
    categories = Category.objects.annotate(active_product_count=Count("product", filter=Q(product__active=True)))
    featured_products = [product for product in products if product.best_seller][:4]
    loved_names = {"Sabut Kashmiri Lal Mirch", "Aura Special Lal Mirch (Pisi Lal Mirch)"}
    loved_products = [product for product in products if product.name in loved_names]
    best_sellers = list(dict.fromkeys(loved_products + featured_products))[:6]
    ctx = seo_context(
        f"{SITE_NAME} - Pure and Premium Organic Spices of Pakistan",
        "Freshly packed authentic spices from the fields of Sindh, delivered across Pakistan.",
        f"{SITE_URL}/",
    )
    testimonials = Testimonial.objects.filter(active=True)
    rating_summary = SiteRating.objects.aggregate(average=Avg("rating"), count=Count("id"))
    avg_rating = round(rating_summary["average"] or 0, 1)
    ctx["schema_org"] = json.dumps([org_schema(), website_schema()])
    ctx.update(
        {
            "products": products[:8],
            "best_sellers": best_sellers,
            "categories": cats_with_slugs(categories),
            "testimonials": testimonials[:3],
            "bundles": Bundle.objects.all(),
            "why_items": WhyItem.objects.all(),
            "settings": public_settings(),
            "site_rating_avg": avg_rating,
            "site_rating_count": rating_summary["count"],
        }
    )
    return render(request, "index.html", ctx)


def shop_view(request):
    cat_slug = request.GET.get("category")
    products = catalog_queryset()
    cat_name = ""
    active_category = None
    if cat_slug:
        try:
            category = Category.objects.get(slug=cat_slug)
            products = products.filter(category=category)
            cat_name = category.name
            active_category = category.slug
        except Category.DoesNotExist:
            products = products.none()
    title = f"Buy {cat_name} Online" if cat_name else "Shop Organic Spices"
    desc = (
        f"Browse our complete range of organic {cat_name.lower() if cat_name else 'Pakistani spices'}. "
        "Pure, hand-sourced, and freshly packed."
    )
    ctx = seo_context(title, desc, f"{SITE_URL}/shop")
    ctx["schema_org"] = json.dumps(
        breadcrumb_schema([(SITE_NAME, SITE_URL), ("Shop", f"{SITE_URL}/shop")])
    )
    page = Paginator(products, 24).get_page(request.GET.get("page"))
    page.object_list = list(page.object_list)
    hydrate_catalog_availability(page.object_list)
    ctx.update(
        {
            "products": page,
            "page_obj": page,
            "categories": cats_with_slugs(
                Category.objects.annotate(active_product_count=Count("product", filter=Q(product__active=True)))
            ),
            "active_category": active_category,
        }
    )
    return render(request, "shop.html", ctx)


def category_detail(request, slug):
    request.GET = request.GET.copy()
    request.GET["category"] = slug
    return shop_view(request)


def wholesale_view(request):
    items = []
    for product in catalog_queryset():
        kg_variant = next(
            (variant for variant in product.active_variants if variant.weight_unit == ProductVariant.UNIT_KILOGRAMS),
            None,
        )
        if kg_variant:
            items.append({"product": product, "variant": kg_variant})
    hydrate_catalog_availability([item["product"] for item in items])
    ctx = seo_context(
        "Wholesale Spices Pakistan - Bulk 1kg Orders | Aura Foods",
        "Order authentic Pakistani spices at wholesale prices in 1kg packs. Lal mirch, haldi, dhaniya, masala blends and more, delivered across Pakistan.",
        f"{SITE_URL}/wholesale",
    )
    ctx["schema_org"] = json.dumps(
        breadcrumb_schema([(SITE_NAME, SITE_URL), ("Wholesale", f"{SITE_URL}/wholesale")])
    )
    ctx.update(
        {
            "wholesale_items": items,
            "categories": cats_with_slugs(
                Category.objects.annotate(active_product_count=Count("product", filter=Q(product__active=True)))
            ),
            "settings": public_settings(),
        }
    )
    return render(request, "wholesale.html", ctx)


def product_detail(request, slug=None, pid=None):
    if pid is not None:
        product = get_object_or_404(Product, id=pid, active=True)
        return redirect(f"/product/{product.slug}/", permanent=True)

    product = get_object_or_404(catalog_queryset(), slug=slug)
    related = list(
        catalog_queryset()
        .filter(category=product.category)
        .exclude(id=product.id)[:4]
    )
    hydrate_catalog_availability([product, *related])
    rating_summary = SiteRating.objects.aggregate(average=Avg("rating"), count=Count("id"))
    avg_rating = round(rating_summary["average"] or 0, 1)
    ctx = seo_context(product.name, product.tagline, f"{SITE_URL}/product/{product.slug}/", product.image)
    ctx["schema_org"] = json.dumps(
        [
            breadcrumb_schema(
                [
                    (SITE_NAME, SITE_URL),
                    ("Shop", f"{SITE_URL}/shop"),
                    (product.name, f"{SITE_URL}/product/{product.slug}/"),
                ]
            ),
            product_schema(product, avg_rating, rating_summary["count"]),
        ]
    )
    ctx.update(
        {
            "product": product,
            "related": related,
            "site_rating_avg": avg_rating,
            "site_rating_count": rating_summary["count"],
        }
    )
    return render(request, "product.html", ctx)


def about(request):
    ctx = seo_context(
        "About Aura Foods",
        "Learn the story behind Pakistan's premium organic spice brand.",
        f"{SITE_URL}/about",
    )
    ctx["schema_org"] = json.dumps(org_schema())
    ctx.update({"settings": public_settings(), "why_items": WhyItem.objects.all()})
    return render(request, "about.html", ctx)


def blog(request):
    posts = BlogPost.objects.filter(active=True).order_by("-date")
    ctx = seo_context(
        "Blog - Aura Foods",
        "Read about spices, recipes, and Pakistani culinary heritage.",
        f"{SITE_URL}/blog",
    )
    ctx["schema_org"] = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Blog",
            "name": f"{SITE_NAME} Blog",
            "description": "Cooking tips, health benefits of spices, and Pakistani food heritage.",
            "url": f"{SITE_URL}/blog",
            "publisher": {"@type": "Organization", "name": SITE_NAME},
        }
    )
    ctx.update({"posts": posts})
    return render(request, "blog.html", ctx)


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, active=True)
    other = BlogPost.objects.filter(active=True).exclude(slug=slug)[:3]
    ctx = seo_context(post.title, post.excerpt, f"{SITE_URL}/blog/{slug}", post.image)
    ctx["schema_org"] = json.dumps(
        [
            breadcrumb_schema(
                [
                    (SITE_NAME, SITE_URL),
                    ("Blog", f"{SITE_URL}/blog"),
                    (post.title, f"{SITE_URL}/blog/{slug}"),
                ]
            ),
            blog_posting_schema(post),
        ]
    )
    ctx.update({"post": post, "other_posts": other})
    return render(request, "blog_detail.html", ctx)


@require_POST
@csrf_protect
def site_rating(request):
    if not throttle_request(request, "site_rating", limit=3, window_seconds=3600):
        return JsonResponse({"ok": False, "detail": "Please wait before rating again."}, status=429)
    if cache.get(f"rating-submitted:{request_ip(request)}"):
        return JsonResponse({"ok": False, "detail": "Rating already received recently."}, status=429)
    rating = request.POST.get("rating")
    if rating and rating.isdigit() and 1 <= int(rating) <= 5:
        SiteRating.objects.create(rating=int(rating))
        cache.set(f"rating-submitted:{request_ip(request)}", True, timeout=86400)
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False, "detail": "Invalid rating."}, status=400)


def contact_view(request):
    ctx = seo_context(
        "Contact Aura Foods",
        "Reach out for orders, wholesale inquiries, or any questions.",
        f"{SITE_URL}/contact",
    )
    ctx["schema_org"] = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": SITE_NAME,
            "image": f"{SITE_URL}{DEFAULT_IMAGE}",
            "telephone": "+92-335-2832967",
            "email": "aurafoodsonline@gmail.com",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Karachi",
                "addressRegion": "Sindh",
                "addressCountry": "Pakistan",
            },
            "url": SITE_URL,
        }
    )
    ctx.update({"settings": public_settings()})
    if request.method == "POST":
        if request.POST.get("website", "").strip():
            ContactMessage.objects.create(
                name=request.POST.get("name", "").strip()[:200],
                email=(request.POST.get("email", "") or "spam@example.invalid").strip()[:254],
                phone=request.POST.get("phone", "").strip()[:50],
                message=request.POST.get("message", "").strip()[:5000],
                spam_status=ContactMessage.STATUS_SPAM,
                ip_address=request_ip(request) if request_ip(request) != "unknown" else None,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )
            ctx["success"] = "Thank you. We'll get back to you within 24 hours."
            return render(request, "contact.html", ctx)
        if not throttle_request(request, "contact", limit=5, window_seconds=3600):
            ctx["error"] = "Please wait before sending another message."
            return render(request, "contact.html", ctx, status=429)
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        message = request.POST.get("message", "").strip()
        try:
            validate_email(email)
        except ValidationError:
            ctx["error"] = "Please enter a valid email address."
            return render(request, "contact.html", ctx, status=400)
        if len(name) < 2 or len(name) > 200 or len(message) < 10 or len(message) > 2000:
            ctx["error"] = "Please enter a valid name and message between 10 and 2000 characters."
            return render(request, "contact.html", ctx, status=400)
        ContactMessage.objects.create(
            name=name,
            email=email,
            phone=phone[:50],
            message=message,
            ip_address=request_ip(request) if request_ip(request) != "unknown" else None,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )
        ctx["success"] = "Thank you. We'll get back to you within 24 hours."
    return render(request, "contact.html", ctx)


def policy_page(request, slug):
    fallback = next((item for item in REQUIRED_POLICY_PAGES if item["slug"] == slug), None)
    page = PolicyPage.objects.filter(slug=slug, is_published=True).first()
    if not page and not fallback:
        return render(request, "404.html", status=404)
    title = page.title if page else fallback["title"]
    content = page.content if page else fallback["content"]
    ctx = seo_context(
        title,
        f"{title} for Aura Foods customers.",
        f"{SITE_URL}/policies/{slug}/",
    )
    ctx.update({"page_title": title, "page_content": content, "policy_slug": slug})
    return render(request, "policy_page.html", ctx)


@ensure_csrf_cookie
def cart(request):
    ctx = seo_context(
        "Shopping Cart - Aura Foods",
        "Review your items before checkout.",
        f"{SITE_URL}/cart",
    )
    ctx["noindex"] = True
    return render(request, "cart.html", ctx)


@require_POST
@csrf_protect
def api_cart_quote(request):
    if not throttle_request(request, "cart_quote", limit=90, window_seconds=60):
        return JsonResponse(
            {
                "ok": False,
                "errors": [
                    {
                        "code": "rate_limited",
                        "message": "Please wait a moment before refreshing your cart again.",
                    }
                ],
                "warnings": [],
                "lines": [],
            },
            status=429,
        )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {
                "ok": False,
                "errors": [
                    {
                        "code": "invalid_json",
                        "message": "Your cart could not be read. Please refresh and try again.",
                    }
                ],
                "warnings": [],
                "lines": [],
            },
            status=400,
        )

    cart_payload = payload.get("items", payload if isinstance(payload, list) else [])
    try:
        quote = OrderPricingService.quote(cart_payload, city=payload.get("city", ""))
    except CartQuoteError as exc:
        return JsonResponse(
            {
                "ok": False,
                "errors": [{"code": exc.code, "message": exc.message}],
                "warnings": [],
                "lines": [],
            },
            status=400,
        )

    return JsonResponse(cart_quote_payload(quote))


@ensure_csrf_cookie
def checkout(request):
    if request.method == "POST":
        if not throttle_request(request, "checkout", limit=10, window_seconds=3600):
            ctx = seo_context("Checkout - Aura Foods", "", f"{SITE_URL}/checkout")
            ctx["error"] = "Please wait before placing another order."
            ctx["noindex"] = True
            ctx["checkout_policy_links"] = policy_links(checkout_only=True)
            return render(request, "checkout.html", ctx, status=429)
        cart_data = request.POST.get("cart_data", "[]")
        try:
            cart_payload = json.loads(cart_data)
        except json.JSONDecodeError:
            cart_payload = []

        try:
            order = OrderPlacementService.place_order(
                {
                    "customer_name": request.POST.get("fullName"),
                    "phone": request.POST.get("phone"),
                    "city": request.POST.get("city"),
                    "address": request.POST.get("address"),
                    "payment_method": request.POST.get("payment"),
                    "notes": request.POST.get("notes"),
                    "email": request.POST.get("email"),
                    "idempotency_key": request.POST.get("idempotency_key"),
                    "customer_user": request.user,
                },
                cart_payload,
            )
            if request.user.is_authenticated and not request.user.is_staff and request.POST.get("save_address"):
                CustomerAddress.objects.update_or_create(
                    user=request.user,
                    is_default=True,
                    defaults={
                        "full_name": order.customer_name,
                        "phone": order.phone,
                        "city": order.city,
                        "address": order.address,
                    },
                )
            request.session["recent_order_reference"] = order.reference
            return redirect(f"/order-confirmation/ref/{order.reference}/")
        except (ValueError, ValidationError) as exc:
            ctx = seo_context("Checkout - Aura Foods", "", f"{SITE_URL}/checkout")
            ctx["error"] = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            ctx["checkout_policy_links"] = policy_links(checkout_only=True)
            return render(request, "checkout.html", ctx)

    ctx = seo_context(
        "Checkout - Aura Foods",
        "Complete your order for premium organic Pakistani spices.",
        f"{SITE_URL}/checkout",
    )
    ctx["noindex"] = True
    ctx["checkout_policy_links"] = policy_links(checkout_only=True)
    if request.user.is_authenticated and not request.user.is_staff:
        ctx["saved_addresses"] = request.user.saved_addresses.all()
    return render(request, "checkout.html", ctx)


def customer_email_verified(user):
    return CustomerEmailVerification.objects.filter(user=user, verified_at__isnull=False).exists()


def account_register(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect("/account/")
    ctx = seo_context("Create Account - Aura Foods", "Create an Aura Foods customer account.", f"{SITE_URL}/account/register/")
    ctx["noindex"] = True
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")
        if password != confirm:
            ctx["error"] = "Passwords do not match."
            return render(request, "account_register.html", ctx, status=400)
        if User.objects.filter(username__iexact=username).exists():
            ctx["error"] = "That username is already registered."
            return render(request, "account_register.html", ctx, status=400)
        try:
            validate_email(email)
            validate_password(password)
        except ValidationError as exc:
            ctx["error"] = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return render(request, "account_register.html", ctx, status=400)
        user = User.objects.create_user(username=username, email=email, password=password)
        _verification, token = CustomerEmailVerification.create_for_user(user)
        send_customer_verification_email(user, token, request=request)
        login(request, user)
        return redirect("/account/")
    return render(request, "account_register.html", ctx)


def account_login(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect("/account/")
    ctx = seo_context("Customer Login - Aura Foods", "Log in to view your Aura Foods orders.", f"{SITE_URL}/account/login/")
    ctx["noindex"] = True
    if request.method == "POST":
        user = authenticate(username=request.POST.get("username", ""), password=request.POST.get("password", ""))
        if user and not user.is_staff:
            login(request, user)
            return redirect(request.GET.get("next") or "/account/")
        ctx["error"] = "Invalid customer credentials."
        return render(request, "account_login.html", ctx, status=401)
    return render(request, "account_login.html", ctx)


def account_password_reset_request(request):
    ctx = seo_context("Reset Password - Aura Foods", "Reset your Aura Foods account password.", f"{SITE_URL}/account/password-reset/")
    ctx["noindex"] = True
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        user = User.objects.filter(email__iexact=email, is_staff=False).first()
        if user:
            _reset, token = CustomerPasswordReset.create_for_user(user)
            send_customer_password_reset_email(user, token, request=request)
        ctx["success"] = "If that email is registered, a reset link will be sent."
    return render(request, "account_password_reset.html", ctx)


def account_password_reset_confirm(request, token):
    reset = CustomerPasswordReset.objects.filter(token_hash=CustomerPasswordReset.hash_token(token)).select_related("user").first()
    ctx = seo_context("Set New Password - Aura Foods", "Choose a new Aura Foods account password.", f"{SITE_URL}/account/password-reset/confirm/")
    ctx["noindex"] = True
    if not reset or not reset.is_usable or reset.user.is_staff:
        ctx["error"] = "This password reset link is invalid or expired."
        return render(request, "account_password_reset_confirm.html", ctx, status=400)
    if request.method == "POST":
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")
        if password != confirm:
            ctx["error"] = "Passwords do not match."
            return render(request, "account_password_reset_confirm.html", ctx, status=400)
        try:
            validate_password(password, user=reset.user)
        except ValidationError as exc:
            ctx["error"] = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return render(request, "account_password_reset_confirm.html", ctx, status=400)
        reset.user.set_password(password)
        reset.user.save(update_fields=["password"])
        reset.used_at = timezone.now()
        reset.save(update_fields=["used_at"])
        messages.success(request, "Password reset complete. Please log in.")
        return redirect("/account/login/")
    return render(request, "account_password_reset_confirm.html", ctx)


def account_verify_email(request, token):
    verification = CustomerEmailVerification.objects.filter(token_hash=CustomerEmailVerification.hash_token(token)).select_related("user").first()
    ctx = seo_context("Verify Email - Aura Foods", "Verify your Aura Foods customer email.", f"{SITE_URL}/account/verify-email/")
    ctx["noindex"] = True
    if not verification or not verification.is_usable:
        ctx["error"] = "This email verification link is invalid or expired."
        return render(request, "account_verify_email.html", ctx, status=400)
    verification.verified_at = timezone.now()
    verification.save(update_fields=["verified_at"])
    ctx["success"] = "Email verified successfully."
    return render(request, "account_verify_email.html", ctx)


@login_required(login_url="/account/login/")
def account_logout(request):
    logout(request)
    return redirect("/")


@login_required(login_url="/account/login/")
def account_profile(request):
    if request.user.is_staff:
        return redirect("/admin/dashboard/")
    ctx = seo_context("My Account - Aura Foods", "View saved addresses and order history.", f"{SITE_URL}/account/")
    ctx["noindex"] = True
    if request.method == "POST":
        CustomerAddress.objects.update_or_create(
            user=request.user,
            is_default=True,
            defaults={
                "full_name": request.POST.get("full_name", "").strip(),
                "phone": request.POST.get("phone", "").strip(),
                "city": request.POST.get("city", "").strip(),
                "address": request.POST.get("address", "").strip(),
            },
        )
        messages.success(request, "Default address saved.")
        return redirect("/account/")
    ctx["orders"] = Order.objects.filter(customer_user=request.user).prefetch_related("items").select_related("shipment").order_by("-created_at")
    ctx["addresses"] = request.user.saved_addresses.all()
    ctx["email_verified"] = customer_email_verified(request.user)
    ctx["tickets"] = request.user.support_tickets.select_related("order").order_by("-created_at")[:10]
    return render(request, "account_profile.html", ctx)


@login_required(login_url="/account/login/")
def account_order_support(request, reference):
    if request.user.is_staff:
        return redirect("/admin/dashboard/")
    order = get_object_or_404(Order, reference=reference, customer_user=request.user)
    ctx = seo_context("Order Support - Aura Foods", "Request help with your Aura Foods order.", f"{SITE_URL}/account/orders/{reference}/support/")
    ctx["noindex"] = True
    ctx["order"] = order
    if request.method == "POST":
        category = request.POST.get("category", SupportTicket.CATEGORY_SHIPPING)
        message = request.POST.get("message", "").strip()
        if len(message) < 10:
            ctx["error"] = "Please describe the issue in at least 10 characters."
            return render(request, "account_order_support.html", ctx, status=400)
        try:
            if category == SupportTicket.CATEGORY_RETURN:
                OrderLifecycleService.request_return(order, message, customer=request.user)
            if category == SupportTicket.CATEGORY_REFUND:
                OrderLifecycleService.request_refund(order, order.total, message, actor=request.user)
        except ValidationError as exc:
            ctx["error"] = "; ".join(exc.messages)
            return render(request, "account_order_support.html", ctx, status=400)
        ticket = SupportTicket.objects.create(
            user=request.user,
            order=order,
            category=category if category in dict(SupportTicket.CATEGORY_CHOICES) else SupportTicket.CATEGORY_GENERAL,
            name=request.user.get_full_name() or request.user.username,
            email=request.user.email or order.email,
            phone=order.phone,
            subject=f"Order {order.reference} support",
            message=message,
            priority="high" if category in {SupportTicket.CATEGORY_REFUND, SupportTicket.CATEGORY_COMPLAINT} else "normal",
        )
        messages.success(request, f"Support ticket {ticket.public_reference} created.")
        return redirect("/account/")
    return render(request, "account_order_support.html", ctx)


def faq_view(request):
    ctx = seo_context("FAQ - Aura Foods", "Answers about orders, delivery, returns, refunds, and spice storage.", f"{SITE_URL}/faq/")
    ctx["faqs"] = FAQItem.objects.filter(active=True)
    if not ctx["faqs"]:
        ctx["fallback_faqs"] = [
            ("Delivery", "Delivery charges and timelines are calculated server-side at checkout based on your city."),
            ("Returns", "Food products can be returned only when unopened, damaged in transit, or incorrectly supplied."),
            ("Storage", "Keep spices sealed in a cool, dry place away from sunlight and moisture."),
        ]
    return render(request, "faq.html", ctx)


def support_request(request):
    ctx = seo_context("Support - Aura Foods", "Contact Aura Foods support for orders, shipping, returns, refunds, and wholesale.", f"{SITE_URL}/support/")
    ctx["noindex"] = True
    if request.method == "POST":
        if not throttle_request(request, "support_request", limit=5, window_seconds=3600):
            ctx["error"] = "Too many support requests. Please try again later."
            return render(request, "support.html", ctx, status=429)
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        subject = request.POST.get("subject", "").strip()
        message = request.POST.get("message", "").strip()
        category = request.POST.get("category", SupportTicket.CATEGORY_GENERAL)
        try:
            validate_email(email)
        except ValidationError:
            ctx["error"] = "Please enter a valid email address."
            return render(request, "support.html", ctx, status=400)
        if min(len(name), len(subject)) < 2 or len(message) < 10:
            ctx["error"] = "Please complete the support form with enough detail."
            return render(request, "support.html", ctx, status=400)
        ticket = SupportTicket.objects.create(
            user=request.user if request.user.is_authenticated and not request.user.is_staff else None,
            category=category if category in dict(SupportTicket.CATEGORY_CHOICES) else SupportTicket.CATEGORY_GENERAL,
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            message=message,
        )
        ctx["success"] = f"Support ticket {ticket.public_reference} created."
    return render(request, "support.html", ctx)


def track_order(request):
    ctx = seo_context("Track Order - Aura Foods", "Track your Aura Foods order status and delivery progress.", f"{SITE_URL}/track-order/")
    ctx["noindex"] = True
    if request.method == "POST":
        if not throttle_request(request, "order_tracking", limit=10, window_seconds=3600):
            ctx["error"] = "Too many tracking attempts. Please try again later."
            return render(request, "track_order.html", ctx, status=429)
        reference = request.POST.get("reference", "").strip()
        phone = request.POST.get("phone", "").strip()
        normalize_phone = lambda value: re.sub(r"\D", "", value or "")
        order = Order.objects.filter(reference=reference).select_related("shipment").first()
        if order and (not normalize_phone(phone) or normalize_phone(phone) != normalize_phone(order.phone)):
            order = None
        if not order:
            ctx["error"] = "No matching order was found."
            return render(request, "track_order.html", ctx, status=404)
        ctx["order"] = order
        ctx["shipment"] = getattr(order, "shipment", None)
    return render(request, "track_order.html", ctx)


def order_confirmation(request, oid=None, reference=None):
    order = None
    if reference:
        if not throttle_request(request, "order_lookup", limit=30, window_seconds=3600):
            return render(request, "404.html", status=404)
        order = Order.objects.prefetch_related("items").filter(reference=reference).first()
        if not order:
            return render(request, "404.html", status=404)
    elif oid:
        if has_erp_permission(request.user, "sales.view"):
            order = Order.objects.prefetch_related("items").filter(id=oid).first()
        else:
            recent_reference = request.session.get("recent_order_reference")
            candidate = Order.objects.prefetch_related("items").filter(id=oid).first()
            if candidate and recent_reference and candidate.reference == recent_reference:
                return redirect(f"/order-confirmation/ref/{candidate.reference}/")
            return render(request, "404.html", status=404)
        if not order:
            return render(request, "404.html", status=404)

    if not order:
        recent_reference = request.session.get("recent_order_reference")
        if recent_reference:
            order = Order.objects.prefetch_related("items").filter(reference=recent_reference).first()

    ctx = seo_context(
        "Order Confirmed - Aura Foods",
        "Your order has been placed successfully.",
        f"{SITE_URL}/order-confirmation",
    )
    recent_reference = request.session.get("recent_order_reference")
    is_staff = has_erp_permission(request.user, "sales.view")
    ctx["order"] = order
    ctx["shipment"] = getattr(order, "shipment", None) if order else None
    ctx["show_order_private_details"] = bool(
        order and (is_staff or order.reference == recent_reference)
    )
    ctx["noindex"] = True
    return render(request, "order_confirmation.html", ctx)


def ensure_kg_variant(product):
    if ProductVariant.objects.filter(product=product, weight_value=Decimal("1"), weight_unit=ProductVariant.UNIT_KILOGRAMS).exists():
        return
    default = product.default_variant
    if not default:
        return
    grams = (
        default.weight_value
        if default.weight_unit == ProductVariant.UNIT_GRAMS
        else default.weight_value * Decimal("1000")
    )
    factor = (Decimal("1000") / grams).quantize(Decimal("0.001"))
    ProductVariant.objects.create(
        product=product,
        sku=f"AURA-{product.id}-1kg",
        weight_value=Decimal("1"),
        weight_unit=ProductVariant.UNIT_KILOGRAMS,
        price=parse_decimal(default.price * factor),
        old_price=parse_decimal(default.old_price * factor),
        active=True,
        sellable=True,
        sort_order=999,
    )


def search_view(request):
    query = request.GET.get("q", "").strip()
    products = catalog_queryset()
    no_results = False
    if query:
        terms = [term for term in re.split(r"\s+", query) if term]
        q_filter = Q()
        for term in terms:
            q_filter &= (
                Q(name__icontains=term)
                | Q(tagline__icontains=term)
                | Q(description__icontains=term)
                | Q(category__name__icontains=term)
            )
        matched = products.filter(q_filter)
        no_results = not matched.exists()
        if not no_results:
            products = matched
    page = Paginator(products, 24).get_page(request.GET.get("page"))
    page.object_list = list(page.object_list)
    hydrate_catalog_availability(page.object_list)
    ctx = seo_context(
        f'Search results for "{query}"' if query else "Search - Aura Foods",
        f'Find your favorite organic Pakistani spices. {len(page.object_list)} products found for "{query}".'
        if query
        else "Search our collection of pure organic spices.",
        f"{SITE_URL}/search",
    )
    ctx["noindex"] = True
    ctx.update(
        {
            "query": query,
            "no_results": no_results,
            "products": page,
            "page_obj": page,
            "categories": cats_with_slugs(Category.objects.all()),
            "active_category": "",
        }
    )
    return render(request, "shop.html", ctx)


def sitemap_xml(request):
    from datetime import date

    ctx = {
        "products": catalog_queryset(),
        "posts": BlogPost.objects.filter(active=True),
        "categories": cats_with_slugs(Category.objects.all()),
        "now": date.today(),
    }
    return render(request, "sitemap.xml", ctx, content_type="application/xml")


def robots_txt(request):
    return render(request, "robots.txt", content_type="text/plain")


def handler404(request, exception):
    return render(request, "404.html", status=404)


def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("/admin/dashboard/")
    error = None
    mfa_required = False
    pending_username = ""
    if request.method == "POST":
        username = request.POST.get("username", "")
        fail_key, lock_key = admin_login_cache_keys(request, username)
        if cache.get(lock_key):
            log_admin_event(request, "admin_login_locked", object_repr=username, severity=AdminActivityLog.SEVERITY_CRITICAL)
            return render(request, "admin/login.html", {"error": "Too many failed attempts. Please try again later."}, status=429)
        user = authenticate(
            username=username,
            password=request.POST.get("password"),
        )
        if user and user.is_staff:
            if staff_mfa_required(user):
                if not confirmed_device_for(user):
                    log_admin_event(
                        request,
                        "mfa_missing_device",
                        object_repr=user.username,
                        severity=AdminActivityLog.SEVERITY_CRITICAL,
                    )
                    return render(
                        request,
                        "admin/login.html",
                        {
                            "error": "Staff MFA is required. Ask a superuser to enroll an authenticator device before login.",
                            "mfa_required": False,
                        },
                        status=403,
                    )
                token = request.POST.get("mfa_token", "")
                if not verify_staff_token(user, token):
                    failures = cache.get(fail_key, 0) + 1
                    cache.set(fail_key, failures, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
                    log_admin_event(
                        request,
                        "mfa_login_failure",
                        object_repr=user.username,
                        new_value={"failures": failures},
                        severity=AdminActivityLog.SEVERITY_WARNING,
                    )
                    if failures >= settings.ADMIN_LOGIN_FAILURE_LIMIT:
                        cache.set(lock_key, True, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
                    return render(
                        request,
                        "admin/login.html",
                        {
                            "error": "Enter the current authenticator code.",
                            "mfa_required": True,
                            "pending_username": username,
                        },
                        status=401,
                    )
            cache.delete(fail_key)
            cache.delete(lock_key)
            login(request, user)
            log_admin_event(
                request,
                "mfa_login_success" if staff_mfa_required(user) else "admin_login_success",
                object_repr=user.username,
                severity=AdminActivityLog.SEVERITY_INFO,
            )
            return redirect("/admin/dashboard/")
        failures = cache.get(fail_key, 0) + 1
        cache.set(fail_key, failures, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
        log_admin_event(
            request,
            "admin_login_failure",
            object_repr=username,
            new_value={"failures": failures},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
        if failures >= settings.ADMIN_LOGIN_FAILURE_LIMIT:
            cache.set(lock_key, True, timeout=settings.ADMIN_LOGIN_LOCKOUT_SECONDS)
        error = "Invalid credentials"
    return render(request, "admin/login.html", {"error": error, "mfa_required": mfa_required, "pending_username": pending_username})


@django_staff_member_required(login_url="/admin/login/")
def admin_logout_view(request):
    logout(request)
    return redirect("/admin/login/")


@django_staff_member_required(login_url="/admin/login/")
def admin_dashboard(request):
    can_catalog = has_erp_permission(request.user, "admin.configure")
    can_sales = has_erp_permission(request.user, "sales.view")
    can_crm = has_erp_permission(request.user, "crm.view")
    can_sales_manage = has_erp_permission(request.user, "sales.manage")
    can_sales_dispatch = has_erp_permission(request.user, "sales.dispatch")
    products = catalog_queryset() if can_catalog else Product.objects.none()
    categories = Category.objects.all() if can_catalog else Category.objects.none()
    category_products = {}
    for category in categories:
        category_products[category.id] = products.filter(category=category)
    ctx = {
        "products": products,
        "recent_products": products[:5],
        "categories": categories,
        "category_products": category_products,
        "testimonials": Testimonial.objects.filter(active=True) if can_catalog else Testimonial.objects.none(),
        "bundles": Bundle.objects.all() if can_catalog else Bundle.objects.none(),
        "blog_posts": BlogPost.objects.filter(active=True) if can_catalog else BlogPost.objects.none(),
        "why_items": WhyItem.objects.all() if can_catalog else WhyItem.objects.none(),
        "messages": ContactMessage.objects.all().order_by("-created_at") if can_crm else ContactMessage.objects.none(),
        "orders": Order.objects.all().order_by("-created_at") if can_sales else Order.objects.none(),
        "settings": public_settings() if can_catalog else {},
        "can_catalog": can_catalog,
        "can_sales": can_sales,
        "can_sales_manage": can_sales_manage,
        "can_sales_dispatch": can_sales_dispatch,
        "can_crm": can_crm,
    }
    return render(request, "admin/dashboard.html", ctx)


@staff_member_required(login_url="/admin/login/")
def admin_product_add(request):
    if request.method == "POST":
        payload = build_product_payload(request)
        product = Product.objects.create(**payload)
        if request.FILES.get("file"):
            image_url = save_uploaded_image(request.FILES["file"], f"products/{product.id}")
            Product.objects.filter(id=product.id).update(image=image_url)
        sync_product_variants(product)
        apply_variant_form(product, request)
        ensure_kg_variant(product)
        log_admin_activity(
            request=request,
            action="product_add",
            model_name="Product",
            object_id=product.id,
            object_repr=product.name,
            new_value=audit_snapshot(product, ["name", "price", "old_price", "weight"]),
            severity=AdminActivityLog.SEVERITY_CRITICAL,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_product_edit(request, pid):
    if request.method == "POST":
        product = get_object_or_404(Product, id=pid)
        old_value = audit_snapshot(product, ["name", "price", "old_price", "weight", "category_id"])
        payload = build_product_payload(request, product=product)
        for field, value in payload.items():
            setattr(product, field, value)
        if request.FILES.get("file"):
            product.image = save_uploaded_image(request.FILES["file"], f"products/{pid}")
        product.save()
        sync_product_variants(product)
        apply_variant_form(product, request)
        handle_removed_variants(product, request)
        log_admin_activity(
            request=request,
            action="product_edit",
            model_name="Product",
            object_id=product.id,
            object_repr=product.name,
            old_value=old_value,
            new_value=audit_snapshot(product, ["name", "price", "old_price", "weight", "category_id"]),
            severity=AdminActivityLog.SEVERITY_CRITICAL if old_value and old_value.get("price") != str(product.price) else AdminActivityLog.SEVERITY_INFO,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_product_delete(request, pid):
    if request.method == "POST":
        product = Product.objects.filter(id=pid).first()
        old_value = audit_snapshot(product, ["name", "price", "weight"]) if product else None
        object_repr = product.name if product else str(pid)
        Product.objects.filter(id=pid).delete()
        log_admin_activity(
            request=request,
            action="product_delete",
            model_name="Product",
            object_id=pid,
            object_repr=object_repr,
            old_value=old_value,
            severity=AdminActivityLog.SEVERITY_CRITICAL,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_product_image(request, pid):
    if request.method == "POST" and request.FILES.get("file"):
        image_url = save_uploaded_image(request.FILES["file"], f"products/{pid}")
        Product.objects.filter(id=pid).update(image=image_url)
        product = Product.objects.filter(id=pid).first()
        log_admin_activity(
            request=request,
            action="product_image_upload",
            model_name="Product",
            object_id=pid,
            object_repr=product.name if product else image_url,
            new_value={"image": image_url},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_category_add(request):
    if request.method == "POST":
        category = Category.objects.create(name=request.POST.get("name", "").strip())
        log_admin_activity(
            request=request,
            action="category_add",
            model_name="Category",
            object_id=category.id,
            object_repr=category.name,
            new_value=audit_snapshot(category, ["name"]),
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_category_edit(request, cid):
    if request.method == "POST":
        category = get_object_or_404(Category, id=cid)
        old_value = audit_snapshot(category, ["name"])
        category.name = request.POST.get("name", "").strip()
        category.save(update_fields=["name"])
        log_admin_activity(
            request=request,
            action="category_edit",
            model_name="Category",
            object_id=category.id,
            object_repr=category.name,
            old_value=old_value,
            new_value=audit_snapshot(category, ["name"]),
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_category_delete(request, cid):
    if request.method == "POST":
        category = Category.objects.filter(id=cid).first()
        old_value = audit_snapshot(category, ["name"]) if category else None
        object_repr = category.name if category else str(cid)
        Category.objects.filter(id=cid).delete()
        log_admin_activity(
            request=request,
            action="category_delete",
            model_name="Category",
            object_id=cid,
            object_repr=object_repr,
            old_value=old_value,
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_category_image(request, cid):
    if request.method == "POST" and request.FILES.get("file"):
        image_url = save_uploaded_image(request.FILES["file"], f"categories/{cid}")
        Category.objects.filter(id=cid).update(image=image_url)
        category = Category.objects.filter(id=cid).first()
        log_admin_activity(
            request=request,
            action="category_image_upload",
            model_name="Category",
            object_id=cid,
            object_repr=category.name if category else image_url,
            new_value={"image": image_url},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_category_manage_products(request, cid):
    if request.method == "POST":
        assigned_ids = [int(value) for value in request.POST.getlist("product_ids") if value.isdigit()]
        Product.objects.filter(category_id=cid).update(category=None)
        Product.objects.filter(id__in=assigned_ids).update(category_id=cid)
        log_admin_activity(
            request=request,
            action="category_products_update",
            model_name="Category",
            object_id=cid,
            new_value={"product_ids": assigned_ids},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
        return JsonResponse({"ok": True})
    return JsonResponse({"detail": "Method not allowed."}, status=405)


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def api_category_products(request, cid):
    category = get_object_or_404(Category, id=cid)
    all_products = catalog_queryset()
    assigned_ids = list(all_products.filter(category_id=cid).values_list("id", flat=True))
    return Response(
        {
            "category": category.name,
            "all_products": ProductSerializer(all_products, many=True).data,
            "assigned_ids": assigned_ids,
        }
    )


@staff_member_required(login_url="/admin/login/")
def admin_testimonial_add(request):
    if request.method == "POST":
        testimonial = Testimonial.objects.create(
            name=request.POST.get("name", "").strip(),
            city=request.POST.get("city", "").strip(),
            text=request.POST.get("text", "").strip(),
        )
        log_admin_activity(
            request=request,
            action="testimonial_add",
            model_name="Testimonial",
            object_id=testimonial.id,
            object_repr=testimonial.name,
            new_value=audit_snapshot(testimonial, ["name", "city"]),
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_testimonial_delete(request, tid):
    if request.method == "POST":
        testimonial = Testimonial.objects.filter(id=tid).first()
        old_value = audit_snapshot(testimonial, ["name", "city"]) if testimonial else None
        Testimonial.objects.filter(id=tid).delete()
        log_admin_activity(
            request=request,
            action="testimonial_delete",
            model_name="Testimonial",
            object_id=tid,
            object_repr=testimonial.name if testimonial else str(tid),
            old_value=old_value,
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_bundle_edit(request, bid):
    if request.method == "POST":
        bundle = get_object_or_404(Bundle, id=bid)
        old_value = audit_snapshot(bundle, ["name", "items", "price", "old_price"])
        bundle.name = request.POST.get("name", bundle.name).strip()
        bundle.items = request.POST.get("items", bundle.items).strip()
        bundle.price = parse_decimal(request.POST.get("price", bundle.price))
        bundle.old_price = parse_decimal(request.POST.get("old_price", bundle.old_price))
        bundle.save_percent = (
            round((1 - (bundle.price / bundle.old_price)) * 100)
            if bundle.old_price > bundle.price and bundle.old_price > 0
            else 0
        )
        if request.FILES.get("file"):
            bundle.image = save_uploaded_image(request.FILES["file"], f"bundles/{bid}")
        bundle.save()
        log_admin_activity(
            request=request,
            action="bundle_edit",
            model_name="Bundle",
            object_id=bundle.id,
            object_repr=bundle.name,
            old_value=old_value,
            new_value=audit_snapshot(bundle, ["name", "items", "price", "old_price"]),
            severity=AdminActivityLog.SEVERITY_CRITICAL if old_value and old_value.get("price") != str(bundle.price) else AdminActivityLog.SEVERITY_INFO,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_bundle_manage_products(request, bid):
    if request.method == "POST":
        assigned_ids = [int(value) for value in request.POST.getlist("product_ids") if value.isdigit()]
        names = list(Product.objects.filter(id__in=assigned_ids).values_list("name", flat=True))
        Bundle.objects.filter(id=bid).update(items=", ".join(names))
        log_admin_activity(
            request=request,
            action="bundle_products_update",
            model_name="Bundle",
            object_id=bid,
            new_value={"product_ids": assigned_ids},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
        return JsonResponse({"ok": True})
    return JsonResponse({"detail": "Method not allowed."}, status=405)


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def api_bundle_products(request, bid):
    bundle = get_object_or_404(Bundle, id=bid)
    all_products = catalog_queryset()
    assigned_names = [name.strip() for name in bundle.items.split(",")] if bundle.items else []
    assigned_ids = list(all_products.filter(name__in=assigned_names).values_list("id", flat=True))
    return Response(
        {
            "bundle": bundle.name,
            "all_products": ProductSerializer(all_products, many=True).data,
            "assigned_ids": assigned_ids,
        }
    )


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def api_bundle_add_to_cart(request, bid):
    bundle = get_object_or_404(Bundle, id=bid)
    assigned_names = [name.strip() for name in bundle.items.split(",")] if bundle.items else []
    products = [product for product in catalog_queryset().filter(name__in=assigned_names) if product.default_variant]
    return Response(
        {
            "bundle_name": bundle.name,
            "bundle_price": float(bundle.price),
            "products": ProductSerializer(products, many=True).data,
        }
    )


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def api_bundle_detail(request, bid):
    return Response(BundleSerializer(get_object_or_404(Bundle, id=bid)).data)


@staff_member_required(login_url="/admin/login/")
def admin_bundle_add(request):
    if request.method == "POST":
        price = parse_decimal(request.POST.get("price", "0"))
        old_price = parse_decimal(request.POST.get("old_price", "0"))
        save_percent = round((1 - (price / old_price)) * 100) if old_price > price and old_price > 0 else 0
        bundle = Bundle.objects.create(
            name=request.POST.get("name", "").strip(),
            items=request.POST.get("items", "").strip(),
            price=price,
            old_price=old_price,
            save_percent=save_percent,
        )
        log_admin_activity(
            request=request,
            action="bundle_add",
            model_name="Bundle",
            object_id=bundle.id,
            object_repr=bundle.name,
            new_value=audit_snapshot(bundle, ["name", "items", "price", "old_price"]),
            severity=AdminActivityLog.SEVERITY_CRITICAL,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_bundle_delete(request, bid):
    if request.method == "POST":
        bundle = Bundle.objects.filter(id=bid).first()
        old_value = audit_snapshot(bundle, ["name", "items", "price"]) if bundle else None
        Bundle.objects.filter(id=bid).delete()
        log_admin_activity(
            request=request,
            action="bundle_delete",
            model_name="Bundle",
            object_id=bid,
            object_repr=bundle.name if bundle else str(bid),
            old_value=old_value,
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_blog_add(request):
    if request.method == "POST":
        post = BlogPost.objects.create(
            slug=slugify(request.POST.get("title", "")),
            title=request.POST.get("title", "").strip(),
            category=request.POST.get("category", "General").strip(),
            read_time=request.POST.get("read_time", "5 min").strip(),
            excerpt=request.POST.get("excerpt", "").strip(),
            content=request.POST.get("content", "").strip(),
        )
        log_admin_activity(
            request=request,
            action="blog_add",
            model_name="BlogPost",
            object_id=post.id,
            object_repr=post.title,
            new_value=audit_snapshot(post, ["title", "category", "read_time"]),
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_blog_delete(request, bid):
    if request.method == "POST":
        post = BlogPost.objects.filter(id=bid).first()
        old_value = audit_snapshot(post, ["title", "category"]) if post else None
        BlogPost.objects.filter(id=bid).delete()
        log_admin_activity(
            request=request,
            action="blog_delete",
            model_name="BlogPost",
            object_id=bid,
            object_repr=post.title if post else str(bid),
            old_value=old_value,
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_blog_image(request, bid):
    if request.method == "POST" and request.FILES.get("file"):
        image_url = save_uploaded_image(request.FILES["file"], f"blog/{bid}")
        BlogPost.objects.filter(id=bid).update(image=image_url)
        post = BlogPost.objects.filter(id=bid).first()
        log_admin_activity(
            request=request,
            action="blog_image_upload",
            model_name="BlogPost",
            object_id=bid,
            object_repr=post.title if post else image_url,
            new_value={"image": image_url},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_bundle_image(request, bid):
    if request.method == "POST" and request.FILES.get("file"):
        image_url = save_uploaded_image(request.FILES["file"], f"bundles/{bid}")
        Bundle.objects.filter(id=bid).update(image=image_url)
        bundle = Bundle.objects.filter(id=bid).first()
        log_admin_activity(
            request=request,
            action="bundle_image_upload",
            model_name="Bundle",
            object_id=bid,
            object_repr=bundle.name if bundle else image_url,
            new_value={"image": image_url},
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_why_edit(request, wid):
    if request.method == "POST":
        item = get_object_or_404(WhyItem, id=wid)
        old_value = audit_snapshot(item, ["title", "description"])
        item.title = request.POST.get("title", "").strip()
        item.description = request.POST.get("description", "").strip()
        item.save(update_fields=["title", "description"])
        log_admin_activity(
            request=request,
            action="why_item_edit",
            model_name="WhyItem",
            object_id=item.id,
            object_repr=item.title,
            old_value=old_value,
            new_value=audit_snapshot(item, ["title", "description"]),
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_settings_save(request):
    if request.method == "POST":
        keys = [
            "site_name",
            "site_tagline",
            "hero_title",
            "hero_subtitle",
            "hero_badge",
            "about_title",
            "about_content",
            "phone",
            "email",
            "address",
            "whatsapp",
            "story_location",
            "free_delivery_min",
            "delivery_charge",
        ]
        old_value = {key: Setting.objects.filter(key=key).values_list("value", flat=True).first() for key in keys}
        new_value = {}
        for key in keys:
            value = request.POST.get(f"setting_{key}", "").strip()
            Setting.objects.update_or_create(key=key, defaults={"value": value})
            new_value[key] = value
        log_admin_activity(
            request=request,
            action="settings_update",
            model_name="Setting",
            object_repr="Site settings",
            old_value=old_value,
            new_value=new_value,
            severity=AdminActivityLog.SEVERITY_CRITICAL,
        )
    return redirect("/admin/dashboard/")


@django_staff_member_required(login_url="/admin/login/")
def admin_change_password(request):
    if request.method == "POST":
        user = request.user
        old_password = request.POST.get("current", "")
        new_password = request.POST.get("newpass", "")
        if not user.check_password(old_password):
            messages.error(request, "Current password is incorrect.")
        else:
            try:
                validate_password(new_password, user=user)
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)
                log_admin_activity(
                    request=request,
                    action="password_change",
                    model_name="User",
                    object_id=user.id,
                    object_repr=user.username,
                    severity=AdminActivityLog.SEVERITY_CRITICAL,
                )
                messages.success(request, "Password changed successfully.")
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
    return redirect("/admin/dashboard/")


@django_staff_member_required(login_url="/admin/login/")
def admin_order_update_status(request, oid):
    if request.method == "POST":
        status = request.POST.get("status", Order.STATUS_PENDING)
        required = "sales.dispatch" if status in {Order.STATUS_SHIPPED, Order.STATUS_DELIVERED} else "sales.manage"
        if not has_erp_permission(request.user, required):
            raise PermissionDenied(f"Order status '{status}' requires {required} permission.")
        order = get_object_or_404(Order, id=oid)
        try:
            if status == Order.STATUS_CANCELLED:
                OrderLifecycleService.cancel_order(order, actor=request.user, note="Admin status update")
            else:
                OrderLifecycleService.transition_order(order, status, actor=request.user, note="Admin status update")
            log_admin_activity(
                request=request,
                action="order_status_update",
                model_name="Order",
                object_id=order.id,
                object_repr=order.reference,
                new_value={"status": status},
                severity=AdminActivityLog.SEVERITY_CRITICAL if status == Order.STATUS_CANCELLED else AdminActivityLog.SEVERITY_WARNING,
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_message_delete(request, mid):
    if request.method == "POST":
        message = ContactMessage.objects.filter(id=mid).first()
        old_value = audit_snapshot(message, ["name", "email", "spam_status"]) if message else None
        ContactMessage.objects.filter(id=mid).delete()
        log_admin_activity(
            request=request,
            action="contact_message_delete",
            model_name="ContactMessage",
            object_id=mid,
            object_repr=message.name if message else str(mid),
            old_value=old_value,
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
    return redirect("/admin/dashboard/")


@staff_member_required(login_url="/admin/login/")
def admin_upload_image(request):
    if request.method == "POST" and request.FILES.get("file"):
        file_obj = request.FILES["file"]
        target = request.POST.get("target", "uploads")
        image_url = save_uploaded_image(file_obj, target)
        if target == "hero":
            Setting.objects.update_or_create(key="hero_image", defaults={"value": image_url})
        elif target == "story":
            Setting.objects.update_or_create(key="story_image", defaults={"value": image_url})
        log_admin_activity(
            request=request,
            action="site_image_upload",
            model_name="Setting",
            object_repr=target,
            new_value={"target": target, "image": image_url},
            severity=AdminActivityLog.SEVERITY_CRITICAL,
        )
    return redirect("/admin/dashboard/")


class ProductViewSet(viewsets.ModelViewSet):
    queryset = catalog_queryset()
    serializer_class = ProductSerializer
    permission_classes = [ReadOnlyOrStaffPermission]
    lookup_field = "id"

    def get_queryset(self):
        queryset = catalog_queryset()
        return queryset[:200] if self.action == "list" else queryset

    def get_serializer_class(self):
        if self.request and has_erp_permission(self.request.user, "admin.configure"):
            return AdminProductSerializer
        return ProductSerializer

    def list(self, request, *args, **kwargs):
        products = list(self.filter_queryset(self.get_queryset()))
        hydrate_catalog_availability(products)
        return Response(self.get_serializer(products, many=True).data)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [ReadOnlyOrStaffPermission]


class BundleViewSet(viewsets.ModelViewSet):
    queryset = Bundle.objects.all()
    serializer_class = BundleSerializer
    permission_classes = [ReadOnlyOrStaffPermission]


class TestimonialViewSet(viewsets.ModelViewSet):
    queryset = Testimonial.objects.filter(active=True)
    serializer_class = TestimonialSerializer
    permission_classes = [ReadOnlyOrStaffPermission]


class BlogPostViewSet(viewsets.ModelViewSet):
    queryset = BlogPost.objects.filter(active=True)
    serializer_class = BlogPostSerializer
    permission_classes = [ReadOnlyOrStaffPermission]


class WhyItemViewSet(viewsets.ModelViewSet):
    queryset = WhyItem.objects.all()
    serializer_class = WhyItemSerializer
    permission_classes = [ReadOnlyOrStaffPermission]


class SettingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Setting.objects.filter(key__in=PUBLIC_SETTING_KEYS)
    serializer_class = SettingSerializer
    permission_classes = [permissions.AllowAny]


class ContactMessageViewSet(viewsets.ModelViewSet):
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageSerializer
    permission_classes = [CRMSourcePermission]


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def api_product_detail(request, pid):
    product = get_object_or_404(catalog_queryset(), id=pid)
    hydrate_catalog_availability([product])
    serializer_class = AdminProductSerializer if has_erp_permission(request.user, "admin.configure") else ProductSerializer
    return Response(serializer_class(product).data)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def api_delivery_settings(request):
    free_min = (
        Setting.objects.filter(key="free_delivery_min").values_list("value", flat=True).first()
        or "500"
    )
    charge = (
        Setting.objects.filter(key="delivery_charge").values_list("value", flat=True).first()
        or "150"
    )
    return Response(
        {
            "free_delivery_min": float(parse_decimal(free_min)),
            "delivery_charge": float(parse_decimal(charge)),
            "zones": [
                {
                    "name": zone.name,
                    "city_pattern": zone.city_pattern,
                    "base_charge": float(zone.base_charge),
                    "free_delivery_min": float(zone.free_delivery_min),
                    "eta": zone.eta_label,
                    "courier_hint": zone.courier_hint,
                }
                for zone in DeliveryZone.objects.filter(active=True)
            ],
        }
    )
