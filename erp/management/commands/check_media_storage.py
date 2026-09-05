from __future__ import annotations

from pathlib import Path
import os
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run a write/read/delete diagnostic against the configured default media storage."

    def add_arguments(self, parser):
        parser.add_argument("--write-test", action="store_true", help="Perform a write/read/delete storage test.")

    def handle(self, *args, **options):
        backend = getattr(settings, "MEDIA_STORAGE_BACKEND", "local")
        self.stdout.write(f"Media storage backend: {backend}")
        if backend in {"s3", "r2", "s3-compatible"}:
            required = ("AWS_STORAGE_BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
            missing = [name for name in required if not os.environ.get(name)]
            if missing:
                raise CommandError("Missing production media storage settings: " + ", ".join(missing))
        if not options["write_test"]:
            self.stdout.write("Default storage class: %s" % default_storage.__class__.__name__)
            if backend == "local":
                self.stdout.write("Local media root: %s" % getattr(settings, "MEDIA_ROOT", ""))
            self.stdout.write("Write test skipped. Re-run with --write-test in staging when credentials are configured.")
            return
        name = f"diagnostics/storage-check-{uuid4().hex}.txt"
        content = b"aurafoods-storage-check"
        saved = default_storage.save(name, ContentFile(content))
        try:
            with default_storage.open(saved, "rb") as handle:
                read_back = handle.read()
            if read_back != content:
                raise RuntimeError("Media storage read-back content mismatch.")
            self.stdout.write(self.style.SUCCESS(f"Media storage write/read/delete OK: {saved}"))
        finally:
            if default_storage.exists(saved):
                default_storage.delete(saved)
            # Remove the local diagnostics directory when using FileSystemStorage.
            path = Path(getattr(settings, "MEDIA_ROOT", "")) / "diagnostics"
            if path.exists() and not any(path.iterdir()):
                path.rmdir()
