"""Tariff band rows and footnotes for printed documents."""

from decimal import Decimal

from tariffs.display_pricing import GridBaseSummary

from .band_labels import band_description, band_recurrence


def percentage_band_rows(tariff, grid_base: GridBaseSummary, band_tr: dict) -> list[dict]:
    """Return percentage rows in tariff band order.

    Each band's effective_chf is None when the grid base has no effective price.
    """
    rows = []
    for period in tariff.periods.all():
        pct = Decimal(str(period.percentage or 0))
        effective_chf = (
            grid_base.price_chf_per_kwh * pct / Decimal("100")
            if grid_base.has_effective_price
            else None
        )
        rows.append({
            "period": period,
            "label": band_description(period, band_tr),
            "recurrence": band_recurrence(period, band_tr),
            "pct": pct,
            "effective_chf": effective_chf,
        })
    return rows


def grid_base_is_multiband(grid_tariffs) -> bool:
    """Static multi-band bases need an approximation footnote.

    Dynamic tariffs carry their own status. Use prefetched periods in memory.
    """
    return any(
        not tariff.dynamic_source_id and len(list(tariff.periods.all())) > 1
        for tariff in grid_tariffs
    )
