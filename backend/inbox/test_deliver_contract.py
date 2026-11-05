from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from inbox.models import DeliveredDocument, DocumentKind
from inbox.test_helpers import make_contract_issue
from invoices.test_helpers import make_participant, make_zev
from testing.helpers import authenticate, make_user

URL = "/api/v1/inbox/documents/deliver-contract/"


class DeliverContractTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_ct_owner", UserRole.USER)
        self.account = make_user("inbox_ct_participant", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev, user=self.account)
        self.issue = make_contract_issue(self.participant, self.owner)

    def _post(self, user, issue=None):
        client = APIClient()
        authenticate(client, user)
        return client.post(URL, {"contract_issue": str((issue or self.issue).pk)}, format="json")

    def test_issuing_a_contract_does_not_deliver_it(self):
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_manager_delivers_a_contract_by_reference_without_a_copy(self):
        response = self._post(self.owner)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual((body["delivered"], body["without_account"]), (1, 0))
        document = DeliveredDocument.objects.get()
        self.assertEqual(document.kind, DocumentKind.CONTRACT)
        self.assertEqual(document.contract_issue_id, self.issue.pk)
        self.assertEqual(document.file.name, "")
        self.assertEqual(document.delivered_by, self.owner)
        self.assertEqual(document.document_number, self.issue.document_number)
        self.assertEqual(str(document.batch_id), body["batch_id"])
        self.assertEqual(body["documents"][0]["id"], str(document.pk))

    def test_the_participant_can_open_the_delivered_contract(self):
        self._post(self.owner)
        document = DeliveredDocument.objects.get()
        client = APIClient()
        authenticate(client, self.account)

        response = client.get(f"/api/v1/inbox/documents/{document.pk}/file/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-contract")

    def test_a_participant_without_an_account_is_counted(self):
        unlinked = make_participant(self.zev, first="No", last="Account")
        issue = make_contract_issue(unlinked, self.owner)

        response = self._post(self.owner, issue)

        self.assertEqual(response.json()["without_account"], 1)

    def test_delivering_again_is_idempotent(self):
        self._post(self.owner)

        response = self._post(self.owner)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["delivered"], 0)
        self.assertEqual(DeliveredDocument.objects.count(), 1)

    def test_an_outdated_version_is_refused(self):
        newer = make_contract_issue(self.participant, self.owner, version=2)

        response = self._post(self.owner, self.issue)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(DeliveredDocument.objects.exists())
        self.assertEqual(self._post(self.owner, newer).status_code, 201)

    def test_naming_the_participant_delivers_their_latest_version(self):
        newer = make_contract_issue(self.participant, self.owner, version=2)
        client = APIClient()
        authenticate(client, self.owner)

        response = client.post(URL, {"participant": str(self.participant.pk)}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(DeliveredDocument.objects.get().contract_issue_id, newer.pk)

    def test_a_participant_without_an_issued_contract_gets_a_404(self):
        unissued = make_participant(self.zev, first="New", last="Comer")
        client = APIClient()
        authenticate(client, self.owner)

        response = client.post(URL, {"participant": str(unissued.pk)}, format="json")

        self.assertEqual(response.status_code, 404)

    def test_a_manager_of_another_zev_cannot_deliver_by_participant(self):
        stranger = make_user("inbox_ct_stranger2", UserRole.USER)
        make_zev(stranger, "Elsewhere")
        client = APIClient()
        authenticate(client, stranger)

        self.assertEqual(client.post(URL, {"participant": str(self.participant.pk)}, format="json").status_code, 404)

    def test_exactly_one_of_issue_and_participant_is_required(self):
        client = APIClient()
        authenticate(client, self.owner)

        self.assertEqual(client.post(URL, {}, format="json").status_code, 400)
        both = {"contract_issue": str(self.issue.pk), "participant": str(self.participant.pk)}
        self.assertEqual(client.post(URL, both, format="json").status_code, 400)

    def test_the_participant_cannot_deliver_their_own_contract(self):
        self.assertEqual(self._post(self.account).status_code, 404)
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_a_manager_of_another_zev_gets_a_404(self):
        stranger = make_user("inbox_ct_stranger", UserRole.USER)
        make_zev(stranger, "Elsewhere")

        self.assertEqual(self._post(stranger).status_code, 404)

    def test_an_unknown_issue_gets_the_same_404(self):
        client = APIClient()
        authenticate(client, self.owner)

        response = client.post(URL, {"contract_issue": "00000000-0000-0000-0000-000000000000"}, format="json")

        self.assertEqual(response.status_code, 404)

    def test_a_malformed_id_is_a_400(self):
        client = APIClient()
        authenticate(client, self.owner)

        self.assertEqual(client.post(URL, {"contract_issue": "nope"}, format="json").status_code, 400)

    def test_a_disabled_zev_refuses_a_manager_but_not_an_admin(self):
        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])

        self.assertEqual(self._post(self.owner).status_code, 400)
        admin = make_user("inbox_ct_admin", UserRole.ADMIN)
        self.assertEqual(self._post(admin).status_code, 201)

    def test_an_anonymous_caller_is_refused(self):
        response = APIClient().post(URL, {"contract_issue": str(self.issue.pk)}, format="json")

        self.assertIn(response.status_code, (401, 403))
