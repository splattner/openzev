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

from tariffs.models import BillingMode, SplitKey, TariffCategory
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


def shared_tariff(zev, *, price="90.00", yearly=False, valid_from=JAN, valid_to=None,
                   split_key=SplitKey.EQUAL, name="Verwaltungsgebühr"):
    """A shared fee of ``price`` per month (or per year) for the whole ZEV."""
    return factories.TariffFactory(
        zev=zev,
        name=name,
        category=TariffCategory.METERING,
        billing_mode=BillingMode.SHARED_YEARLY_FEE if yearly else BillingMode.SHARED_MONTHLY_FEE,
        energy_type=None,
        fixed_price_chf=Decimal(price),
        valid_from=valid_from,
        valid_to=valid_to,
        split_key=split_key,
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


# ---------------------------------------------------------------------------
# split_key (shared metering points, docs/specs/2026-08-shared-metering-points.md)
# ---------------------------------------------------------------------------


def test_equal_key_ignores_weights_entirely():
    """The isolation guarantee: unequal weights set, split_key=equal — the
    amounts must be identical to today's headcount split, byte for byte."""
    zev = factories.ZevFactory()
    a, b, c = participants(zev, 3)
    a.allocation_weight = Decimal("10")
    a.save(update_fields=["allocation_weight"])
    b.allocation_weight = Decimal("1")
    b.save(update_fields=["allocation_weight"])
    shared_tariff(zev, price="90.00", split_key=SplitKey.EQUAL)

    lines = [fee_line(generate_invoice(p, JAN, JAN_END)) for p in (a, b, c)]

    assert [line.total_chf for line in lines] == [Decimal("30.00")] * 3


def test_weight_key_splits_by_weight():
    zev = factories.ZevFactory()
    heavy, light = participants(zev, 2)
    heavy.allocation_weight = Decimal("3")
    heavy.save(update_fields=["allocation_weight"])
    light.allocation_weight = Decimal("1")
    light.save(update_fields=["allocation_weight"])
    shared_tariff(zev, price="80.00", split_key=SplitKey.WEIGHT)

    heavy_line = fee_line(generate_invoice(heavy, JAN, JAN_END))
    light_line = fee_line(generate_invoice(light, JAN, JAN_END))

    # Weight 3 of 4 total: 80 * 3/4 = 60; weight 1 of 4: 80 * 1/4 = 20.
    assert heavy_line.total_chf == Decimal("60.00")
    assert light_line.total_chf == Decimal("20.00")


def test_split_key_defaults_to_equal():
    """A tariff created without naming a key bills as it does today."""
    zev = factories.ZevFactory()
    a, b = participants(zev, 2)
    a.allocation_weight = Decimal("5")
    a.save(update_fields=["allocation_weight"])
    tariff = factories.TariffFactory(
        zev=zev, name="Default Key Fee", category=TariffCategory.METERING,
        billing_mode=BillingMode.SHARED_MONTHLY_FEE, energy_type=None,
        fixed_price_chf=Decimal("60.00"), valid_from=JAN,
    )

    assert tariff.split_key == SplitKey.EQUAL
    line = fee_line(generate_invoice(a, JAN, JAN_END))
    assert line.total_chf == Decimal("30.00")


def test_two_shared_tariffs_can_use_different_keys():
    """One equal and one weight tariff in the same ZEV, same invoice, both
    correct — the case split_key exists for."""
    zev = factories.ZevFactory()
    heavy, light = participants(zev, 2)
    heavy.allocation_weight = Decimal("3")
    heavy.save(update_fields=["allocation_weight"])
    light.allocation_weight = Decimal("1")
    light.save(update_fields=["allocation_weight"])
    shared_tariff(zev, price="80.00", split_key=SplitKey.WEIGHT, name="Lift Electricity")
    shared_tariff(zev, price="40.00", split_key=SplitKey.EQUAL, name="Metering Administration")

    heavy_lines = {i.description.split(" (")[0]: i for i in generate_invoice(heavy, JAN, JAN_END).items.all()}
    light_lines = {i.description.split(" (")[0]: i for i in generate_invoice(light, JAN, JAN_END).items.all()}

    # Weight-keyed: 80 split 3:1 -> 60 / 20.
    assert heavy_lines["Lift Electricity"].total_chf == Decimal("60.00")
    assert light_lines["Lift Electricity"].total_chf == Decimal("20.00")
    # Equal-keyed: 40 split evenly regardless of weight -> 20 / 20.
    assert heavy_lines["Metering Administration"].total_chf == Decimal("20.00")
    assert light_lines["Metering Administration"].total_chf == Decimal("20.00")


def test_default_weights_reproduce_equal_split_under_weight_key():
    """With all weights at their default (1), WEIGHT and EQUAL agree."""
    zev = factories.ZevFactory()
    members = participants(zev, 3)
    shared_tariff(zev, price="90.00", split_key=SplitKey.WEIGHT)

    lines = [fee_line(generate_invoice(p, JAN, JAN_END)) for p in members]

    assert [line.total_chf for line in lines] == [Decimal("30.00")] * 3


def test_joiner_shifts_weight_sum_only_from_their_own_month():
    zev = factories.ZevFactory()
    founders = participants(zev, 2)
    joiner, = participants(zev, 1, valid_from=FEB)
    for p in founders:
        p.allocation_weight = Decimal("1")
        p.save(update_fields=["allocation_weight"])
    joiner.allocation_weight = Decimal("2")
    joiner.save(update_fields=["allocation_weight"])
    shared_tariff(zev, price="120.00", split_key=SplitKey.WEIGHT)

    founder_line = fee_line(generate_invoice(founders[0], JAN, MAR_END))
    joiner_line = fee_line(generate_invoice(joiner, JAN, MAR_END))

    # January: weight sum 2 (founders only) -> founder gets 120 * 1/2 = 60.
    # Feb+Mar: weight sum 4 (1+1+2) -> founder gets 120 * 1/4 = 30 each.
    assert founder_line.total_chf == Decimal("120.00")  # 60 + 30 + 30
    # Joiner: only Feb+Mar, at weight 2 of 4 -> 120 * 2/4 = 60 each.
    assert joiner_line.total_chf == Decimal("120.00")  # 60 + 60


def test_tiny_weight_bills_almost_nothing():
    zev = factories.ZevFactory()
    tiny, rest = participants(zev, 2)
    tiny.allocation_weight = Decimal("0.0001")
    tiny.save(update_fields=["allocation_weight"])
    rest.allocation_weight = Decimal("1")
    rest.save(update_fields=["allocation_weight"])
    shared_tariff(zev, price="100.00", split_key=SplitKey.WEIGHT)

    tiny_line = fee_line(generate_invoice(tiny, JAN, JAN_END))

    # 100 * 0.0001 / 1.0001, rounded to the centime, is negligible.
    assert tiny_line.total_chf < Decimal("0.02")
    assert tiny_line.total_chf >= Decimal("0.00")


def test_an_indivisible_weighted_share_leaves_the_rappen_shortfall():
    """Same documented rounding convention as the equal-key variant: a share
    that doesn't divide evenly is quantized per line, and the community
    collects a hair under the source amount."""
    zev = factories.ZevFactory()
    a, b, c = participants(zev, 3)
    for p in (a, b, c):
        p.allocation_weight = Decimal("1")
        p.save(update_fields=["allocation_weight"])
    shared_tariff(zev, price="100.00", split_key=SplitKey.WEIGHT)

    total = sum(
        fee_line(generate_invoice(p, JAN, JAN_END)).total_chf for p in (a, b, c)
    )

    assert total == Decimal("99.99")


# ---------------------------------------------------------------------------
# Tariff-clamped denominators (regression: #465)
#
# ``_price_fixed_fees`` drives its numerator loop from
# ``_billable_months(tariff, ...)``. A denominator clamped to the invoice
# *period* instead of the tariff's own validity counts members of the calendar
# month who are not members of the part the tariff actually bills — they land
# in the denominator while their own numerator loop skips them, so the
# community recovers less than the whole fee. Tariff versioning makes a
# mid-period ``valid_from`` ordinary, so this is not an exotic shape.
# ---------------------------------------------------------------------------

def test_weight_and_equal_keys_agree_when_the_tariff_starts_mid_month():
    """The isolation guarantee under a clipped tariff: with every weight at
    the default 1, ``weight`` must bill exactly what ``equal`` bills."""
    zev = factories.ZevFactory()
    stayer = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    # Leaves on the 10th — before the tariff starts on the 15th, so they are
    # never billed for it and must not sit in either denominator.
    factories.ParticipantFactory(zev=zev, valid_from=JAN, valid_to=date(2026, 1, 10))

    equal = shared_tariff(zev, price="100.00", name="Equal fee",
                          valid_from=date(2026, 1, 15), split_key=SplitKey.EQUAL)
    weight = shared_tariff(zev, price="100.00", name="Weight fee",
                           valid_from=date(2026, 1, 15), split_key=SplitKey.WEIGHT)

    invoice = generate_invoice(stayer, JAN, JAN_END)
    by_name = {item.description.split(" (")[0]: item for item in invoice.items.all()}

    assert by_name[equal.name].total_chf == Decimal("100.00")
    assert by_name[weight.name].total_chf == by_name[equal.name].total_chf


def test_weighted_shared_fee_is_fully_recovered_when_the_tariff_starts_mid_month():
    """Reconciliation property under a clipped tariff: a full ZEV run recovers
    the month's amount once, not a fraction of it."""
    zev = factories.ZevFactory()
    factories.ParticipantFactory(zev=zev, valid_from=JAN)
    factories.ParticipantFactory(zev=zev, valid_from=JAN, valid_to=date(2026, 1, 10))
    shared_tariff(zev, price="100.00", valid_from=date(2026, 1, 15),
                  split_key=SplitKey.WEIGHT)

    result = generate_invoices_for_zev(zev, JAN, JAN_END)
    recovered = sum(
        (item.total_chf for invoice in result.invoices
         for item in invoice.items.filter(tariff_category=TariffCategory.METERING)),
        Decimal("0"),
    )

    assert result.failures == []
    assert recovered == Decimal("100.00")


def test_weighted_shared_fee_denominator_still_tracks_the_billed_window():
    """The clamp must not overshoot: a member who *is* active inside the
    tariff's billed window still dilutes it."""
    zev = factories.ZevFactory()
    stayer = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    # Leaves on the 20th — inside the Jan 15..Jan 31 billed window.
    factories.ParticipantFactory(zev=zev, valid_from=JAN, valid_to=date(2026, 1, 20))
    shared_tariff(zev, price="100.00", valid_from=date(2026, 1, 15),
                  split_key=SplitKey.WEIGHT)

    assert fee_line(generate_invoice(stayer, JAN, JAN_END)).total_chf == Decimal("50.00")


# ---------------------------------------------------------------------------
# Zero-value shares (regression: bogus "N Monate / CHF 0.00" lines)
# ---------------------------------------------------------------------------

def test_a_zero_weight_member_gets_no_shared_fee_line():
    """A zero-weight member of a WEIGHT-split fee is an active month member
    (charged_months > 0), but their share computes to 0.00 — they get no line,
    matching the bucket="shared" per-metering-point rule (§4.6.4)."""
    zev = factories.ZevFactory()
    full = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    zero = factories.ParticipantFactory(
        zev=zev, valid_from=JAN, allocation_weight=Decimal("0"))
    shared_tariff(zev, price="80.00", split_key=SplitKey.WEIGHT)

    assert fee_line(generate_invoice(zero, JAN, JAN_END)) is None
    # The paying member is unaffected: weight sum excludes the zero-weight
    # member, so the full fee still lands on them.
    assert fee_line(generate_invoice(full, JAN, JAN_END)).total_chf == Decimal("80.00")


def test_an_exact_half_cent_share_survives_the_zero_line_gate():
    """The exclusion gate must quantize with the renderer's ROUND_HALF_UP, not
    Python quantize()'s default banker's rounding: a share of exactly 0.005
    bills as 0.01 and stays on the invoice instead of silently vanishing."""
    zev = factories.ZevFactory()
    billed = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    factories.ParticipantFactory(zev=zev, valid_from=JAN)  # weight-sum denominator
    shared_tariff(zev, price="0.01", split_key=SplitKey.WEIGHT)

    line = fee_line(generate_invoice(billed, JAN, JAN_END))
    assert line.total_chf == Decimal("0.01")


def test_a_shared_fee_configured_at_zero_chf_gets_no_line_either():
    """The gate covers every shared path, not just weight-split ones: a
    SHARED_* fee deliberately configured at CHF 0.00 under split_key = equal
    has the same nothing-to-bill shape as a zero-weight member, so it is
    suppressed too (§4.6.3). Plain non-shared fees keep their CHF 0.00 line
    (test_zero_and_negative_fixed_fees_are_handled_consistently)."""
    zev = factories.ZevFactory()
    member = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    factories.ParticipantFactory(zev=zev, valid_from=JAN)
    shared_tariff(zev, price="0.00", split_key=SplitKey.EQUAL)

    assert fee_line(generate_invoice(member, JAN, JAN_END)) is None
