from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import os
import socket
from uuid import uuid4

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .domain_services import expire_supplier_price_agreements
from .models import (
    Company, DocumentState, ScheduledTaskConfig, ScheduledTaskLock, ScheduledTaskLog,
    StockBatch, SupplierInvoice,
)


@contextmanager
def scheduled_job_lock(job_name: str, *, ttl=timezone.timedelta(minutes=30)):
    """Acquire a database-backed lease suitable for multiple web/worker containers."""
    now = timezone.now()
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"
    acquired = False
    with transaction.atomic():
        lock, created = ScheduledTaskLock.objects.get_or_create(
            job_name=job_name,
            defaults={
                "lock_key": f"erp-scheduled:{job_name}", "locked_by": owner,
                "locked_at": now, "expires_at": now + ttl,
            },
        )
        lock = ScheduledTaskLock.objects.select_for_update().get(pk=lock.pk)
        if not created and lock.status == ScheduledTaskLock.Status.ACQUIRED and lock.expires_at > now:
            acquired = False
        elif not created:
            lock.status = ScheduledTaskLock.Status.EXPIRED if lock.expires_at <= now else ScheduledTaskLock.Status.STALE
            lock.locked_by = owner
            lock.locked_at = now
            lock.expires_at = now + ttl
            lock.released_at = None
            lock.status = ScheduledTaskLock.Status.ACQUIRED
            lock.save()
            acquired = True
        else:
            acquired = True
    if not acquired:
        yield False
        return
    try:
        yield True
    except Exception:
        if acquired:
            ScheduledTaskLock.objects.filter(job_name=job_name, locked_by=owner).update(
                status=ScheduledTaskLock.Status.FAILED, released_at=timezone.now(), updated_at=timezone.now()
            )
        raise
    else:
        if acquired:
            ScheduledTaskLock.objects.filter(job_name=job_name, locked_by=owner).update(
                status=ScheduledTaskLock.Status.RELEASED, released_at=timezone.now(), updated_at=timezone.now()
            )


def _disabled_job_log(*, job_name: str, job_type: str, triggered_by: str) -> ScheduledTaskLog | None:
    config = ScheduledTaskConfig.objects.filter(job_name=job_name).first()
    if not config or config.enabled:
        return None
    now = timezone.now()
    log = ScheduledTaskLog.objects.create(
        job_name=job_name,
        job_type=job_type,
        started_at=now,
        finished_at=now,
        status=ScheduledTaskLog.Status.SKIPPED,
        duration=timezone.timedelta(0),
        message="Skipped because the scheduled task configuration is disabled.",
        triggered_by=triggered_by,
    )
    ScheduledTaskConfig.objects.filter(pk=config.pk).update(last_run=now, updated_at=now)
    return log


def _run_logged(*, job_name: str, job_type: str, triggered_by: str, operation: Callable[[], dict]) -> ScheduledTaskLog:
    with scheduled_job_lock(job_name) as acquired:
        if not acquired:
            now = timezone.now()
            return ScheduledTaskLog.objects.create(
                job_name=job_name, job_type=job_type, triggered_by=triggered_by,
                started_at=now, finished_at=now, duration=timezone.timedelta(0),
                status=ScheduledTaskLog.Status.SKIPPED,
                message="Skipped because another container holds the active job lease.",
            )
        log = ScheduledTaskLog.objects.create(
            job_name=job_name, job_type=job_type, triggered_by=triggered_by,
            status=ScheduledTaskLog.Status.STARTED,
        )
        try:
            result = operation()
            log.status = ScheduledTaskLog.Status.SUCCESS
            log.message = ", ".join(f"{key}={value}" for key, value in result.items())
        except Exception as exc:
            log.status = ScheduledTaskLog.Status.FAILED
            log.message = "Scheduled task failed. Inspect error details."
            log.error_details = f"{exc.__class__.__name__}: {str(exc)}"[:2000]
            raise
        finally:
            log.finished_at = timezone.now()
            log.duration = log.finished_at - log.started_at
            log.save(update_fields=["status", "message", "error_details", "finished_at", "duration"])
            ScheduledTaskConfig.objects.filter(job_name=job_name).update(last_run=log.finished_at, updated_at=timezone.now())
        return log


def refresh_expiry_statuses(*, triggered_by=ScheduledTaskLog.TriggeredBy.MANAGEMENT_COMMAND) -> ScheduledTaskLog:
    skipped = _disabled_job_log(
        job_name="refresh_expiry_statuses",
        job_type=ScheduledTaskLog.JobType.EXPIRY_REFRESH,
        triggered_by=triggered_by,
    )
    if skipped:
        return skipped

    def operation():
        today = timezone.localdate()
        company = Company.objects.filter(is_active=True).first()
        threshold_days = company.near_expiry_threshold_days if company else 30
        threshold = today + timezone.timedelta(days=threshold_days)

        no_expiry = StockBatch.objects.filter(expiry_date__isnull=True).exclude(
            expiry_status=StockBatch.ExpiryStatus.NOT_APPLICABLE
        ).update(expiry_status=StockBatch.ExpiryStatus.NOT_APPLICABLE, updated_at=timezone.now())
        current = StockBatch.objects.filter(expiry_date__gt=threshold).exclude(
            expiry_status=StockBatch.ExpiryStatus.CURRENT
        ).update(expiry_status=StockBatch.ExpiryStatus.CURRENT, updated_at=timezone.now())
        near_expiry = StockBatch.objects.filter(expiry_date__gte=today, expiry_date__lte=threshold).exclude(
            expiry_status=StockBatch.ExpiryStatus.NEAR_EXPIRY
        ).update(expiry_status=StockBatch.ExpiryStatus.NEAR_EXPIRY, updated_at=timezone.now())
        expired = StockBatch.objects.filter(expiry_date__lt=today).exclude(
            expiry_status=StockBatch.ExpiryStatus.EXPIRED,
            stock_state=StockBatch.StockState.EXPIRED,
            is_blocked=True,
        ).update(
            expiry_status=StockBatch.ExpiryStatus.EXPIRED,
            stock_state=StockBatch.StockState.EXPIRED,
            is_blocked=True,
            block_reason="Expired stock - scheduled classification",
            updated_at=timezone.now(),
        )
        agreements_expired = expire_supplier_price_agreements(as_of=today)
        return {
            "not_applicable_updated": no_expiry,
            "current_updated": current,
            "near_expiry_updated": near_expiry,
            "expired_blocked": expired,
            "rate_agreements_expired": agreements_expired,
        }

    return _run_logged(
        job_name="refresh_expiry_statuses",
        job_type=ScheduledTaskLog.JobType.EXPIRY_REFRESH,
        triggered_by=triggered_by,
        operation=operation,
    )


def refresh_overdue_supplier_invoices(
    *, triggered_by=ScheduledTaskLog.TriggeredBy.MANAGEMENT_COMMAND
) -> ScheduledTaskLog:
    skipped = _disabled_job_log(
        job_name="refresh_overdue_supplier_invoices",
        job_type=ScheduledTaskLog.JobType.OVERDUE_REFRESH,
        triggered_by=triggered_by,
    )
    if skipped:
        return skipped

    def operation():
        today = timezone.localdate()
        eligible = SupplierInvoice.objects.annotate(
            calculated_outstanding=F("amount") - F("paid_amount") - F("advance_adjusted_amount")
            - F("debit_note_amount") - F("credit_note_amount")
        ).filter(
            due_date__lt=today,
            calculated_outstanding__gt=0,
            status__in=[DocumentState.POSTED, DocumentState.PARTIALLY_PAID, DocumentState.OVERDUE],
        )
        updated = eligible.exclude(status=DocumentState.OVERDUE).update(
            status=DocumentState.OVERDUE, updated_at=timezone.now()
        )
        return {"overdue_updated": updated, "overdue_open_total": eligible.count()}

    return _run_logged(
        job_name="refresh_overdue_supplier_invoices",
        job_type=ScheduledTaskLog.JobType.OVERDUE_REFRESH,
        triggered_by=triggered_by,
        operation=operation,
    )


def run_scheduled_erp_maintenance(
    *, triggered_by=ScheduledTaskLog.TriggeredBy.MANAGEMENT_COMMAND
) -> ScheduledTaskLog:
    skipped = _disabled_job_log(
        job_name="run_scheduled_erp_maintenance",
        job_type=ScheduledTaskLog.JobType.OTHER,
        triggered_by=triggered_by,
    )
    if skipped:
        return skipped

    def operation():
        expiry_log = refresh_expiry_statuses(triggered_by=triggered_by)
        overdue_log = refresh_overdue_supplier_invoices(triggered_by=triggered_by)
        return {
            "expiry_status": expiry_log.status,
            "overdue_status": overdue_log.status,
            "child_job_logs": 2,
        }

    return _run_logged(
        job_name="run_scheduled_erp_maintenance",
        job_type=ScheduledTaskLog.JobType.OTHER,
        triggered_by=triggered_by,
        operation=operation,
    )
