"""Tariffs with more than two priced time bands.

`PeriodType` names the two bands a Swiss tariff traditionally has — HT and NT —
and every consumer that looks a band up by name is written around that pair. A
peak/shoulder/off-peak tariff has no such names, so its bands are stored as
plain `band` rows told apart by their windows.

The engine needed no new matching logic for this: it matches a band by its
window, never by its name. What did need deciding is the two places where
`period_type` *is* load-bearing — the flat short-circuit and the fallback for
an hour no band covers.

See docs/specs/2026-03-tariffs-and-billing-engine.md §3.2 and issue #528.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.engine import _get_tariff_price
from tariffs.models import (
    BillingMode,
    EnergyType,
    PeriodType,
    Tariff,
    TariffCategory,
    TariffPeriod,
)
from testing.helpers import authenticate, make_user
from zev.models import Zev

WINTER = "1,2,3,10,11,12"
SUMMER = "4,5,6,7,8,9"


class BandFixture(TestCase):
    def setUp(self):
        self.owner = make_user(f"band_owner_{self._testMethodName[:30]}", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="Band ZEV", owner=self.owner, zev_type="zev")
        self.tariff = Tariff.objects.create(
            zev=self.zev, name="Grid", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )

    def band(self, price, start, end, **extra):
        return TariffPeriod.objects.create(
            tariff=self.tariff, period_type=PeriodType.BAND,
            price_chf_per_kwh=Decimal(price), time_from=start, time_to=end, **extra,
        )


class MultiBandPricingTests(BandFixture):
    """Three bands is the shape that could not be stored at all before."""

    def setUp(self):
        super().setUp()
        self.band("0.09", "00:00", "07:00")   # off-peak
        self.band("0.24", "07:00", "17:00")   # peak
        self.band("0.15", "17:00", "23:59")   # shoulder

    def _price_at(self, hour, minute=0):
        return _get_tariff_price(self.tariff, datetime(2026, 3, 15, hour, minute))

    def test_each_band_prices_its_own_window(self):
        self.assertEqual(self._price_at(3), Decimal("0.09000"))
        self.assertEqual(self._price_at(12), Decimal("0.24000"))
        self.assertEqual(self._price_at(20), Decimal("0.15000"))

    def test_the_boundaries_fall_where_the_windows_say(self):
        self.assertEqual(self._price_at(6, 59), Decimal("0.09000"))
        self.assertEqual(self._price_at(7, 0), Decimal("0.24000"))
        self.assertEqual(self._price_at(16, 59), Decimal("0.24000"))
        self.assertEqual(self._price_at(17, 0), Decimal("0.15000"))

    def test_bands_are_stored_and_read_back_in_start_time_order(self):
        """The engine's fallback reads periods[0], so this order is not merely
        cosmetic — it has to be the same band on every database."""
        self.assertEqual(
            [str(period.time_from) for period in self.tariff.periods.all()],
            ["00:00:00", "07:00:00", "17:00:00"],
        )

    def test_an_hour_no_band_covers_bills_at_the_days_first_band(self):
        """23:59 to midnight is left unpriced by the document's own spelling of
        end-of-day. The rule is stated rather than left to whichever row the
        database returned first."""
        self.assertEqual(self._price_at(23, 59), Decimal("0.09000"))


class BandNamingTests(BandFixture):
    """A plain band has no conventional name, so it has to be called something
    a participant reading a contract can act on."""

    def test_a_band_with_a_label_uses_it(self):
        self.assertEqual(self.band("0.24", "07:00", "17:00", label="Spitzenlast").display_name,
                         "Spitzenlast")

    def test_a_band_without_a_label_is_named_by_its_window(self):
        self.assertEqual(self.band("0.24", "07:00", "17:00").display_name, "07:00–17:00")

    def test_the_named_types_keep_their_own_names(self):
        high = TariffPeriod.objects.create(
            tariff=self.tariff, period_type=PeriodType.HIGH,
            price_chf_per_kwh=Decimal("0.2"), time_from="07:00", time_to="22:00",
        )

        self.assertEqual(high.display_name, "High tariff (HT)")


class FlatBesideBandsTests(TestCase):
    """The engine returns a flat band's price without looking at any window, so
    a flat band sharing months with a timed one makes the timed bands dead
    weight that still print on the contract."""

    def setUp(self):
        self.admin = make_user("band_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)
        self.zev = Zev.objects.create(name="Flat ZEV", owner=self.admin, zev_type="zev")
        self.tariff = Tariff.objects.create(
            zev=self.zev, name="Grid", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )

    def _post(self, **overrides):
        payload = {"tariff": str(self.tariff.id), "price_chf_per_kwh": "0.20"}
        payload.update(overrides)
        return self.client.post("/api/v1/tariffs/periods/", payload, format="json")

    def test_a_timed_band_is_refused_beside_an_existing_flat_one(self):
        self._post(period_type="flat")

        response = self._post(period_type="band", time_from="07:00", time_to="17:00")

        self.assertEqual(response.status_code, 400)
        self.assertIn("period_type", response.data)

    def test_a_flat_band_is_refused_beside_existing_timed_ones(self):
        """The other direction matters just as much — entering the flat one
        second is the more likely mistake."""
        self._post(period_type="band", time_from="07:00", time_to="17:00")

        response = self._post(period_type="flat")

        self.assertEqual(response.status_code, 400)

    def test_a_flat_winter_beside_a_timed_summer_is_allowed(self):
        """Seasons make this ordinary rather than contradictory: the flat band
        never gets the chance to short-circuit a month it does not apply in."""
        self._post(period_type="flat", months=WINTER)

        response = self._post(period_type="band", time_from="07:00", time_to="17:00", months=SUMMER)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(TariffPeriod.objects.filter(tariff=self.tariff).count(), 2)

    def test_several_timed_bands_together_are_fine(self):
        self._post(period_type="band", time_from="00:00", time_to="07:00")
        self._post(period_type="band", time_from="07:00", time_to="17:00")

        response = self._post(period_type="band", time_from="17:00", time_to="23:59")

        self.assertEqual(response.status_code, 201, response.data)

    def test_editing_a_band_does_not_collide_with_itself(self):
        created = self._post(period_type="band", time_from="07:00", time_to="17:00")

        response = self.client.patch(
            f"/api/v1/tariffs/periods/{created.data['id']}/",
            {"price_chf_per_kwh": "0.30"}, format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)


class BandVersioningTests(BandFixture):
    """A new version copies the bands; dropping the label would leave a
    contract naming a band by a window it no longer prints."""

    def test_a_new_version_carries_the_band_labels(self):
        self.band("0.24", "07:00", "17:00", label="Spitzenlast")
        self.band("0.09", "17:00", "23:59", label="Randzeit")
        client = APIClient()
        authenticate(client, self.owner)

        response = client.post(
            f"/api/v1/tariffs/tariffs/{self.tariff.pk}/new-version/",
            {"valid_from": "2027-01-01"}, format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        created = Tariff.objects.get(pk=response.data["id"])
        self.assertEqual(
            sorted(period.label for period in created.periods.all()),
            ["Randzeit", "Spitzenlast"],
        )
