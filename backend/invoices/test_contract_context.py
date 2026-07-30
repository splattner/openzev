from datetime import date
from unittest.mock import patch

from django.test import TestCase

from accounts.models import UserRole
from invoices.contract_pdf import _build_contract_context
from invoices.test_helpers import make_participant, make_user, make_zev
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType


class ContractPdfContextTests(TestCase):
    def setUp(self):
        self.owner = make_user("contract_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Contract ZEV")
        self.participant = make_participant(self.zev, first="Future", last="Participant")

    def test_future_metering_point_assignments_are_included_in_contract_context(self):
        current_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-CONTRACT-CURRENT",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        future_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-CONTRACT-FUTURE",
            meter_type=MeteringPointType.PRODUCTION,
        )
        past_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-CONTRACT-PAST",
            meter_type=MeteringPointType.CONSUMPTION,
        )

        MeteringPointAssignment.objects.create(
            metering_point=current_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        MeteringPointAssignment.objects.create(
            metering_point=future_mp,
            participant=self.participant,
            valid_from=date(2026, 6, 1),
        )
        MeteringPointAssignment.objects.create(
            metering_point=past_mp,
            participant=self.participant,
            valid_from=date(2025, 1, 1),
            valid_to=date(2026, 2, 28),
        )

        with patch("invoices.contract_pdf.date") as mocked_date:
            mocked_date.today.return_value = date(2026, 4, 15)
            context = _build_contract_context(self.participant)

        self.assertEqual(
            [mp.meter_id for mp in context["consumption_mps"]],
            ["CH-CONTRACT-CURRENT"],
        )
        self.assertEqual(
            [mp.meter_id for mp in context["production_mps"]],
            ["CH-CONTRACT-FUTURE"],
        )


class ContractPdfPaymentTermsTests(TestCase):
    """Regression: the contract PDF hardcoded 'payable within 30 days'
    independently of the invoice PDF's own copy of the same bug (#365 follow-up)."""

    def setUp(self):
        self.owner = make_user("contract_terms_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Contract Terms ZEV")
        self.participant = make_participant(self.zev, first="Terms", last="Participant")

    def test_payment_terms_unit_follows_the_zevs_configured_term(self):
        self.zev.payment_term_days = 45
        self.zev.save(update_fields=["payment_term_days"])

        context = _build_contract_context(self.participant)

        self.assertEqual(context["zev"].payment_term_days, 45)
        self.assertEqual(context["tr"]["payment_terms_unit"], "Tage ab Rechnungsdatum")

    def test_payment_terms_unit_uses_the_default_thirty_days(self):
        context = _build_contract_context(self.participant)

        self.assertEqual(context["zev"].payment_term_days, 30)
        self.assertEqual(context["tr"]["payment_terms_unit"], "Tage ab Rechnungsdatum")

    def test_payment_terms_unit_is_grammatically_singular_for_one_day(self):
        self.zev.payment_term_days = 1
        self.zev.save(update_fields=["payment_term_days"])

        context = _build_contract_context(self.participant)

        self.assertEqual(context["tr"]["payment_terms_unit"], "Tag ab Rechnungsdatum")

    def test_payment_terms_unit_is_translated_per_zev_invoice_language(self):
        self.zev.payment_term_days = 45
        self.zev.invoice_language = "en"
        self.zev.save(update_fields=["payment_term_days", "invoice_language"])

        context = _build_contract_context(self.participant)

        self.assertEqual(context["tr"]["payment_terms_unit"], "days from invoice date")

    def test_building_one_contracts_context_does_not_leak_into_another(self):
        """CONTRACT_TRANSLATIONS is a module-level constant shared by every
        contract; resolving payment_terms_unit must copy it, not mutate it in
        place, or one ZEV's term would bleed into the next contract rendered
        in the same process."""
        self.zev.payment_term_days = 45
        self.zev.save(update_fields=["payment_term_days"])
        _build_contract_context(self.participant)

        other_owner = make_user("contract_terms_owner_other", UserRole.ZEV_OWNER)
        other_zev = make_zev(other_owner, "Other Contract Terms ZEV")
        other_participant = make_participant(other_zev, first="Other", last="Participant")

        context = _build_contract_context(other_participant)

        self.assertEqual(context["tr"]["payment_terms_unit"], "Tage ab Rechnungsdatum")
