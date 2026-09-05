from django.core.management.base import BaseCommand

from erp.scheduled_jobs import run_scheduled_erp_maintenance


class Command(BaseCommand):
    help = "Run the safe daily AuraFoods ERP maintenance tasks and log the summary."

    def handle(self, *args, **options):
        log = run_scheduled_erp_maintenance()
        self.stdout.write(self.style.SUCCESS(f"{log.job_name}: {log.status}; {log.message}"))
