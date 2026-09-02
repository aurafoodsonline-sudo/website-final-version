from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext


class Command(BaseCommand):
    help = "Run lightweight release performance budgets for critical storefront pages."

    DEFAULT_BUDGETS = {
        "/": 40,
        "/shop/": 45,
        "/cart/": 15,
        "/checkout/": 25,
        "/faq/": 20,
    }

    def add_arguments(self, parser):
        parser.add_argument("--max-bytes", type=int, default=350_000)

    def handle(self, *args, **options):
        client = Client(HTTP_HOST="localhost")
        failures = []
        for path, query_budget in self.DEFAULT_BUDGETS.items():
            with CaptureQueriesContext(connection) as captured:
                response = client.get(path)
            byte_count = len(response.content or b"")
            self.stdout.write(
                f"{path} status={response.status_code} queries={len(captured)} bytes={byte_count}"
            )
            if response.status_code >= 400:
                failures.append(f"{path} returned {response.status_code}")
            if len(captured) > query_budget:
                failures.append(f"{path} used {len(captured)} queries, budget {query_budget}")
            if byte_count > options["max_bytes"]:
                failures.append(f"{path} rendered {byte_count} bytes, budget {options['max_bytes']}")
        if failures:
            raise CommandError("; ".join(failures))
        self.stdout.write(self.style.SUCCESS("Release performance budgets passed."))
