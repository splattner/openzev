from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing.helpers import authenticate as auth
from zev.models import Zev


class TariffActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="tariff_admin",
            password="pass1234",
            role=UserRole.ADMIN,
        )

    def make_owner(self, username: str) -> User:
        return User.objects.create_user(
            username=username,
            password="pass1234",
            role=UserRole.ZEV_OWNER,
        )

    def make_client(self, user: User) -> APIClient:
        client = APIClient()
        auth(client, user)
        return client

    def test_periods_are_rejected_for_fixed_fee_tariffs(self):
        owner = self.make_owner("tariff_fixed_fee_owner")
        zev = Zev.objects.create(name="Fixed fee ZEV", owner=owner, zev_type="vzev")
        tariff = Tariff.objects.create(
            zev=zev,
            name="Monthly fee",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.MONTHLY_FEE,
            fixed_price_chf=Decimal("15.00"),
            valid_from="2026-01-01",
        )
        client = self.make_client(owner)

        response = client.post(
            "/api/v1/tariffs/periods/",
            {
                "tariff": str(tariff.id),
                "period_type": PeriodType.FLAT,
                "price_chf_per_kwh": "0.10",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"][0],
            "Tariff periods are only supported for energy-based tariffs.",
        )

    def test_periods_are_rejected_for_percentage_tariffs(self):
        owner = self.make_owner("tariff_percentage_owner")
        zev = Zev.objects.create(name="Percentage ZEV", owner=owner, zev_type="vzev")
        tariff = Tariff.objects.create(
            zev=zev,
            name="Percentage tariff",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.LOCAL,
            percentage=Decimal("7.50"),
            valid_from="2026-01-01",
        )
        client = self.make_client(owner)

        response = client.post(
            "/api/v1/tariffs/periods/",
            {
                "tariff": str(tariff.id),
                "period_type": PeriodType.FLAT,
                "price_chf_per_kwh": "0.10",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"][0],
            "Tariff periods are only supported for energy-based tariffs.",
        )

    def test_energy_tariff_period_accepts_time_and_weekday_fields(self):
        owner = self.make_owner("tariff_energy_period_owner")
        zev = Zev.objects.create(name="Energy period ZEV", owner=owner, zev_type="vzev")
        tariff = Tariff.objects.create(
            zev=zev,
            name="Timed tariff",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.LOCAL,
            valid_from="2026-01-01",
        )
        client = self.make_client(owner)

        response = client.post(
            "/api/v1/tariffs/periods/",
            {
                "tariff": str(tariff.id),
                "period_type": PeriodType.HIGH,
                "price_chf_per_kwh": "0.27",
                "time_from": "06:00",
                "time_to": "22:00",
                "weekdays": "0,1,2,3,4",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        period = TariffPeriod.objects.get(tariff=tariff)
        self.assertEqual(period.period_type, PeriodType.HIGH)
        self.assertEqual(str(period.price_chf_per_kwh), "0.27000")
        self.assertEqual(period.weekdays, "0,1,2,3,4")
