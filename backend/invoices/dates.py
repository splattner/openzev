"""Shared date formatting for printable documents (invoices, contracts, ...).

``format_date_value`` was originally private to ``invoices.pdf``; invoices,
contracts, annual statements, financial summaries and the email tasks all need
dates rendered in exactly the same way, so the implementation now lives here.
``invoices.pdf`` imports it under the historical ``_format_date_value`` name to
keep its public callers (``annual_statement``, ``tasks``, ``financial_summary``)
working unchanged.
"""

from datetime import date, datetime

from django.utils import timezone

from accounts.models import AppSettings


def format_date_value(value: date | datetime | None, pattern: str) -> str:
    """Format a date (or datetime) according to an ``AppSettings`` pattern."""
    if value is None:
        return ""

    if isinstance(value, datetime):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()

    day = f"{value.day:02d}"
    month = f"{value.month:02d}"
    year = str(value.year)

    if pattern == AppSettings.SHORT_DATE_DD_MM_YYYY:
        return f"{day}.{month}.{year}"
    if pattern == AppSettings.SHORT_DATE_DD_SLASH_MM_SLASH_YYYY:
        return f"{day}/{month}/{year}"
    if pattern == AppSettings.SHORT_DATE_MM_SLASH_DD_SLASH_YYYY:
        return f"{month}/{day}/{year}"
    if pattern == AppSettings.SHORT_DATE_YYYY_MM_DD:
        return f"{year}-{month}-{day}"
    return value.isoformat()
