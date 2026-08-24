from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from tariffs.models import BillingMode, SplitKey, Tariff, TariffCategory
from zev.models import Zev


from testing.helpers import authenticate as auth


class TariffPermissionTests(TestCase):
	def test_participant_cannot_access_tariffs(self):
		client = APIClient()
		participant = User.objects.create_user(
			username="tariff_participant",
			password="pass1234",
			role=UserRole.PARTICIPANT,
		)
		auth(client, participant)

		resp = client.get("/api/v1/tariffs/tariffs/")
		self.assertEqual(resp.status_code, 403)

	def test_owner_can_create_monthly_fee_tariff(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		resp = client.post("/api/v1/tariffs/tariffs/", {
			"zev": str(zev.id),
			"name": "Monthly metering fee",
			"category": TariffCategory.GRID_FEES,
			"billing_mode": BillingMode.MONTHLY_FEE,
			"fixed_price_chf": "15.00",
			"valid_from": "2026-01-01",
		}, format="json")
		self.assertEqual(resp.status_code, 201)
		self.assertEqual(Tariff.objects.get(name="Monthly metering fee").energy_type, None)

	def test_owner_can_create_per_metering_point_monthly_fee_tariff(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_3",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff ZEV 3", owner=owner, zev_type="vzev")
		auth(client, owner)

		resp = client.post("/api/v1/tariffs/tariffs/", {
			"zev": str(zev.id),
			"name": "Per MP monthly",
			"category": TariffCategory.GRID_FEES,
			"billing_mode": BillingMode.PER_METERING_POINT_MONTHLY_FEE,
			"fixed_price_chf": "4.50",
			"valid_from": "2026-01-01",
		}, format="json")
		self.assertEqual(resp.status_code, 201)

	def test_owner_can_create_shared_fee_tariff(self):
		"""The shared modes fall into the serializer's generic fixed-fee branch,
		so they require a price and have their energy type cleared without the
		serializer needing to know about them."""
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_shared",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff ZEV Shared", owner=owner, zev_type="vzev")
		auth(client, owner)

		resp = client.post("/api/v1/tariffs/tariffs/", {
			"zev": str(zev.id),
			"name": "Shared admin fee",
			"category": TariffCategory.GRID_FEES,
			"billing_mode": BillingMode.SHARED_MONTHLY_FEE,
			"energy_type": "local",
			"fixed_price_chf": "90.00",
			"valid_from": "2026-01-01",
		}, format="json")
		self.assertEqual(resp.status_code, 201)
		self.assertIsNone(Tariff.objects.get(name="Shared admin fee").energy_type)

	def test_shared_fee_tariff_requires_a_price(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_owner_shared_2",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff ZEV Shared 2", owner=owner, zev_type="vzev")
		auth(client, owner)

		resp = client.post("/api/v1/tariffs/tariffs/", {
			"zev": str(zev.id),
			"name": "Shared yearly fee",
			"category": TariffCategory.GRID_FEES,
			"billing_mode": BillingMode.SHARED_YEARLY_FEE,
			"valid_from": "2026-01-01",
		}, format="json")
		self.assertEqual(resp.status_code, 400)
		self.assertIn("fixed_price_chf", resp.data)

	def _post_tariff(self, client, zev, name, *, valid_from, valid_to=None,
	                 category=TariffCategory.ENERGY, billing_mode=BillingMode.ENERGY,
	                 energy_type="local", **extra):
		payload = {
			"zev": str(zev.id),
			"name": name,
			"category": category,
			"billing_mode": billing_mode,
			"energy_type": energy_type,
			"valid_from": valid_from,
			"valid_to": valid_to,
			**extra,
		}
		return client.post("/api/v1/tariffs/tariffs/", payload, format="json")

	def test_rejects_overlapping_tariffs_with_the_same_name(self):
		"""A second version of a tariff created without closing the first would
		apply both at once and double-bill every participant."""
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_overlap_owner",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff Overlap ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		first = self._post_tariff(client, zev, "Local Energy", valid_from="2026-01-01", valid_to="2026-12-31")
		self.assertEqual(first.status_code, 201)

		second = self._post_tariff(client, zev, "Local Energy", valid_from="2026-06-01", valid_to="2027-05-31")

		self.assertEqual(second.status_code, 400)
		self.assertIn("valid_from", second.data)
		self.assertIn("Local Energy", str(second.data["valid_from"]))

	def test_allows_overlapping_tariffs_with_different_names(self):
		"""Distinct per-kWh components of one category coexist by design — grid
		fees are Netznutzung *and* SDL — and the engine accumulates them into
		separate invoice lines."""
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_components_owner",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff Components ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		first = self._post_tariff(
			client, zev, "Netznutzung Arbeit", valid_from="2026-01-01",
			category=TariffCategory.GRID_FEES, energy_type="grid")
		second = self._post_tariff(
			client, zev, "Systemdienstleistung SDL", valid_from="2026-01-01",
			category=TariffCategory.GRID_FEES, energy_type="grid")

		self.assertEqual(first.status_code, 201)
		self.assertEqual(second.status_code, 201)
		self.assertEqual(Tariff.objects.filter(zev=zev, category=TariffCategory.GRID_FEES).count(), 2)

	def test_allows_the_same_name_in_consecutive_windows(self):
		"""Seasonal versioning done properly: the old window is closed first."""
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_seasonal_owner",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff Seasonal ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		first = self._post_tariff(client, zev, "Local Energy", valid_from="2026-01-01", valid_to="2026-03-31")
		second = self._post_tariff(client, zev, "Local Energy", valid_from="2026-04-01")

		self.assertEqual(first.status_code, 201)
		self.assertEqual(second.status_code, 201)

	def test_rejects_overlapping_fixed_fees_with_the_same_name(self):
		"""The guard used to skip fixed fees entirely, so a duplicated monthly
		fee was charged twice with nothing to catch it."""
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_fee_overlap_owner",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff Fee Overlap ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		first = self._post_tariff(
			client, zev, "Metering Fee", valid_from="2026-01-01",
			category=TariffCategory.METERING, billing_mode=BillingMode.MONTHLY_FEE,
			energy_type=None, fixed_price_chf="5.00")
		second = self._post_tariff(
			client, zev, "Metering Fee", valid_from="2026-06-01",
			category=TariffCategory.METERING, billing_mode=BillingMode.MONTHLY_FEE,
			energy_type=None, fixed_price_chf="6.00")

		self.assertEqual(first.status_code, 201)
		self.assertEqual(second.status_code, 400)

	def test_allows_adjacent_non_overlapping_energy_tariffs(self):
		client = APIClient()
		owner = User.objects.create_user(
			username="tariff_nonoverlap_owner",
			password="pass1234",
			role=UserRole.ZEV_OWNER,
		)
		zev = Zev.objects.create(name="Tariff NonOverlap ZEV", owner=owner, zev_type="vzev")
		auth(client, owner)

		first_resp = client.post(
			"/api/v1/tariffs/tariffs/",
			{
				"zev": str(zev.id),
				"name": "Local Energy 2026",
				"category": TariffCategory.ENERGY,
				"billing_mode": BillingMode.ENERGY,
				"energy_type": "local",
				"valid_from": "2026-01-01",
				"valid_to": "2026-12-31",
			},
			format="json",
		)
		self.assertEqual(first_resp.status_code, 201)

		second_resp = client.post(
			"/api/v1/tariffs/tariffs/",
			{
				"zev": str(zev.id),
				"name": "Local Energy 2027",
				"category": TariffCategory.ENERGY,
				"billing_mode": BillingMode.ENERGY,
				"energy_type": "local",
				"valid_from": "2027-01-01",
				"valid_to": None,
			},
			format="json",
		)

		self.assertEqual(second_resp.status_code, 201)


class SplitKeyModelAndApiTests(TestCase):
	"""split_key model default and API round-trip (shared metering points,
	docs/specs/2026-08-shared-metering-points.md). Billing behaviour is pinned
	in invoices/test_shared_fee.py; this class only covers the field itself."""

	def setUp(self):
		self.client = APIClient()
		self.owner = User.objects.create_user(
			username="split_key_owner", password="pass1234", role=UserRole.ZEV_OWNER,
		)
		self.zev = Zev.objects.create(name="Split Key ZEV", owner=self.owner, zev_type="vzev")
		auth(self.client, self.owner)

	def _post_tariff(self, name, *, billing_mode, energy_type=None, fixed_price_chf="100.00", **extra):
		payload = {
			"zev": str(self.zev.id),
			"name": name,
			"category": TariffCategory.METERING,
			"billing_mode": billing_mode,
			"energy_type": energy_type,
			"fixed_price_chf": fixed_price_chf,
			"valid_from": "2026-01-01",
			**extra,
		}
		return self.client.post("/api/v1/tariffs/tariffs/", payload, format="json")

	def test_split_key_defaults_to_equal(self):
		for billing_mode in (BillingMode.ENERGY, BillingMode.SHARED_MONTHLY_FEE):
			with self.subTest(billing_mode=billing_mode):
				tariff = Tariff.objects.create(
					zev=self.zev, name=f"Default {billing_mode}",
					category=TariffCategory.METERING, billing_mode=billing_mode,
					energy_type="local" if billing_mode == BillingMode.ENERGY else None,
					valid_from=date(2026, 1, 1),
				)
				self.assertEqual(tariff.split_key, SplitKey.EQUAL)

	def test_split_key_exposed_and_writable_via_api(self):
		create_resp = self._post_tariff(
			"Metering Fee", billing_mode=BillingMode.SHARED_MONTHLY_FEE, split_key="weight",
		)
		self.assertEqual(create_resp.status_code, 201, create_resp.content)
		self.assertEqual(create_resp.data["split_key"], "weight")

		tariff_id = create_resp.data["id"]
		get_resp = self.client.get(f"/api/v1/tariffs/tariffs/{tariff_id}/")
		self.assertEqual(get_resp.data["split_key"], "weight")

		patch_resp = self.client.patch(
			f"/api/v1/tariffs/tariffs/{tariff_id}/", {"split_key": "equal"}, format="json",
		)
		self.assertEqual(patch_resp.status_code, 200, patch_resp.content)
		self.assertEqual(patch_resp.data["split_key"], "equal")

	def test_split_key_is_accepted_but_inert_on_non_shared_modes(self):
		"""split_key is read only by the two shared billing modes (model
		docstring); storing it on any other mode is harmless."""
		resp = self._post_tariff(
			"Local Energy", billing_mode=BillingMode.ENERGY, energy_type="local",
			fixed_price_chf=None, split_key="weight",
		)
		self.assertEqual(resp.status_code, 201, resp.content)
		self.assertEqual(resp.data["split_key"], "weight")
		tariff = Tariff.objects.get(pk=resp.data["id"])
		self.assertEqual(tariff.billing_mode, BillingMode.ENERGY)
