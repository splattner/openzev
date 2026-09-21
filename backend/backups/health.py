"""Is the instance actually protected? One answer, shared by the backup tab and the health panel.

"Last backup" means the last *finished whole-instance backup an administrator
or the schedule asked for*. A community-only backup does not protect the
instance, and a safety backup (taken before a restore) is the way back from that
restore, not a routine backup; letting either make the instance look fresh would
be the failure this exists to prevent.
"""

from __future__ import annotations

from django.utils import timezone

from . import crypto
from .models import BackupDestination, BackupJob, BackupJobScope, BackupJobStatus, BackupJobTrigger
from .schedule import get_schedule


def routine_backups():
    return BackupJob.objects.filter(scope=BackupJobScope.INSTANCE).exclude(trigger=BackupJobTrigger.PRE_RESTORE)


def latest_jobs():
    """``(last finished, last failed)`` routine backup, either of which may be ``None``."""
    last_ok = (
        routine_backups().select_related("destination", "zev")
        .filter(status=BackupJobStatus.COMPLETED).order_by("-completed_at").first()
    )
    last_failed = (
        routine_backups().select_related("destination", "zev")
        .filter(status=BackupJobStatus.FAILED).order_by("-completed_at", "-created_at").first()
    )
    return last_ok, last_failed


def backup_health(now=None) -> dict:
    now = now or timezone.now()
    schedule = get_schedule()
    last_ok, last_failed = latest_jobs()
    age_hours = round((now - last_ok.completed_at).total_seconds() / 3600, 1) if last_ok else None

    # Stale is relative to the schedule the administrator chose: twice its
    # interval, so one missed run is a warning to watch, two are a problem.
    stale = schedule["enabled"] and (age_hours is None or age_hours > 2 * schedule["interval_hours"])

    failed_since = bool(
        last_failed and last_ok and (last_failed.completed_at or last_failed.created_at) > last_ok.completed_at
    )
    destinations = BackupDestination.objects.filter(enabled=True).count()
    if destinations == 0:
        status = "unknown"
    elif stale or last_ok is None or failed_since:
        status = "degraded"
    else:
        status = "ok"

    try:
        encrypted = crypto.encryption_configured()
    except crypto.BackupCryptoError:
        encrypted = False

    return {
        "status": status,
        "destinations_enabled": destinations,
        "schedule_enabled": schedule["enabled"],
        "schedule_interval_hours": schedule["interval_hours"] if schedule["enabled"] else None,
        "last_successful_at": last_ok.completed_at if last_ok else None,
        "age_hours": age_hours,
        "stale": bool(stale),
        "last_failed_after_success": failed_since,
        "encrypted": encrypted,
    }
