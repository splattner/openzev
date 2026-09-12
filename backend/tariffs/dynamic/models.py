"""Storage for dynamic tariff price series.

Two models. :class:`DynamicTariffSource` is the configuration of one operator
series; :class:`DynamicPricePoint` is the series itself, one row per priced
interval.

Sources are **global, not ZEV-scoped**. A product's grid price at 14:15 on a
given day is one fact, not one fact per community, so two ZEVs on the same
product share one source and one fetch. That also means a current-day-only
series is captured once for everyone before unavailable history is lost.

The points are billing evidence, not a cache: an invoice issued last March must
stay re-derivable, and neither operator can supply those prices any more. See
docs/adr/0018-dynamic-tariff-price-series.md.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from .adapters import DynamicApiVersion, DynamicRequestMode
from .vse_v1 import TARIFF_TYPES as V1_TARIFF_TYPES
from .vse_v2 import TARIFF_TYPES as V2_TARIFF_TYPES


class DynamicTariffType(models.TextChoices):
    """The tariff types the VSE standard defines, as served by an endpoint.

    ``integrated`` is a *combination* whose contents depend on the endpoint's
    API version (v1: electricity + grid; v2: electricity + dso — see
    ``tariffs.dynamic.components``), so billing it beside separate grid-fee
    or levy tariffs charges the same money twice. Which one a community
    should use depends on what it actually buys from the operator.
    """

    ELECTRICITY = "electricity", "Electricity supply"
    GRID = "grid", "Grid usage"
    METERING = "metering", "Metering"
    NATIONAL_FEES = "national_fees", "National fees"
    INTEGRATED = "integrated", "Integrated supply and network"
    DSO = "dso", "DSO total"
    DSO_COMPLETE = "dso_complete", "Complete DSO total"
    INTEGRATED_COMPLETE = "integrated_complete", "Complete integrated total"
    REGIONAL_FEES = "regional_fees", "Regional fees"
    FEED_IN = "feed_in", "Feed-in remuneration"
    REFUND = "refund", "Storage refund"


# The model's choices and the parser's vocabulary have to stay the same set:
# a type the model can store but the parser cannot read would be a source that
# never fetches anything.
_MODEL_TARIFF_TYPES = {choice.value for choice in DynamicTariffType}
_PARSER_TARIFF_TYPES = set(V1_TARIFF_TYPES) | set(V2_TARIFF_TYPES)
if _MODEL_TARIFF_TYPES != _PARSER_TARIFF_TYPES:
    raise RuntimeError(
        "DynamicTariffType choices do not match the dynamic tariff parsers: "
        f"model-only={sorted(_MODEL_TARIFF_TYPES - _PARSER_TARIFF_TYPES)} "
        f"parser-only={sorted(_PARSER_TARIFF_TYPES - _MODEL_TARIFF_TYPES)}"
    )


class FetchStatus(models.TextChoices):
    PENDING = "pending", "Not fetched yet"
    OK = "ok", "Fetched"
    FAILED = "failed", "Failed"


class DynamicTariffSource(models.Model):
    """One operator price series, identified by endpoint, component and product."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=200, help_text="Shown when picking a source, e.g. 'Dynamic grid price'")
    url = models.URLField(max_length=500)
    api_version = models.CharField(
        max_length=20, choices=DynamicApiVersion.choices, default=DynamicApiVersion.V1_0_5
    )
    request_mode = models.CharField(
        max_length=20, choices=DynamicRequestMode.choices, default=DynamicRequestMode.STANDARD
    )
    query_tariff_type = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Tariff-type query value discovered for this endpoint.",
    )
    supports_range = models.BooleanField(default=True)
    empty_on_not_found = models.BooleanField(
        default=False,
        help_text="Treat HTTP 404 as a successful empty publication for this endpoint.",
    )
    tariff_type = models.CharField(max_length=20, choices=DynamicTariffType.choices)
    # The operator's own product name. Blank means "whatever the endpoint
    # defaults to", which is only safe for an endpoint that serves one product:
    # Two products can quote different values at the same instant, so a silent
    # default on a multi-product endpoint would bill the wrong tariff.
    tariff_name = models.CharField(max_length=120, blank=True, default="")
    enabled = models.BooleanField(
        default=True,
        help_text="Disabled sources remain as billing evidence but are skipped by scheduled refreshes.",
    )

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
    # Earliest window still needing retry; separate from covers_to so later
    # success does not erase an earlier failure.
    recovery_from = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["url", "api_version", "tariff_type", "tariff_name"],
                name="unique_dynamic_tariff_source",
            ),
            models.CheckConstraint(
                condition=~models.Q(request_mode=DynamicRequestMode.EXACT_URL, supports_range=True),
                name="dynamic_exact_url_no_range",
            ),
        ]

    def clean(self):
        errors = {}
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            for field in ("url", "api_version", "tariff_type", "tariff_name"):
                if getattr(self, field) != getattr(original, field):
                    errors[field] = "Source identity is immutable; create a replacement source."
        if self.request_mode == DynamicRequestMode.EXACT_URL and self.supports_range:
            errors["supports_range"] = "An exact-URL source cannot support range queries."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return self.label or f"{self.url} ({self.get_tariff_type_display()})"

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def supports_backfill(self) -> bool:
        """Whether discovery found support for historical range queries."""
        return self.supports_range


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
    # negative in a recorded production response.
    price_chf_per_kwh = models.DecimalField(max_digits=8, decimal_places=5)

    class Meta:
        ordering = ["source", "valid_from", "id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "valid_from"], name="unique_dynamic_price_point"),
            models.CheckConstraint(condition=models.Q(valid_to__gt=models.F("valid_from")), name="dynamic_price_point_valid_range"),
        ]

    def __str__(self) -> str:
        return f"{self.valid_from.isoformat()} {self.price_chf_per_kwh}"
