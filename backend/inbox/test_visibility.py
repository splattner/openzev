"""Who sees which delivered document (SPEC-2026-11-participant-document-inbox §3, §5.1)."""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from inbox import services
from inbox.models import DocumentKind
from inbox.test_helpers import PDF, deliver_operator_document
from invoices.test_helpers import make_invoice, make_participant, make_zev
from testing.helpers import authenticate as auth, make_user
from zev.models import ZevAccessGrant, ZevAccessRole

DOCS = "/api/v1/inbox/documents/"


def ids(response):
    assert response.status_code == 200, response.content
    return {row["id"] for row in response.json()["results"]}


class InboxVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("inbox_vis_owner", UserRole.USER)
        self.tenant = make_user("inbox_vis_tenant", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev, user=self.tenant)
        self.neighbour = make_participant(self.zev, first="Max", last="Muster")
        self.mine = deliver_operator_document(self.participant, "Mine")
        self.theirs = deliver_operator_document(self.neighbour, "Theirs")

    def test_participant_sees_only_own_rows(self):
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.mine.pk)})
        self.assertEqual(self.client.get(f"{DOCS}{self.theirs.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"{DOCS}{self.theirs.pk}/file/").status_code, 404)

    def test_account_with_two_participant_rows_sees_both(self):
        other_zev = make_zev(make_user("inbox_vis_owner2", UserRole.USER), "Second")
        second = make_participant(other_zev, user=self.tenant)
        in_second = deliver_operator_document(second, "Elsewhere")
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.mine.pk), str(in_second.pk)})
        self.assertEqual(ids(self.client.get(DOCS, {"zev_id": str(other_zev.pk)})), {str(in_second.pk)})

    def test_row_stays_after_valid_to_passes(self):
        self.participant.valid_to = date.today() - timedelta(days=30)
        self.participant.save()
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.mine.pk)})
        self.assertEqual(self.client.get(f"{DOCS}{self.mine.pk}/file/").status_code, 200)

    def test_row_stays_when_zev_is_disabled(self):
        self.zev.disabled_at = timezone.now()
        self.zev.save()
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.mine.pk)})

    def test_other_viewsets_still_hide_a_disabled_zev(self):
        invoice = make_invoice(self.zev, self.participant)
        type(invoice).objects.filter(pk=invoice.pk).update(sent_at=timezone.now())
        self.zev.disabled_at = timezone.now()
        self.zev.save()
        auth(self.client, self.tenant)
        response = self.client.get("/api/v1/invoices/invoices/")
        self.assertEqual(response.json()["results"], [])

    def test_row_appears_when_account_is_linked_later(self):
        late = make_user("inbox_vis_late", UserRole.USER)
        auth(self.client, late)
        self.assertEqual(ids(self.client.get(DOCS)), set())
        self.neighbour.user = late
        self.neighbour.save()
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.theirs.pk)})

    def test_unlinking_the_account_removes_access(self):
        self.participant.user = None
        self.participant.save()
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS)), set())

    def test_participant_cannot_see_withdrawn_but_manager_can(self):
        services.withdraw(self.mine, self.owner)
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS)), set())
        self.assertEqual(self.client.get(f"{DOCS}{self.mine.pk}/").status_code, 404)
        auth(self.client, self.owner)
        self.assertNotIn(str(self.mine.pk), ids(self.client.get(DOCS)))
        self.assertIn(str(self.mine.pk), ids(self.client.get(DOCS, {"include_withdrawn": "true"})))
        detail = self.client.get(f"{DOCS}{self.mine.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIsNotNone(detail.json()["withdrawn_at"])

    def test_participant_include_withdrawn_does_not_widen(self):
        services.withdraw(self.mine, self.owner)
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS, {"include_withdrawn": "true"})), set())

    def test_superseded_row_visible_with_link(self):
        new = deliver_operator_document(self.participant, "Newer")
        services.supersede(self.mine, new)
        auth(self.client, self.tenant)
        rows = {row["id"]: row for row in self.client.get(DOCS).json()["results"]}
        self.assertEqual(rows[str(self.mine.pk)]["superseded_by"], str(new.pk))
        self.assertIsNotNone(rows[str(self.mine.pk)]["superseded_at"])
        self.assertEqual(ids(self.client.get(DOCS, {"include_superseded": "false"})), {str(new.pk)})

    def test_manager_outbox_covers_the_zev_and_filters(self):
        auth(self.client, self.owner)
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.mine.pk), str(self.theirs.pk)})
        self.assertEqual(
            ids(self.client.get(DOCS, {"participant_id": str(self.neighbour.pk)})), {str(self.theirs.pk)}
        )
        self.assertEqual(ids(self.client.get(DOCS, {"kind": "invoice"})), set())

    def test_viewer_reads_but_cannot_write(self):
        viewer = make_user("inbox_vis_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER)
        auth(self.client, viewer)
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.mine.pk), str(self.theirs.pk)})
        self.assertEqual(self.client.post(DOCS, {}).status_code, 405)

    def test_manager_of_another_zev_sees_nothing(self):
        stranger = make_user("inbox_vis_stranger", UserRole.USER)
        make_zev(stranger, "Elsewhere")
        auth(self.client, stranger)
        self.assertEqual(ids(self.client.get(DOCS)), set())
        self.assertEqual(self.client.get(f"{DOCS}{self.mine.pk}/").status_code, 404)

    def test_admin_sees_all(self):
        admin = make_user("inbox_vis_admin", UserRole.ADMIN)
        auth(self.client, admin)
        self.assertEqual(ids(self.client.get(DOCS)), {str(self.mine.pk), str(self.theirs.pk)})

    def test_anonymous_is_refused(self):
        self.assertEqual(self.client.get(DOCS).status_code, 401)

    def test_bad_filters_are_validation_errors(self):
        auth(self.client, self.owner)
        for params in ({"kind": "nope"}, {"year": "abc"}, {"participant_id": "x"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(DOCS, params).status_code, 400)

    def test_year_filter_matches_period_or_delivery_year(self):
        statement, _ = services.deliver(
            participant=self.participant, kind=DocumentKind.ANNUAL_STATEMENT, title="S 2024", body=PDF,
            period=(date(2024, 1, 1), date(2024, 12, 31)),
        )
        auth(self.client, self.tenant)
        self.assertEqual(ids(self.client.get(DOCS, {"year": 2024})), {str(statement.pk)})
        self.assertEqual(ids(self.client.get(DOCS, {"year": timezone.localdate().year})), {str(self.mine.pk)})

    def test_download_headers(self):
        auth(self.client, self.tenant)
        response = self.client.get(f"{DOCS}{self.mine.pk}/file/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_contract_download_serves_the_issue_bytes(self):
        from inbox.test_helpers import make_contract_issue

        issue = make_contract_issue(self.participant, self.owner)
        document, _ = services.deliver(
            participant=self.participant, kind=DocumentKind.CONTRACT, title="C-1", contract_issue=issue,
            document_number="C-1",
        )
        auth(self.client, self.tenant)
        response = self.client.get(f"{DOCS}{document.pk}/file/")
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-contract")
