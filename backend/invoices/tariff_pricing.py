"""Representative display prices shared by contracts and tariff overviews."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from tariffs.dynamic.pricing import summarize_dynamic_tariff, summarize_requests
from tariffs.models import BillingMode, EnergyType, PeriodType


@dataclass(frozen=True)
class GridBaseSummary:
    price_chf_per_kwh: Decimal | None
    dynamic_status: str | None

    @property
    def has_effective_price(self) -> bool:
        return self.price_chf_per_kwh is not None and (
            self.price_chf_per_kwh > 0 or self.dynamic_status is not None
        )


def display_grid_base_summary(
    grid_tariffs, *, as_of: date | None = None, dynamic_summaries=None
) -> GridBaseSummary:
    """Sum representative prices; an unavailable component makes the base unavailable."""
    as_of = as_of or timezone.localdate()
    total = Decimal("0")
    dynamic_status = None
    for tariff in grid_tariffs:
        if tariff.dynamic_source_id:
            summary = (
                dynamic_summaries[tariff.pk] if dynamic_summaries is not None
                else summarize_dynamic_tariff(tariff, as_of=as_of)
            )
            if summary.average_chf_per_kwh is None:
                return GridBaseSummary(None, "unavailable")
            total += summary.average_chf_per_kwh
            if summary.status == "partial":
                dynamic_status = "partial"
            elif dynamic_status is None:
                dynamic_status = "complete"
            continue
        periods = list(tariff.periods.all())
        representative = next(
            (period for kind in (PeriodType.FLAT, PeriodType.HIGH, PeriodType.LOW)
             for period in periods if period.period_type == kind),
            periods[0] if periods else None,
        )
        if representative:
            total += Decimal(str(representative.price_chf_per_kwh))
    return GridBaseSummary(total, dynamic_status)


def prepare_tariff_display_summaries(tariffs, *, as_of: date):
    """Cache API display prices, including percentage bases at their own date.

    Call with prefetched periods and all grid versions in the requested ZEVs.
    All dynamic windows share one bounded query per source.
    """
    requests, grids_by_zev, bases = {}, {}, {}
    for tariff in tariffs:
        if tariff.dynamic_source_id:
            requests[tariff.pk, as_of] = (tariff, as_of)
        if tariff.billing_mode == BillingMode.ENERGY and tariff.energy_type == EnergyType.GRID:
            grids_by_zev.setdefault(tariff.zev_id, []).append(tariff)
    for tariff in tariffs:
        if tariff.billing_mode != BillingMode.PERCENTAGE_OF_ENERGY:
            continue
        reference = max(tariff.valid_from, min(as_of, tariff.valid_to or as_of))
        grids = [grid for grid in grids_by_zev.get(tariff.zev_id, [])
                 if grid.valid_from <= reference and (grid.valid_to is None or reference <= grid.valid_to)]
        bases[tariff.pk] = (reference, grids)
        for grid in grids:
            if grid.dynamic_source_id:
                requests[grid.pk, reference] = (grid, reference)
    summaries = summarize_requests(requests)
    for tariff in tariffs:
        if tariff.dynamic_source_id:
            tariff._prefetched_dynamic_summary = summaries[tariff.pk, as_of]
        if tariff.pk in bases:
            reference, grids = bases[tariff.pk]
            base = display_grid_base_summary(grids, as_of=reference, dynamic_summaries={
                grid.pk: summaries[grid.pk, reference] for grid in grids if grid.dynamic_source_id
            })
            tariff._prefetched_percentage_base = {
                "price_chf_per_kwh": str(base.price_chf_per_kwh) if base.price_chf_per_kwh is not None else None,
                "dynamic_status": base.dynamic_status,
                "reference_date": reference.isoformat(),
            }


def grid_base_is_multiband(grid_tariffs) -> bool:
    """Static multi-band bases need an approximation footnote.

    Dynamic tariffs carry their own status. Use prefetched periods in memory.
    """
    return any(
        not tariff.dynamic_source_id and len(list(tariff.periods.all())) > 1
        for tariff in grid_tariffs
    )
