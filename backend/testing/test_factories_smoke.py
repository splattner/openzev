"""Smoke tests for the shared factories and conftest fixtures.

These guard the test infrastructure itself: if a factory's defaults drift out of
sync with a model constraint, these fail fast with a clear message.
"""

from __future__ import annotations

import pytest

from invoices.models import Invoice
from tariffs.models import PeriodType
from testing import factories
from testing.helpers import authenticate

pytestmark = pytest.mark.django_db


def test_zev_factory_creates_owner():
    zev = factories.ZevFactory()
    assert zev.owner_id is not None
    # Owning a ZEV makes its owner a manager through the owner grant (#761).
    from zev import access

    assert access.can_manage(zev.owner, zev)


def test_participant_factory_shares_zev():
    participant = factories.ParticipantFactory()
    assert participant.zev_id is not None
    assert participant.valid_from == factories.DEFAULT_VALID_FROM


def test_assignment_for_keeps_same_zev():
    participant = factories.ParticipantFactory()
    assignment = factories.assignment_for(participant)
    assert assignment.metering_point.zev_id == participant.zev_id
    assert assignment.participant_id == participant.id


def test_flat_tariff_has_single_flat_period():
    zev = factories.ZevFactory()
    tariff = factories.flat_tariff(zev, price="0.25000")
    periods = list(tariff.periods.all())
    assert len(periods) == 1
    assert periods[0].period_type == PeriodType.FLAT
    assert str(periods[0].price_chf_per_kwh) == "0.25000"


def test_invoice_factory_participant_matches_zev():
    invoice = factories.InvoiceFactory()
    assert invoice.participant.zev_id == invoice.zev_id
    assert Invoice.objects.count() == 1


def test_authenticate_helper_sets_bearer_header():
    from rest_framework.test import APIClient

    user = factories.AdminFactory()
    client = APIClient()
    authenticate(client, user)
    # The credentials are stored on the client's underlying handler.
    assert client._credentials["HTTP_AUTHORIZATION"].startswith("Bearer ")
