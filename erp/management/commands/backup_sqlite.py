from pathlib import Path
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Create a timestamped SQLite database backup for local deployments."

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        if database["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("backup_sqlite is only for local SQLite deployments. Use provider-native backups for production databases.")
        source = Path(database["NAME"])
        if not source.exists():
            raise CommandError(f"SQLite database not found: {source}")
        backup_dir = settings.BASE_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S-%f")
        target = backup_dir / f"aurafoods-{stamp}.sqlite3"
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_db:
            with sqlite3.connect(target) as target_db:
                source_db.backup(target_db)
        self.stdout.write(str(target))
