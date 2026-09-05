from django.test import TestCase
from django.utils import timezone

from unittest.mock import patch

from erp.models import ScheduledTaskLock, ScheduledTaskLog
from erp.scheduled_jobs import _run_logged, run_scheduled_erp_maintenance, scheduled_job_lock


class ScheduledJobLockTests(TestCase):
    def test_concurrent_attempt_skips_and_success_releases(self):
        with scheduled_job_lock("test_job") as first:
            self.assertTrue(first)
            with scheduled_job_lock("test_job") as second:
                self.assertFalse(second)
        self.assertEqual(ScheduledTaskLock.objects.get(job_name="test_job").status, ScheduledTaskLock.Status.RELEASED)

    def test_expired_lock_is_recovered(self):
        ScheduledTaskLock.objects.create(
            job_name="expired", lock_key="erp-scheduled:expired", locked_by="dead-worker",
            locked_at=timezone.now() - timezone.timedelta(hours=2),
            expires_at=timezone.now() - timezone.timedelta(hours=1),
        )
        with scheduled_job_lock("expired") as acquired:
            self.assertTrue(acquired)

    def test_exception_marks_lock_failed(self):
        with self.assertRaises(RuntimeError):
            with scheduled_job_lock("failing"):
                raise RuntimeError("expected")
        self.assertEqual(ScheduledTaskLock.objects.get(job_name="failing").status, ScheduledTaskLock.Status.FAILED)

    def test_logged_duplicate_is_skipped_without_running_operation(self):
        operation_called = False

        def operation():
            nonlocal operation_called
            operation_called = True
            return {"changed": 1}

        with scheduled_job_lock("logged_duplicate"):
            log = _run_logged(
                job_name="logged_duplicate",
                job_type=ScheduledTaskLog.JobType.OTHER,
                triggered_by=ScheduledTaskLog.TriggeredBy.MANAGEMENT_COMMAND,
                operation=operation,
            )
        self.assertFalse(operation_called)
        self.assertEqual(log.status, ScheduledTaskLog.Status.SKIPPED)

    def test_logged_failure_records_sanitized_error_and_releases_failed_lease(self):
        with self.assertRaisesRegex(ValueError, "expected failure"):
            _run_logged(
                job_name="logged_failure",
                job_type=ScheduledTaskLog.JobType.OTHER,
                triggered_by=ScheduledTaskLog.TriggeredBy.MANAGEMENT_COMMAND,
                operation=lambda: (_ for _ in ()).throw(ValueError("expected failure")),
            )
        log = ScheduledTaskLog.objects.get(job_name="logged_failure")
        self.assertEqual(log.status, ScheduledTaskLog.Status.FAILED)
        self.assertIn("ValueError", log.error_details)
        self.assertEqual(ScheduledTaskLock.objects.get(job_name="logged_failure").status, ScheduledTaskLock.Status.FAILED)

    @patch("erp.scheduled_jobs.refresh_overdue_supplier_invoices")
    @patch("erp.scheduled_jobs.refresh_expiry_statuses")
    def test_parent_maintenance_duplicate_does_not_start_child_jobs(self, expiry, overdue):
        with scheduled_job_lock("run_scheduled_erp_maintenance"):
            log = run_scheduled_erp_maintenance()
        self.assertEqual(log.status, ScheduledTaskLog.Status.SKIPPED)
        expiry.assert_not_called()
        overdue.assert_not_called()
