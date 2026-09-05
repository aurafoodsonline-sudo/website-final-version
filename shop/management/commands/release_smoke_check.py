from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from shop.models import Category, Product
from shop.views import slugify


class Command(BaseCommand):
    help = "Run a local smoke check for storefront, account, support, policy, and admin entry routes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail when optional catalog detail routes cannot be checked because no product/category exists.",
        )

    def handle(self, *args, **options):
        client = Client(HTTP_HOST="localhost")
        routes = [
            ("/", "home"),
            ("/shop/", "shop"),
            ("/cart/", "cart"),
            ("/checkout/", "checkout"),
            ("/account/login/", "account login"),
            ("/account/register/", "account register"),
            ("/account/password-reset/", "password reset"),
            ("/support/", "support"),
            ("/faq/", "faq"),
            ("/track-order/", "track order"),
            ("/contact/", "contact"),
            ("/policies/privacy-policy/", "privacy policy"),
            ("/policies/terms-and-conditions/", "terms policy"),
            ("/admin/login/", "admin login"),
        ]

        product = Product.objects.filter(active=True).order_by("id").first()
        category = Category.objects.order_by("id").first()
        skipped = []
        if product:
            routes.append((f"/product/{product.slug}/", "product detail"))
        else:
            skipped.append("product detail")
        if category:
            routes.append((f"/category/{slugify(category.name)}/", "category detail"))
        else:
            skipped.append("category detail")

        failures = []
        for path, label in routes:
            response = client.get(path)
            self.stdout.write(f"{label}: {path} status={response.status_code}")
            if response.status_code >= 400:
                failures.append(f"{label} {path} returned {response.status_code}")

        if skipped:
            message = "Skipped optional routes with no local data: " + ", ".join(skipped)
            if options["strict"]:
                raise CommandError(message)
            self.stdout.write(message)

        if failures:
            raise CommandError("; ".join(failures))

        self.stdout.write("Release smoke checks passed.")
