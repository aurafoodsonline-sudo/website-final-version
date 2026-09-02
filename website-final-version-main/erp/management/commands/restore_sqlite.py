from pathlib import Path
from shutil import copy2

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restore a local SQLite database backup. Requires --confirm."

    def add_arguments(self, parser):
        parser.add_argument("backup_path")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Restore refused. Re-run with --confirm after stopping application traffic.")
        database = settings.DATABASES["default"]
        if database["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("restore_sqlite is only for local SQLite deployments. Use provider-native restore for production databases.")
        source = Path(options["backup_path"]).resolve()
        if not source.exists() or source.suffix != ".sqlite3":
            raise CommandError("Backup file must exist and use the .sqlite3 extension.")
        target = Path(database["NAME"])
        copy2(source, target)
        self.stdout.write(self.style.SUCCESS(f"Restored SQLite database from {source}"))
