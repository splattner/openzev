"""The report endpoints serve managers and admins; a participant call is a 404 whatever the community state (#862)."""

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

    # A participant's statement and summary are issued to their inbox (#862), so a participant
    # call is a 404 here, also for an account that manages another community.
    expected = 200
    if role == "participant" or (role == "manager_elsewhere" and not disabled):
        expected = 404
    elif disabled and role == "manager_elsewhere":
        expected = 403
    assert response.status_code == expected, response.content
    assert render.called == (expected == 200)


@pytest.mark.parametrize("report, generator", [
    ("annual-statement", "generate_annual_statement_pdf"),
    ("financial-summary", "generate_financial_summary_pdf"),
])
def test_participant_is_refused_whether_the_community_is_enabled_or_not(
    zev, participant, participant_user, participant_client, report, generator,
):
    participant.user = participant_user
    participant.save()
    url = f"/api/v1/invoices/invoices/{report}/"
    with patch(f"invoices.views_reports.{generator}", return_value=b"%PDF") as render:
        for disabled_at in (timezone.now(), None):
            zev.disabled_at = disabled_at
            zev.save()
            assert participant_client.get(url, {"year": "2026"}).status_code == 404
        render.assert_not_called()


@pytest.mark.parametrize("selection", ["disabled", "enabled", "omitted", "foreign", "unknown", "malformed"])
@pytest.mark.parametrize("report, generator", [
    ("annual-statement", "generate_annual_statement_pdf"),
    ("financial-summary", "generate_financial_summary_pdf"),
])
def test_no_selection_gets_a_participant_a_report_from_another_membership(
    zev, participant, participant_user, participant_client, selection, report, generator,
):
    participant.user = participant_user
    participant.save()
    zev.disabled_at = timezone.now()
    zev.save()
    enabled = ZevFactory()
    ParticipantFactory(zev=enabled, user=participant_user)
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

    assert response.status_code == 404, response.content
    render.assert_not_called()
