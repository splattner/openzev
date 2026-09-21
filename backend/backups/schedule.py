"""The built-in backup schedule: one ``django_celery_beat`` periodic task, edited as data.

An administrator changes *when* backups run without a deploy, so the schedule
lives in the database as beat's own ``PeriodicTask`` and ``CrontabSchedule``
rather than in ``settings.CELERY_BEAT_SCHEDULE``. Beat's database scheduler
notices a change when the row is saved, so saves go through ``save()``, never a
queryset ``update()``.

Only what an administrator can sensibly ask for is exposed: daily or weekly, at
a time of day. The task is created the first time a schedule is saved (there is
nothing for beat to run while it is off, and nothing to create on a fresh
installation), and until then the schedule reads as off.
"""

from __future__ import annotations

from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

TASK_NAME = "openzev-scheduled-backup"
TASK_PATH = "backups.tasks.scheduled_backup"

DAILY = "daily"
WEEKLY = "weekly"
FREQUENCIES = (DAILY, WEEKLY)

DEFAULT = {"enabled": False, "frequency": DAILY, "hour": 2, "minute": 0, "day_of_week": 0}


def interval_hours(frequency: str) -> int:
    return 168 if frequency == WEEKLY else 24


def get_schedule() -> dict:
    """The schedule as the API shows it; the defaults, switched off, when none has been saved."""
    task = PeriodicTask.objects.select_related("crontab").filter(name=TASK_NAME).first()
    if task is None or task.crontab is None:
        result = dict(DEFAULT)
        result["last_run_at"] = None
    else:
        cron = task.crontab
        weekly = cron.day_of_week != "*"
        result = {
            "enabled": task.enabled,
            "frequency": WEEKLY if weekly else DAILY,
            "hour": int(cron.hour),
            "minute": int(cron.minute),
            "day_of_week": int(cron.day_of_week) if weekly else DEFAULT["day_of_week"],
            "last_run_at": task.last_run_at,
        }
    result["timezone"] = settings.TIME_ZONE
    result["interval_hours"] = interval_hours(result["frequency"])
    return result


def set_schedule(*, enabled: bool, frequency: str, hour: int, minute: int, day_of_week: int) -> dict:
    """Save the schedule and return it as :func:`get_schedule` would."""
    cron_fields = {
        "minute": str(minute),
        "hour": str(hour),
        "day_of_week": str(day_of_week) if frequency == WEEKLY else "*",
        "day_of_month": "*",
        "month_of_year": "*",
        "timezone": settings.TIME_ZONE,
    }
    crontab = CrontabSchedule.objects.filter(**cron_fields).first() or CrontabSchedule.objects.create(**cron_fields)
    task, _ = PeriodicTask.objects.get_or_create(
        name=TASK_NAME, defaults={"task": TASK_PATH, "crontab": crontab, "enabled": enabled},
    )
    task.task, task.crontab, task.enabled = TASK_PATH, crontab, enabled
    task.save()
    return get_schedule()
