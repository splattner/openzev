"""factory_boy factories for the OpenZEV test suite.

These replace the hand-written ``make_user`` / ``setUp`` object graphs that were
duplicated across every app's test module. Use them to build only the objects a
test actually cares about, letting the factory supply sensible defaults for the
rest.

Example::

    from testing.factories import ParticipantFactory, assignment_for

    participant = ParticipantFactory()           # also creates a Zev + owner
    assignment = assignment_for(participant)      # + metering point + assignment

All date defaults are anchored on 2026-01-01 to match the existing tests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from accounts.models import User, UserRole
from invoices.models import Invoice, InvoiceItem, InvoiceStatus
from tariffs.models import (
    BillingMode,
    EnergyType,
    PeriodType,
    Tariff,
    TariffCategory,
    TariffPeriod,
)
from zev.models import (
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointType,
    Participant,
    Zev,
    ZevType,
)

DEFAULT_VALID_FROM = date(2026, 1, 1)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    role = UserRole.PARTICIPANT
    password = factory.PostGenerationMethodCall("set_password", "pass1234")


class AdminFactory(UserFactory):
    username = factory.Sequence(lambda n: f"admin{n}")
    role = UserRole.ADMIN
    is_staff = True


class OwnerFactory(UserFactory):
    username = factory.Sequence(lambda n: f"owner{n}")
    role = UserRole.ZEV_OWNER


class ParticipantUserFactory(UserFactory):
    username = factory.Sequence(lambda n: f"participant{n}")
    role = UserRole.PARTICIPANT


# ---------------------------------------------------------------------------
# ZEV core graph
# ---------------------------------------------------------------------------

class ZevFactory(DjangoModelFactory):
    class Meta:
        model = Zev

    name = factory.Sequence(lambda n: f"Test ZEV {n}")
    owner = factory.SubFactory(OwnerFactory)
    zev_type = ZevType.VZEV
    invoice_prefix = "INV"


class ParticipantFactory(DjangoModelFactory):
    class Meta:
        model = Participant

    zev = factory.SubFactory(ZevFactory)
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = factory.Sequence(lambda n: f"Last{n}")
    email = factory.LazyAttribute(lambda o: f"{o.first_name}.{o.last_name}@example.com".lower())
    valid_from = DEFAULT_VALID_FROM


class MeteringPointFactory(DjangoModelFactory):
    class Meta:
        model = MeteringPoint

    zev = factory.SubFactory(ZevFactory)
    meter_id = factory.Sequence(lambda n: f"MP-{n:05d}")
    meter_type = MeteringPointType.CONSUMPTION
    is_active = True


class MeteringPointAssignmentFactory(DjangoModelFactory):
    class Meta:
        model = MeteringPointAssignment

    metering_point = factory.SubFactory(MeteringPointFactory)
    participant = factory.SubFactory(ParticipantFactory)
    valid_from = DEFAULT_VALID_FROM


# ---------------------------------------------------------------------------
# Tariffs
# ---------------------------------------------------------------------------

class TariffFactory(DjangoModelFactory):
    class Meta:
        model = Tariff

    zev = factory.SubFactory(ZevFactory)
    name = factory.Sequence(lambda n: f"Tariff {n}")
    category = TariffCategory.ENERGY
    billing_mode = BillingMode.ENERGY
    energy_type = EnergyType.LOCAL
    valid_from = DEFAULT_VALID_FROM


class TariffPeriodFactory(DjangoModelFactory):
    class Meta:
        model = TariffPeriod

    tariff = factory.SubFactory(TariffFactory)
    period_type = PeriodType.FLAT
    price_chf_per_kwh = Decimal("0.20000")


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

class InvoiceFactory(DjangoModelFactory):
    class Meta:
        model = Invoice
        skip_postgeneration_save = True

    invoice_number = factory.Sequence(lambda n: f"INV-{n:05d}")
    zev = factory.SubFactory(ZevFactory)
    participant = factory.SubFactory(
        ParticipantFactory,
        zev=factory.SelfAttribute("..zev"),
    )
    period_start = DEFAULT_VALID_FROM
    period_end = date(2026, 1, 31)
    status = InvoiceStatus.DRAFT
    total_chf = Decimal("0.00")

    @factory.post_generation
    def dynamic_evidence(self, create, extracted, **kwargs):
        if create:
            from tariffs.dynamic.evidence import record_invoice_evidence

            # Match generated invoices; reload dates supplied as strings.
            self.refresh_from_db()
            record_invoice_evidence(self, Tariff.objects.filter(zev_id=self.zev_id))


class InvoiceItemFactory(DjangoModelFactory):
    class Meta:
        model = InvoiceItem

    invoice = factory.SubFactory(InvoiceFactory)
    item_type = InvoiceItem.ItemType.LOCAL_ENERGY
    tariff_category = TariffCategory.ENERGY
    description = "Local energy"
    quantity_kwh = Decimal("100.0000")
    unit_price_chf = Decimal("0.20000")
    total_chf = Decimal("20.00")


# ---------------------------------------------------------------------------
# Convenience builders
# ---------------------------------------------------------------------------

def assignment_for(participant, *, meter_type=MeteringPointType.CONSUMPTION,
                   valid_from=None, valid_to=None) -> MeteringPointAssignment:
    """Create a metering point in the participant's ZEV and assign it.

    Keeps the metering point and assignment in the same ZEV as ``participant``,
    which the model's ``clean()`` requires.
    """
    metering_point = MeteringPointFactory(zev=participant.zev, meter_type=meter_type)
    return MeteringPointAssignmentFactory(
        metering_point=metering_point,
        participant=participant,
        valid_from=valid_from or participant.valid_from,
        valid_to=valid_to,
    )


def flat_tariff(zev, *, category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL,
                price="0.20000", valid_from=None, valid_to=None) -> Tariff:
    """Create a flat-rate energy tariff with a single FLAT period."""
    tariff = TariffFactory(
        zev=zev,
        category=category,
        billing_mode=BillingMode.ENERGY,
        energy_type=energy_type,
        valid_from=valid_from or DEFAULT_VALID_FROM,
        valid_to=valid_to,
    )
    TariffPeriodFactory(tariff=tariff, period_type=PeriodType.FLAT,
                        price_chf_per_kwh=Decimal(price))
    return tariff
