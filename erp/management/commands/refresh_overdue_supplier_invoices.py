from django.core.management.base import BaseCommand

from erp.scheduled_jobs import refresh_overdue_supplier_invoices


class Command(BaseCommand):
    help = "Refresh overdue supplier invoice statuses and log the job."

    def handle(self, *args, **options):
        log = refresh_overdue_supplier_invoices()
        self.stdout.write(self.style.SUCCESS(f"{log.job_name}: {log.status}; {log.message}"))
