"""Annual ZEV report: a year's energy balance, its monthly trend, and what
participation saved each participant.

Owner/admin view of one ZEV and one calendar year (docs/specs/
2026-09-annual-zev-report.md). Nothing here is computed afresh: the energy
figures are the Energy balance dashboard's (``metering.analytics``) over the
civil year in monthly buckets, and the savings are the annual statement's
(``compute_savings``) summed per participant, so the report reconciles with
both.
"""

from datetime import date
from decimal import Decimal
from functools import partial

from django.db.models.functions import TruncMonth

from allocation.validity import business_tz, period_end_exclusive_dt, period_start_dt
from metering.analytics import owner_dashboard_summary, zev_balance_timeline
from metering.models import MeterReading

from .annual_statement import compute_savings
from .models import Invoice, InvoiceStatus


def _year_readings(zev, year: int):
    """The ZEV's readings in civil ``year`` (ADR 0026)."""
    return MeterReading.objects.filter(
        metering_point__zev=zev,
        timestamp__gte=period_start_dt(date(year, 1, 1)),
        timestamp__lt=period_end_exclusive_dt(date(year, 12, 31)),
    )


def _rate(numerator: float, denominator: float) -> float | None:
    """``numerator / denominator`` as a percentage to one decimal, or None when undefined."""
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _balance(entry: dict) -> dict:
    """kWh figures plus the two rates the report is about.

    Self-consumption rate: share of production used inside the ZEV.
    Self-sufficiency rate: share of consumption covered by the ZEV.
    Both use the dashboard's definitions, so the numbers agree.
    """
    self_consumed = max(entry["produced_kwh"] - entry["exported_kwh"], 0.0)
    return {
        "produced_kwh": entry["produced_kwh"],
        "consumed_kwh": entry["consumed_kwh"],
        "imported_kwh": entry["imported_kwh"],
        "exported_kwh": entry["exported_kwh"],
        "self_consumed_kwh": self_consumed,
        "self_consumption_rate": _rate(self_consumed, entry["produced_kwh"]),
        "self_sufficiency_rate": _rate(self_consumed, entry["consumed_kwh"]),
    }


def _by_month(timeline: list[dict]) -> dict[int, dict]:
    """Timeline entries keyed by calendar month.

    Buckets are ISO datetimes truncated in the business timezone, so the
    month is the civil month the readings belong to.
    """
    return {int(entry["bucket"][5:7]): entry for entry in timeline}


def _empty_month() -> dict:
    return {"produced_kwh": 0.0, "consumed_kwh": 0.0, "imported_kwh": 0.0, "exported_kwh": 0.0}


def _savings_by_participant(zev, year: int) -> dict[str, dict]:
    """``compute_savings`` per participant over the year's non-cancelled invoices.

    Same invoice selection as the annual statement, so a participant's row
    here matches the savings box on their statement.
    """
    invoices = (
        Invoice.objects.filter(
            zev=zev,
            period_start__gte=date(year, 1, 1),
            period_end__lte=date(year, 12, 31),
        )
        .exclude(status=InvoiceStatus.CANCELLED)
        .prefetch_related("items")
        .order_by("period_start")
    )
    grouped: dict[str, list] = {}
    for invoice in invoices:
        grouped.setdefault(str(invoice.participant_id), []).append(invoice)
    return {pid: compute_savings(rows) for pid, rows in grouped.items()}


def build_annual_report(zev, year: int) -> dict:
    """The annual report payload for ``zev`` and civil ``year``."""
    trunc_month = partial(TruncMonth, tzinfo=business_tz())

    readings = _year_readings(zev, year)
    has_data = readings.exists()
    summary = owner_dashboard_summary(readings, trunc_month, None)
    current = _by_month(summary["timeline"])

    previous_readings = _year_readings(zev, year - 1)
    previous_has_data = previous_readings.exists()
    previous_timeline, previous_totals = (
        zev_balance_timeline(previous_readings, trunc_month) if previous_has_data else ([], None)
    )
    previous = _by_month(previous_timeline)

    months = []
    for month in range(1, 13):
        row = {"month": month, **_balance(current.get(month, _empty_month()))}
        prior = _balance(previous[month]) if month in previous else None
        row["previous_self_consumption_rate"] = prior["self_consumption_rate"] if prior else None
        row["previous_self_sufficiency_rate"] = prior["self_sufficiency_rate"] if prior else None
        months.append(row)

    savings = _savings_by_participant(zev, year)
    names = {str(p.id): f"{p.first_name} {p.last_name}".strip() for p in zev.participants.all()}

    participants = {}
    for stat in summary["participant_stats"]:
        pid = stat["participant_id"]
        participants[pid] = {
            "participant_id": pid,
            "participant_name": stat["participant_name"] or names.get(pid, ""),
            "consumed_kwh": stat["total_consumed_kwh"],
            "produced_kwh": stat["total_produced_kwh"],
            "from_zev_kwh": stat["from_zev_kwh"],
            "from_grid_kwh": stat["from_grid_kwh"],
            "self_sufficiency_rate": _rate(stat["from_zev_kwh"], stat["total_consumed_kwh"]),
            "savings": savings.get(pid),
        }
    # Invoiced but without readings in the year (e.g. a data gap): the savings
    # are still real money, so the row stays.
    for pid, row_savings in savings.items():
        if pid not in participants and pid in names:
            participants[pid] = {
                "participant_id": pid,
                "participant_name": names[pid],
                "consumed_kwh": 0.0,
                "produced_kwh": 0.0,
                "from_zev_kwh": 0.0,
                "from_grid_kwh": 0.0,
                "self_sufficiency_rate": None,
                "savings": row_savings,
            }

    saved = [Decimal(row["savings"]["saved_chf"]) for row in participants.values() if row["savings"]]

    return {
        "zev_id": str(zev.id),
        "year": year,
        "has_data": has_data,
        "totals": _balance(summary["zev_totals"]),
        "previous_totals": _balance(previous_totals) if previous_totals else None,
        "months": months,
        "participants": sorted(participants.values(), key=lambda row: row["participant_name"].lower()),
        "savings_total_chf": f"{sum(saved, Decimal('0')):.2f}" if saved else None,
    }
