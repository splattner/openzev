"""One-off charges (#924): who bears them, the shares, and the invoice lines."""

from datetime import date
from decimal import Decimal

import pytest

from tariffs.models import SplitKey, TariffCategory
from testing import factories
from zev.models import VatMode

from .charges import charge_bearers, split_charge
from .engine import generate_invoice, generate_invoices_for_zev
from .models import Charge, ChargeAllocation, ChargeVatTreatment, InvoiceItem

pytestmark = pytest.mark.django_db

JAN = date(2026, 1, 1)
JAN_END = date(2026, 1, 31)
FEB = date(2026, 2, 1)
FEB_END = date(2026, 2, 28)


def charge(zev, *, amount="30.00", day=date(2026, 1, 15), participants=(), **kwargs):
    if participants:
        kwargs.setdefault("allocation", ChargeAllocation.SELECTED_PARTICIPANTS)
    made = Charge.objects.create(
        zev=zev, description=kwargs.pop("description", "Porto"), amount_chf=Decimal(amount),
        charge_date=day, **kwargs,
    )
    made.participants.set(participants)
    return made


def charge_items(invoice):
    return list(invoice.items.filter(tariff_category=TariffCategory.OTHER))


def members(zev, count, **kwargs):
    return [factories.ParticipantFactory(zev=zev, valid_from=JAN, **kwargs) for _ in range(count)]


# ── bearers ──────────────────────────────────────────────────────────────────

def test_all_participants_bear_a_charge_by_membership_on_the_charge_date():
    zev = factories.ZevFactory()
    present = members(zev, 2)
    factories.ParticipantFactory(zev=zev, valid_from=date(2026, 1, 20))  # joins after
    factories.ParticipantFactory(zev=zev, valid_from=JAN, valid_to=date(2026, 1, 10))  # left before
    made = charge(zev)

    assert {p.pk for p in charge_bearers(made)} == {p.pk for p in present}


def test_selected_participants_bear_only_their_own_charge():
    zev = factories.ZevFactory()
    first, second, _third = members(zev, 3)
    made = charge(zev, participants=[first, second])

    assert {p.pk for p in charge_bearers(made)} == {first.pk, second.pk}


def test_a_selected_participant_who_is_not_a_member_that_day_bears_nothing():
    zev = factories.ZevFactory()
    (first,) = members(zev, 1)
    leaver = factories.ParticipantFactory(zev=zev, valid_from=JAN, valid_to=date(2026, 1, 10))
    made = charge(zev, participants=[first, leaver])

    assert [p.pk for p in charge_bearers(made)] == [first.pk]


# ── shares ───────────────────────────────────────────────────────────────────

def test_equal_split_rounds_each_share_on_its_own():
    zev = factories.ZevFactory()
    bearers = members(zev, 3)

    shares = split_charge(Decimal("10.00"), SplitKey.EQUAL, bearers)

    assert set(shares.values()) == {Decimal("3.33")}
    assert sum(shares.values()) == Decimal("9.99")


def test_weight_split_follows_allocation_weight_and_skips_a_zero_weight_member():
    zev = factories.ZevFactory()
    heavy, light = members(zev, 2)
    heavy.allocation_weight, light.allocation_weight = Decimal("3"), Decimal("1")
    zero = factories.ParticipantFactory(zev=zev, valid_from=JAN, allocation_weight=Decimal("0"))

    shares = split_charge(Decimal("40.00"), SplitKey.WEIGHT, [heavy, light, zero])

    assert shares == {heavy.pk: Decimal("30.00"), light.pk: Decimal("10.00")}


def test_a_single_bearer_pays_everything_under_either_split_key():
    zev = factories.ZevFactory()
    (only,) = members(zev, 1)

    for key in (SplitKey.EQUAL, SplitKey.WEIGHT):
        assert split_charge(Decimal("12.50"), key, [only]) == {only.pk: Decimal("12.50")}


def test_nobody_to_bill_gives_no_shares():
    assert split_charge(Decimal("10.00"), SplitKey.EQUAL, []) == {}


# ── invoice lines ────────────────────────────────────────────────────────────

def test_the_charge_is_a_flat_fee_line_under_the_other_category():
    zev = factories.ZevFactory()
    first, _second = members(zev, 2)
    charge(zev, amount="30.00")

    invoice = generate_invoice(first, JAN, JAN_END)

    (item,) = charge_items(invoice)
    assert (item.item_type, item.unit, item.quantity_kwh) == ("fee", "flat", Decimal("1"))
    assert item.total_chf == item.unit_price_chf == Decimal("15.00")
    assert "Porto" in item.description and "Gemeinschaftskosten" in item.description
    assert invoice.subtotal_chf == invoice.total_chf == Decimal("15.00")


def test_a_charge_borne_by_one_participant_carries_no_sharing_marker():
    zev = factories.ZevFactory()
    first, second = members(zev, 2)
    charge(zev, amount="30.00", participants=[first])

    (item,) = charge_items(generate_invoice(first, JAN, JAN_END))
    assert (item.description, item.total_chf) == ("Porto", Decimal("30.00"))
    assert charge_items(generate_invoice(second, JAN, JAN_END)) == []


def test_regeneration_bills_the_charge_again():
    zev = factories.ZevFactory()
    (first,) = members(zev, 1)
    charge(zev, amount="8.00")

    generate_invoice(first, JAN, JAN_END)
    again = generate_invoice(first, JAN, JAN_END)

    assert [i.total_chf for i in charge_items(again)] == [Decimal("8.00")]
    assert again.total_chf == Decimal("8.00")


def test_a_charge_outside_the_period_is_not_billed():
    zev = factories.ZevFactory()
    (first,) = members(zev, 1)
    charge(zev, day=date(2026, 2, 1))

    assert charge_items(generate_invoice(first, JAN, JAN_END)) == []
    assert len(charge_items(generate_invoice(first, FEB, FEB_END))) == 1


def test_batch_and_single_generation_give_the_same_shares():
    zev = factories.ZevFactory()
    people = members(zev, 3)
    charge(zev, amount="10.00")

    batch = {inv.participant_id: inv for inv in generate_invoices_for_zev(zev, JAN, JAN_END).invoices}
    single = {p.pk: generate_invoice(p, JAN, JAN_END) for p in people}

    for person in people:
        assert batch[person.pk].total_chf == single[person.pk].total_chf == Decimal("3.33")


def test_a_participant_with_nothing_else_to_bill_gets_an_invoice_of_the_charge_alone():
    zev = factories.ZevFactory()
    members(zev, 2)
    charge(zev, amount="20.00")

    result = generate_invoices_for_zev(zev, JAN, JAN_END)

    assert not result.failures
    assert sorted(inv.total_chf for inv in result.invoices) == [Decimal("10.00")] * 2


# ── VAT ──────────────────────────────────────────────────────────────────────

# The migration seeds the 8.1 % rate valid from 2024.
def registered_zev():
    zev = factories.ZevFactory(vat_mode=VatMode.REGISTERED, vat_number="CHE-123.456.789")
    return zev


def test_a_taxable_charge_is_in_the_vat_base_of_a_registered_zev():
    zev = registered_zev()
    (first,) = members(zev, 1)
    charge(zev, amount="100.00", vat_treatment=ChargeVatTreatment.TAXABLE)

    invoice = generate_invoice(first, JAN, JAN_END)

    assert (invoice.vat_base_chf, invoice.vat_chf, invoice.total_chf) == (
        Decimal("100.00"), Decimal("8.10"), Decimal("108.10"),
    )


def test_a_pass_through_charge_is_billed_but_not_taxed():
    zev = registered_zev()
    (first,) = members(zev, 1)
    charge(zev, amount="100.00", vat_treatment=ChargeVatTreatment.PASS_THROUGH)
    charge(zev, amount="50.00", description="Reparatur")

    invoice = generate_invoice(first, JAN, JAN_END)

    assert (invoice.subtotal_chf, invoice.vat_base_chf, invoice.vat_chf, invoice.total_chf) == (
        Decimal("150.00"), Decimal("50.00"), Decimal("4.05"), Decimal("154.05"),
    )
    assert invoice.pass_through_chf == Decimal("100.00")


def test_a_share_of_a_thousand_francs_or_more_can_be_invoiced():
    # The flat line's unit price holds the share; a narrow column overflowed
    # on PostgreSQL from CHF 1,000.
    zev = factories.ZevFactory()
    (first,) = members(zev, 1)
    charge(zev, amount="12345.67", description="Dach")

    invoice = generate_invoice(first, JAN, JAN_END)

    (item,) = charge_items(invoice)
    assert (item.unit_price_chf, item.total_chf) == (Decimal("12345.67"), Decimal("12345.67"))


@pytest.mark.parametrize("mode", [VatMode.NOT_REGISTERED, VatMode.INCLUSIVE])
def test_other_vat_modes_bill_the_charge_as_entered(mode):
    zev = factories.ZevFactory(vat_mode=mode)
    (first,) = members(zev, 1)
    charge(zev, amount="100.00")

    invoice = generate_invoice(first, JAN, JAN_END)

    assert (invoice.total_chf, invoice.vat_chf) == (Decimal("100.00"), Decimal("0.00"))
    assert not invoice.embedded_vat_chf


# ── readiness ────────────────────────────────────────────────────────────────

def charges_step(zev):
    from .readiness import compute_readiness

    steps = {step["key"]: step for step in compute_readiness(zev, JAN, JAN_END)["steps"]}
    return steps["charges"], list(steps)


def test_readiness_has_nothing_to_say_without_charges():
    zev = factories.ZevFactory()
    members(zev, 1)

    step, order = charges_step(zev)

    assert (step["status"], step["count"]) == ("done", 0)
    assert order.index("generated") < order.index("charges") < order.index("approved")


def test_a_draft_that_predates_a_charge_change_asks_for_regeneration():
    zev = factories.ZevFactory()
    (first,) = members(zev, 1)
    generate_invoice(first, JAN, JAN_END)
    charge(zev)

    step, _order = charges_step(zev)
    assert (step["status"], step["detail_data"]["stale_drafts"]) == ("todo", 1)

    generate_invoice(first, JAN, JAN_END)
    assert charges_step(zev)[0]["status"] == "done"


@pytest.mark.parametrize("change", ["delete", "move_date", "remove_bearer"])
def test_a_draft_billing_a_charge_that_no_longer_applies_asks_for_regeneration(change):
    zev = factories.ZevFactory()
    first, second = members(zev, 2)
    made = charge(zev, participants=[first, second])
    generate_invoice(first, JAN, JAN_END)
    assert charges_step(zev)[0]["status"] == "done"

    if change == "delete":
        made.delete()
    elif change == "move_date":
        made.charge_date = date(2026, 2, 15)
        made.save()
    else:
        made.participants.set([second])
        made.save()

    step, _order = charges_step(zev)
    assert (step["status"], step["detail_data"]["stale_drafts"]) == ("todo", 1)

    generate_invoice(first, JAN, JAN_END)
    assert charges_step(zev)[0]["status"] == "done"


def test_a_charge_nobody_can_bear_is_a_warning():
    zev = factories.ZevFactory()
    members(zev, 1)
    leaver = factories.ParticipantFactory(zev=zev, valid_from=JAN, valid_to=date(2026, 1, 5))
    charge(zev, participants=[leaver], description="Reparatur")

    step, _order = charges_step(zev)

    assert step["status"] == "warn"
    assert step["detail_data"]["unbilled_charges"] == ["Reparatur"]


# ── category and PDF ─────────────────────────────────────────────────────────

def test_a_tariff_cannot_use_the_charge_only_category(owner_client, zev):
    response = owner_client.post("/api/v1/tariffs/tariffs/", {
        "zev": str(zev.pk), "name": "Porto", "category": "other", "billing_mode": "monthly_fee",
        "fixed_price_chf": "5.00", "valid_from": "2026-01-01",
    }, format="json")

    assert response.status_code == 400
    assert "category" in response.data


def test_every_category_has_a_pdf_group_and_a_translation_in_every_language():
    from .pdf import _group_items_by_category
    from .pdf_translations import INVOICE_TRANSLATIONS

    zev = factories.ZevFactory()
    (first,) = members(zev, 1)
    invoice = generate_invoice(first, JAN, JAN_END)  # no items yet
    for category in TariffCategory.values:
        InvoiceItem.objects.create(
            invoice=invoice, item_type="fee", tariff_category=category, description=category,
            quantity_kwh=Decimal("1"), unit="flat", unit_price_chf=Decimal("1"), total_chf=Decimal("1"),
        )
    for lang, translations in INVOICE_TRANSLATIONS.items():
        groups = _group_items_by_category(list(invoice.items.all()), JAN, JAN_END, translations)
        assert [group["key"] for group in groups] == list(TariffCategory.values), lang
        assert groups[-1]["items"][0]["unit_label"] == translations["unit_flat"]
