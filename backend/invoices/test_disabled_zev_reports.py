"""Explicit report resolvers must hide disabled participant memberships."""

from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from testing.factories import ParticipantFactory, ZevFactory
from testing.helpers import authenticate
from zev.models import ZevAccessGrant


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("role", ["participant", "manager", "viewer", "admin", "manager_elsewhere"])
@pytest.mark.parametrize("report, generator", [
    ("annual-statement", "generate_annual_statement_pdf"),
    ("financial-summary", "generate_financial_summary_pdf"),
])
def test_report_visibility(zev, participant, participant_user, admin_user, disabled, role, report, generator):
    participant.user = participant_user
    participant.save()
    zev.disabled_at = timezone.now() if disabled else None
    zev.save()
    if role in ("manager", "viewer"):
        ZevAccessGrant.objects.create(zev=zev, user=participant_user, role=role)
    if role == "manager_elsewhere":
        ZevFactory(owner=participant_user)
    client = APIClient()
    authenticate(client, admin_user if role == "admin" else participant_user)

    with patch(f"invoices.views_reports.{generator}", return_value=b"%PDF") as render:
        response = client.get(f"/api/v1/invoices/invoices/{report}/", {
            "year": "2026", "zev_id": str(zev.pk), "participant_id": str(participant.pk),
        })

    expected = 200
    if disabled and role in ("participant", "manager_elsewhere"):
        expected = 403 if role == "manager_elsewhere" else 404
    assert response.status_code == expected, response.content
    assert render.called == (expected == 200)


@pytest.mark.parametrize("report, generator", [
    ("annual-statement", "generate_annual_statement_pdf"),
    ("financial-summary", "generate_financial_summary_pdf"),
])
def test_self_service_without_ids_returns_after_reenable(zev, participant, participant_user, participant_client, report, generator):
    participant.user = participant_user
    participant.save()
    zev.disabled_at = timezone.now()
    zev.save()
    with patch(f"invoices.views_reports.{generator}", return_value=b"%PDF") as render:
        url = f"/api/v1/invoices/invoices/{report}/"
        response = participant_client.get(url, {"year": "2026"})
        assert response.status_code == 404, response.content
        render.assert_not_called()
        zev.disabled_at = None
        zev.save()
        assert participant_client.get(url, {"year": "2026"}).status_code == 200
        assert render.call_count == 1
        assert participant in render.call_args.args
        assert zev in render.call_args.args


@pytest.mark.parametrize("selection", ["disabled", "enabled", "omitted", "foreign", "unknown", "malformed"])
@pytest.mark.parametrize("report, generator", [
    ("annual-statement", "generate_annual_statement_pdf"),
    ("financial-summary", "generate_financial_summary_pdf"),
])
def test_explicit_zev_never_falls_back_to_another_membership(
    zev, participant, participant_user, participant_client, selection, report, generator,
):
    participant.user = participant_user
    participant.save()
    zev.disabled_at = timezone.now()
    zev.save()
    enabled = ZevFactory()
    own = ParticipantFactory(zev=enabled, user=participant_user)
    selected_id = {
        "disabled": str(zev.pk), "enabled": str(enabled.pk), "omitted": None,
        "foreign": str(ZevFactory().pk), "unknown": "00000000-0000-0000-0000-000000000000",
        "malformed": "not-a-uuid",
    }[selection]
    params = {"year": "2026"}
    if selected_id is not None:
        params["zev_id"] = selected_id

    with patch(f"invoices.views_reports.{generator}", return_value=b"%PDF") as render:
        response = participant_client.get(f"/api/v1/invoices/invoices/{report}/", params)

    if selection in ("enabled", "omitted"):
        assert response.status_code == 200, response.content
        if report == "annual-statement":
            render.assert_called_once_with(own, enabled, 2026, sent_only=True)
        else:
            render.assert_called_once_with(enabled, own, 2026)
    else:
        assert response.status_code == 404, response.content
        render.assert_not_called()
