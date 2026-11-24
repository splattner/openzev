"""Representative tariff prices for API responses and PDFs."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from .dynamic.pricing import DynamicPriceSummary, summarize_dynamic_tariff, summarize_requests
from .models import BillingMode, EnergyType, PeriodType, Tariff
from .pricing import is_active


@dataclass(frozen=True)
class GridBaseSummary:
    price_chf_per_kwh: Decimal | None
    dynamic_status: str | None
    reference_date: date

    @property
    def has_effective_price(self) -> bool:
        """Documents print positive static totals and any available dynamic total."""
        return self.price_chf_per_kwh is not None and (
            self.price_chf_per_kwh > 0 or self.dynamic_status is not None
        )

    def as_dict(self) -> dict:
        return {
            "price_chf_per_kwh": str(self.price_chf_per_kwh) if self.price_chf_per_kwh is not None else None,
            "dynamic_status": self.dynamic_status,
            "reference_date": self.reference_date.isoformat(),
        }


def display_grid_base_summary(
    grid_tariffs, *, as_of: date,
    dynamic_summaries: dict[tuple[UUID, date], DynamicPriceSummary] | None = None,
) -> GridBaseSummary:
    """Sum representative prices for grid tariffs prefiltered to as_of.

    A missing dynamic price makes the whole base unavailable.
    """
    total = Decimal("0")
    dynamic_status = None
    for tariff in grid_tariffs:
        if tariff.dynamic_source_id:
            summary = (
                dynamic_summaries[tariff.pk, as_of] if dynamic_summaries is not None
                else summarize_dynamic_tariff(tariff, as_of=as_of)
            )
            if summary.average_chf_per_kwh is None:
                return GridBaseSummary(None, "unavailable", as_of)
            total += summary.average_chf_per_kwh
            if summary.status == "partial":
                dynamic_status = "partial"
            elif dynamic_status is None:
                dynamic_status = "complete"
            continue
        periods = list(tariff.periods.all())
        for kind in (PeriodType.FLAT, PeriodType.HIGH, PeriodType.LOW):
            representative = next((period for period in periods if period.period_type == kind), None)
            if representative is not None:
                break
        else:
            representative = periods[0] if periods else None
        if representative:
            total += representative.price_chf_per_kwh
    return GridBaseSummary(total, dynamic_status, as_of)


@dataclass(frozen=True)
class TariffDisplaySummaries:
    dynamic_prices: dict[UUID, DynamicPriceSummary]
    percentage_bases: dict[UUID, GridBaseSummary]


def build_tariff_display_summaries(tariffs: Sequence[Tariff], *, as_of: date) -> TariffDisplaySummaries:
    """Build display summaries keyed by tariff ID.

    Expects prefetched periods and all grid versions for ZEVs with percentage
    tariffs. Reads price points at most once per source across all reference dates.
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
        grids = [
            grid for grid in grids_by_zev.get(tariff.zev_id, [])
            if is_active(grid, reference)
        ]
        bases[tariff.pk] = (reference, grids)
        for grid in grids:
            if grid.dynamic_source_id:
                requests[grid.pk, reference] = (grid, reference)

    summaries = summarize_requests(requests)
    return TariffDisplaySummaries(
        dynamic_prices={
            tariff.pk: summaries[tariff.pk, as_of] for tariff in tariffs if tariff.dynamic_source_id
        },
        percentage_bases={
            pk: display_grid_base_summary(grids, as_of=reference, dynamic_summaries=summaries)
            for pk, (reference, grids) in bases.items()
        },
    )
