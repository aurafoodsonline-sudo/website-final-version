from django.core.management.base import BaseCommand

from erp.scheduled_jobs import refresh_expiry_statuses


class Command(BaseCommand):
    help = "Refresh current, near-expiry, and expired stock classifications and log the job."

    def handle(self, *args, **options):
        log = refresh_expiry_statuses()
        self.stdout.write(self.style.SUCCESS(f"{log.job_name}: {log.status}; {log.message}"))
