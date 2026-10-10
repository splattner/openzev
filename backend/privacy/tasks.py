from celery import shared_task

from . import sweep as privacy_sweep


@shared_task
def sweep_personal_data() -> dict:
    """Daily: blank old audit IPs and email recipients, delete spent one-time tokens."""
    return privacy_sweep.sweep()
