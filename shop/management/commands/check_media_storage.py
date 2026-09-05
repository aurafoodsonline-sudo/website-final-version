import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Diagnose local or S3-compatible media storage without printing credentials."

    def add_arguments(self, parser):
        parser.add_argument(
            "--write-test",
            action="store_true",
            help="Upload and delete a small diagnostic file using the configured media storage.",
        )

    def handle(self, *args, **options):
        backend = getattr(settings, "MEDIA_STORAGE_BACKEND", "local")
        self.stdout.write(f"Media storage backend: {backend}")
        self.stdout.write(f"Default storage class: {default_storage.__class__.__module__}.{default_storage.__class__.__name__}")

        if backend in {"s3", "r2", "s3-compatible"}:
            required = ["AWS_STORAGE_BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
            missing = [name for name in required if not getattr(settings, "STORAGES", {}).get("default") or not os.environ.get(name)]
            if missing:
                raise CommandError("Missing production media storage settings: " + ", ".join(missing))
        else:
            self.stdout.write(f"Local media root: {settings.MEDIA_ROOT}")

        if options["write_test"]:
            path = "diagnostics/media-storage-check.txt"
            saved_path = default_storage.save(path, ContentFile(b"aura-foods-media-storage-check"))
            try:
                url = default_storage.url(saved_path)
                self.stdout.write(f"Write test saved: {saved_path}")
                self.stdout.write(f"URL generated: {url}")
            finally:
                default_storage.delete(saved_path)
                self.stdout.write("Write test file deleted.")
        else:
            self.stdout.write("Write test skipped. Re-run with --write-test in staging when credentials are configured.")
