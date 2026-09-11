"""Storage for dynamic tariff price series.

Two models. :class:`DynamicTariffSource` is the configuration of one operator
series; :class:`DynamicPricePoint` is the series itself, one row per priced
interval.

Sources are **global, not ZEV-scoped**. The price of Groupe E's ``vario`` grid
product at 14:15 on a given day is one fact, not one fact per community, so two
ZEVs on the same product share one source and one fetch. That also means the
series is captured once for everyone — which matters because BKW keeps no
history at all, so an interval nobody fetched on the day is gone for good.

The points are billing evidence, not a cache: an invoice issued last March must
stay re-derivable, and neither operator can supply those prices any more. See
docs/adr/0018-dynamic-tariff-price-series.md.
"""

from __future__ import annotations

import uuid

from django.db import models

from .adapters import DynamicAdapter
from .vse_v1 import TARIFF_TYPES


class DynamicTariffType(models.TextChoices):
    """The tariff types the VSE standard defines, as served by an endpoint.

    ``integrated`` is a *combination* of ``electricity`` and ``grid``, so
    billing it beside separate grid-fee or levy tariffs charges the same money
    twice. Which one a community should use depends on what it actually buys
    from the operator.
    """

    ELECTRICITY = "electricity", "Electricity supply"
    GRID = "grid", "Grid usage"
    INTEGRATED = "integrated", "Integrated (electricity + grid)"
    REGIONAL_FEES = "regional_fees", "Regional fees"
    FEED_IN = "feed_in", "Feed-in remuneration"


# The model's choices and the parser's vocabulary have to stay the same set:
# a type the model can store but the parser cannot read would be a source that
# never fetches anything.
assert {choice.value for choice in DynamicTariffType} == set(TARIFF_TYPES)


class FetchStatus(models.TextChoices):
    PENDING = "pending", "Not fetched yet"
    OK = "ok", "Fetched"
    FAILED = "failed", "Failed"


class DynamicTariffSource(models.Model):
    """One operator price series, identified by endpoint, component and product."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=200, help_text="Shown when picking a source, e.g. 'Groupe E vario — grid'")
    url = models.URLField(max_length=500)
    adapter = models.CharField(max_length=20, choices=DynamicAdapter.choices, default=DynamicAdapter.VSE_V1)
    tariff_type = models.CharField(max_length=20, choices=DynamicTariffType.choices)
    # The operator's own product name. Blank means "whatever the endpoint
    # defaults to", which is only safe for an endpoint that serves one product:
    # Groupe E quoted 0.1398 for `vario` and 0.1267 for `double` at the same
    # instant, so a silent default there would bill the wrong tariff.
    tariff_name = models.CharField(max_length=120, blank=True, default="")

    last_fetch_status = models.CharField(max_length=10, choices=FetchStatus.choices, default=FetchStatus.PENDING)
    last_fetch_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    # User-safe text only, never a raw exception — this reaches the operator's
    # screen. ``importers.remote.TariffFetchError`` already splits the safe
    # message from the server-only detail.
    last_fetch_error = models.CharField(max_length=500, blank=True, default="")

    # Denormalised extent of the stored series, so a picker and the readiness
    # check can say what is covered without aggregating 35 000 rows per year.
    covers_from = models.DateTimeField(null=True, blank=True)
    covers_to = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["url", "tariff_type", "tariff_name"],
                name="unique_dynamic_tariff_source",
            )
        ]

    def __str__(self) -> str:
        return self.label or f"{self.url} ({self.get_tariff_type_display()})"

    @property
    def supports_backfill(self) -> bool:
        """Whether history can still be recovered for this source.

        False for BKW, whose endpoint takes no time range: for that one, only
        what was fetched on the day exists, ever.
        """
        from .adapters import adapter_for

        return adapter_for(self.adapter).supports_range


class DynamicPricePoint(models.Model):
    """The price of one interval.

    ``valid_to`` is stored rather than derived from a resolution setting. It is
    what lets an hourly and a quarter-hourly source share one lookup, and what
    makes a hole in the series detectable as a hole rather than inferred from a
    count — the count is not constant anyway, since a DST day has 92 or 100
    quarter-hours rather than 96.
    """

    id = models.BigAutoField(primary_key=True)
    source = models.ForeignKey(DynamicTariffSource, on_delete=models.CASCADE, related_name="points")
    valid_from = models.DateTimeField(help_text="Start of the priced interval (UTC)")
    valid_to = models.DateTimeField(help_text="End of the priced interval, exclusive (UTC)")
    # Signed on purpose: a dynamic grid tariff goes negative when the grid is
    # long on solar, which is the whole mechanism. 22 of 96 intervals were
    # negative on the Groupe E day recorded in testdata.
    price_chf_per_kwh = models.DecimalField(max_digits=8, decimal_places=5)

    class Meta:
        ordering = ["source", "valid_from", "id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "valid_from"], name="unique_dynamic_price_point"),
        ]
        indexes = [models.Index(fields=["source", "valid_from"], name="dyn_price_source_from_idx")]

    def __str__(self) -> str:
        return f"{self.valid_from.isoformat()} {self.price_chf_per_kwh}"
