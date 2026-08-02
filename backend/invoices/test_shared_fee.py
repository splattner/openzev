"""Tests for the shared (community-split) fixed fee billing modes.

``SHARED_MONTHLY_FEE`` and ``SHARED_YEARLY_FEE`` differ from every other fixed
fee in one respect: ``fixed_price_chf`` is what the *community* pays, not what
each participant pays. The engine divides it between the participants active in
each billed month.

The month-by-month part is the whole point and is where the behaviour is easy
to get wrong, so it is pinned from both ends — the counter on its own, and the
resulting invoice lines.
"""

from datetime import date
from decimal import Decimal

import pytest

from tariffs.models import BillingMode, TariffCategory
from testing import factories

from .engine import (
    _count_active_participants_by_month,
    generate_invoice,
    generate_invoices_for_zev,
)
from .models import InvoiceItem

pytestmark = pytest.mark.django_db

JAN = date(2026, 1, 1)
MAR_END = date(2026, 3, 31)
JAN_END = date(2026, 1, 31)
FEB = date(2026, 2, 1)
MAR = date(2026, 3, 1)


def shared_tariff(zev, *, price="90.00", yearly=False, valid_from=JAN, valid_to=None):
    """A shared fee of ``price`` per month (or per year) for the whole ZEV."""
    return factories.TariffFactory(
        zev=zev,
        name="Verwaltungsgebühr",
        category=TariffCategory.METERING,
        billing_mode=BillingMode.SHARED_YEARLY_FEE if yearly else BillingMode.SHARED_MONTHLY_FEE,
        energy_type=None,
        fixed_price_chf=Decimal(price),
        valid_from=valid_from,
        valid_to=valid_to,
    )


def participants(zev, count, *, valid_from=JAN, valid_to=None):
    return [
        factories.ParticipantFactory(zev=zev, valid_from=valid_from, valid_to=valid_to)
        for _ in range(count)
    ]


def fee_line(invoice) -> InvoiceItem | None:
    return invoice.items.filter(tariff_category=TariffCategory.METERING).first()


# ---------------------------------------------------------------------------
# _count_active_participants_by_month
# ---------------------------------------------------------------------------

def test_a_stable_membership_gives_every_month_the_same_denominator():
    zev = factories.ZevFactory()
    participants(zev, 3)
    tariff = shared_tariff(zev)

    assert _count_active_participants_by_month(zev, tariff, JAN, MAR_END) == {
        JAN: 3, FEB: 3, MAR: 3,
    }


def test_a_joiner_only_changes_the_months_from_which_they_are_active():
    """The reason this is counted per month: somebody arriving in February must
    not retroactively dilute January's share."""
    zev = factories.ZevFactory()
    participants(zev, 2)
    participants(zev, 1, valid_from=FEB)
    tariff = shared_tariff(zev)

    assert _count_active_participants_by_month(zev, tariff, JAN, MAR_END) == {
        JAN: 2, FEB: 3, MAR: 3,
    }


def test_a_leaver_stops_counting_after_their_last_month():
    zev = factories.ZevFactory()
    participants(zev, 2)
    participants(zev, 1, valid_to=JAN_END)
    tariff = shared_tariff(zev)

    assert _count_active_participants_by_month(zev, tariff, JAN, MAR_END) == {
        JAN: 3, FEB: 2, MAR: 2,
    }


def test_somebody_who_left_before_the_billed_window_is_not_counted():
    """They receive no invoice, so counting them would inflate the denominator
    and leave the community short."""
    zev = factories.ZevFactory()
    participants(zev, 2)
    participants(zev, 1, valid_to=date(2026, 1, 10))
    tariff = shared_tariff(zev)

    # Billing opens on the 15th, after the third member has gone.
    assert _count_active_participants_by_month(zev, tariff, date(2026, 1, 15), JAN_END) == {JAN: 2}


def test_months_outside_the_tariffs_validity_are_absent():
    zev = factories.ZevFactory()
    participants(zev, 2)
    tariff = shared_tariff(zev, valid_from=FEB)

    assert _count_active_participants_by_month(zev, tariff, JAN, MAR_END) == {FEB: 2, MAR: 2}


def test_a_month_with_nobody_active_is_absent_rather_than_zero():
    """A zero would be a division by zero one line later in the caller."""
    zev = factories.ZevFactory()
    participants(zev, 2, valid_to=JAN_END)
    tariff = shared_tariff(zev)

    counts = _count_active_participants_by_month(zev, tariff, JAN, MAR_END)

    assert counts == {JAN: 2}
    assert all(count > 0 for count in counts.values())


def test_a_tariff_that_never_overlaps_the_period_counts_nothing():
    zev = factories.ZevFactory()
    participants(zev, 2)
    tariff = shared_tariff(zev, valid_from=date(2027, 1, 1))

    assert _count_active_participants_by_month(zev, tariff, JAN, MAR_END) == {}


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

def test_a_sole_participant_carries_the_whole_community_fee():
    zev = factories.ZevFactory()
    only, = participants(zev, 1)
    shared_tariff(zev, price="90.00")

    invoice = generate_invoice(only, JAN, JAN_END)

    assert fee_line(invoice).total_chf == Decimal("90.00")


def test_three_participants_each_carry_a_third():
    zev = factories.ZevFactory()
    members = participants(zev, 3)
    shared_tariff(zev, price="90.00")

    invoices = [generate_invoice(member, JAN, JAN_END) for member in members]

    assert [fee_line(inv).total_chf for inv in invoices] == [Decimal("30.00")] * 3


def test_the_share_is_charged_for_every_month_the_period_touches():
    zev = factories.ZevFactory()
    members = participants(zev, 2)
    shared_tariff(zev, price="90.00")

    invoice = generate_invoice(members[0], JAN, MAR_END)
    line = fee_line(invoice)

    assert line.quantity_kwh == Decimal("3.0000")
    assert line.unit == "month"
    assert line.total_chf == Decimal("135.00")  # 3 x 90/2


def test_a_joiner_shifts_the_denominator_only_from_their_own_month():
    """The founding members carry January alone and split the rest three ways;
    the joiner pays only for the months they were there."""
    zev = factories.ZevFactory()
    founders = participants(zev, 2)
    joiner, = participants(zev, 1, valid_from=FEB)
    shared_tariff(zev, price="120.00")

    founder_line = fee_line(generate_invoice(founders[0], JAN, MAR_END))
    joiner_line = fee_line(generate_invoice(joiner, JAN, MAR_END))

    # Founder: 120/2 + 120/3 + 120/3 = 60 + 40 + 40
    assert founder_line.total_chf == Decimal("140.00")
    assert founder_line.quantity_kwh == Decimal("3.0000")
    # Joiner: only the two months they were a member of, at the denominator
    # those months actually had.
    assert joiner_line.total_chf == Decimal("80.00")
    assert joiner_line.quantity_kwh == Decimal("2.0000")


def test_a_yearly_shared_fee_is_a_twelfth_of_the_amount_each_month():
    zev = factories.ZevFactory()
    members = participants(zev, 4)
    shared_tariff(zev, price="1200.00", yearly=True)

    invoice = generate_invoice(members[0], JAN, MAR_END)

    # 1200/12 = 100 per month, split four ways, over three months.
    assert fee_line(invoice).total_chf == Decimal("75.00")


def test_a_participant_with_no_readings_is_still_charged_their_share():
    """Fixed fees never look at meter readings — which is the point of a
    community fee: it is owed for membership, not for consumption."""
    zev = factories.ZevFactory()
    members = participants(zev, 2)
    shared_tariff(zev, price="50.00")

    invoice = generate_invoice(members[0], JAN, JAN_END)

    assert invoice.total_local_kwh == Decimal("0.0000")
    assert invoice.total_grid_kwh == Decimal("0.0000")
    assert fee_line(invoice).total_chf == Decimal("25.00")


def test_a_negative_shared_amount_is_credited_not_charged():
    """A community-wide rebate distributed across the members."""
    zev = factories.ZevFactory()
    members = participants(zev, 4)
    shared_tariff(zev, price="-100.00")

    line = fee_line(generate_invoice(members[0], JAN, JAN_END))

    assert line.total_chf == Decimal("-25.00")
    assert line.item_type == InvoiceItem.ItemType.CREDIT


def test_no_line_is_produced_when_the_fee_covers_no_active_month():
    zev = factories.ZevFactory()
    member, = participants(zev, 1, valid_to=JAN_END)
    shared_tariff(zev, valid_from=FEB)

    invoice = generate_invoice(member, FEB, date(2026, 2, 28))

    assert fee_line(invoice) is None


# ---------------------------------------------------------------------------
# Rounding and reconciliation
# ---------------------------------------------------------------------------

def test_an_indivisible_fee_leaves_the_community_a_rappen_short():
    """CHF 100 across three members is 33.3333... each. Lines are rounded to the
    centime independently, so the community recovers 99.99.

    Pinned as a deliberate choice, not an oversight: the alternative is to hand
    the leftover rappen to one arbitrary member, which couples each invoice to
    the others and only reconciles if every participant is actually invoiced.
    """
    zev = factories.ZevFactory()
    members = participants(zev, 3)
    shared_tariff(zev, price="100.00")

    invoices = [generate_invoice(member, JAN, JAN_END) for member in members]
    lines = [fee_line(inv).total_chf for inv in invoices]

    assert lines == [Decimal("33.33")] * 3
    assert sum(lines) == Decimal("99.99")


def test_a_full_run_recovers_the_community_amount():
    zev = factories.ZevFactory()
    participants(zev, 4)
    shared_tariff(zev, price="240.00")

    invoices, failures = generate_invoices_for_zev(zev, JAN, MAR_END)

    assert failures == []
    assert len(invoices) == 4
    assert sum(fee_line(inv).total_chf for inv in invoices) == Decimal("720.00")  # 3 x 240


def test_a_full_run_reconciles_even_as_membership_changes():
    """Every month's fee is recovered exactly once across the run, no matter who
    was present for it."""
    zev = factories.ZevFactory()
    participants(zev, 2)
    participants(zev, 1, valid_from=FEB)
    participants(zev, 1, valid_to=JAN_END)
    shared_tariff(zev, price="60.00")

    invoices, failures = generate_invoices_for_zev(zev, JAN, MAR_END)

    assert failures == []
    assert len(invoices) == 4
    assert sum(fee_line(inv).total_chf for inv in invoices) == Decimal("180.00")  # 3 x 60


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def test_the_unit_price_shows_the_average_monthly_share():
    zev = factories.ZevFactory()
    founders = participants(zev, 2)
    participants(zev, 1, valid_from=FEB)
    shared_tariff(zev, price="120.00")

    line = fee_line(generate_invoice(founders[0], JAN, MAR_END))

    # 60 + 40 + 40 over three months.
    assert line.unit_price_chf == Decimal("46.66667")


def test_the_description_names_the_fee_as_shared_without_a_headcount():
    """The denominator can differ between the months on one line, so no single
    count would be truthful."""
    zev = factories.ZevFactory(invoice_language="de")
    members = participants(zev, 3)
    shared_tariff(zev)

    line = fee_line(generate_invoice(members[0], JAN, MAR_END))

    assert line.description == "Verwaltungsgebühr (3 Monate, Gemeinschaftskosten anteilig)"


def test_a_single_month_uses_the_singular():
    zev = factories.ZevFactory(invoice_language="en")
    members = participants(zev, 2)
    shared_tariff(zev)

    line = fee_line(generate_invoice(members[0], JAN, JAN_END))

    assert line.description == "Verwaltungsgebühr (1 month, share of community costs)"


def test_a_shared_yearly_fee_says_so():
    zev = factories.ZevFactory(invoice_language="en")
    members = participants(zev, 2)
    shared_tariff(zev, price="1200.00", yearly=True)

    line = fee_line(generate_invoice(members[0], JAN, MAR_END))

    assert line.description == (
        "Verwaltungsgebühr (3 monthly installments of annual fee, share of community costs)"
    )
