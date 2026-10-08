"""Source endpoints of SPEC-2026-supplementary-energy-data §5."""

from datetime import date, datetime, timezone as dt_timezone
from unittest import mock

from django.test import override_settings

from audit.models import AuditEvent
from metering.models import SupplementaryReading, SupplementarySource, SupplementaryStatus
from metering.supplementary import providers
from metering.supplementary.testing import (
    INTEGRATION_KEY,
    SOURCES_URL,
    SupplementaryApiTestCase,
    client_for,
    enable_feature,
)
from testing import factories
from zev.models import AllocationMode, MeteringPointType


class FakeSolarManager:
    """Stands in for the vendor: records what it was asked and rotates the token."""

    def __init__(self):
        self.calls = []
        self.error = None

    def verify(self, external_id, credential):
        self.calls.append((external_id, credential))
        if self.error:
            raise self.error
        return f"rotated-{credential}"


def solar_payload(point, **extra):
    return {
        "metering_point": str(point.pk), "provider": "solar_manager", "external_id": "ABC123",
        "api_key": "the-participants-key", "consent": True, **extra,
    }


class FeatureFlagTests(SupplementaryApiTestCase):
    def test_everything_is_404_while_the_flag_is_off(self):
        enable_feature(False)
        for method, url in (("get", SOURCES_URL), ("post", SOURCES_URL)):
            response = getattr(client_for(self.holder_user), method)(url)
            self.assertEqual(response.status_code, 404, (method, url))


class CreatePushSourceTests(SupplementaryApiTestCase):
    def test_holder_creates_a_push_source_and_gets_the_token_once(self):
        response = self.create_push_source()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["push_token"].startswith("ozs_"))
        self.assertEqual(body["participant"], str(self.holder.pk))
        self.assertEqual(body["status"], "pending")
        self.assertFalse(body["has_credential"])
        self.assertEqual(body["push_token_prefix"], body["push_token"].split("_")[1])
        self.assertNotIn("push_token_hash", body)

        detail = client_for(self.holder_user).get(f"{SOURCES_URL}{body['id']}/").json()
        self.assertNotIn("push_token", detail)

    def test_consent_is_required(self):
        response = self.create_push_source(consent=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn("consent", response.json())
        self.assertEqual(SupplementarySource.objects.count(), 0)

    def test_an_unflagged_metering_point_is_refused(self):
        plain = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL)
        factories.MeteringPointAssignmentFactory(metering_point=plain, participant=self.holder, valid_from=date(2025, 1, 1))
        response = self.create_push_source(point=plain)
        self.assertEqual(response.status_code, 400)
        self.assertIn("metering_point", response.json())

    def test_a_second_source_for_the_same_metering_point_is_refused(self):
        self.assertEqual(self.create_push_source().status_code, 201)
        response = self.create_push_source()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SupplementarySource.objects.count(), 1)

    def test_a_manager_cannot_create_a_source(self):
        response = self.create_push_source(as_user=self.manager)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SupplementarySource.objects.count(), 0)

    def test_a_participant_who_does_not_hold_the_meter_cannot_create_one(self):
        # They cannot see the meter either, so it is "not found" rather than "forbidden".
        response = self.create_push_source(as_user=self.other_user)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SupplementarySource.objects.count(), 0)

    def test_a_community_holder_cannot_create_one(self):
        self.assignment.allocation_mode = AllocationMode.COMMUNITY
        self.assignment.save()
        self.assertEqual(self.create_push_source().status_code, 403)

    def test_someone_with_no_relation_cannot_even_name_the_metering_point(self):
        response = self.create_push_source(as_user=self.stranger)
        self.assertEqual(response.status_code, 400)  # "Invalid pk": existence is not revealed
        self.assertIn("metering_point", response.json())

    def test_an_admin_creates_on_behalf_of_the_holder(self):
        response = self.create_push_source(as_user=self.admin, participant=str(self.holder.pk))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["participant"], str(self.holder.pk))

    def test_an_admin_must_name_a_participant_who_holds_the_meter(self):
        missing = self.create_push_source(as_user=self.admin)
        self.assertEqual(missing.status_code, 400)
        self.assertIn("participant", missing.json())
        wrong = self.create_push_source(as_user=self.admin, participant=str(self.other.pk))
        self.assertEqual(wrong.status_code, 400)

    def test_a_push_source_takes_no_external_id_or_key(self):
        self.assertEqual(self.create_push_source(external_id="ABC123").status_code, 400)
        self.assertEqual(self.create_push_source(api_key="x").status_code, 400)

    def test_a_disabled_zev_refuses_a_non_admin(self):
        from django.utils import timezone

        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        self.assertEqual(self.create_push_source().status_code, 400)

    def test_creation_is_audited_without_the_token(self):
        body = self.create_push_source().json()
        event = AuditEvent.objects.get(action_type="supplementary_source.create")
        self.assertEqual(event.target_id, body["id"])
        self.assertEqual(event.zev_id, self.zev.pk)
        self.assertNotIn(body["push_token"], str(event.metadata_json) + event.summary)


class CreateSolarManagerSourceTests(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.vendor = FakeSolarManager()
        patcher = mock.patch.dict(providers.PROVIDERS, {"solar_manager": self.vendor})
        patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, **extra):
        return client_for(self.holder_user).post(SOURCES_URL, solar_payload(self.point, **extra), format="json")

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
    def test_the_key_is_verified_and_the_rotated_credential_is_stored_encrypted(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.vendor.calls, [("ABC123", "the-participants-key")])
        body = response.json()
        self.assertTrue(body["has_credential"])
        self.assertNotIn("api_key", body)
        self.assertNotIn("push_token", body)
        source = SupplementarySource.objects.get()
        self.assertEqual(source.credential, "rotated-the-participants-key")
        self.assertNotIn(b"the-participants-key", bytes(source.credential_encrypted))
        self.assertNotIn("the-participants-key", response.content.decode())

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[])
    def test_without_an_encryption_key_the_answer_is_503_naming_the_setting(self):
        response = self.create()
        self.assertEqual(response.status_code, 503)
        self.assertIn("INTEGRATION_ENCRYPTION_KEYS", response.json()["detail"])
        self.assertEqual(SupplementarySource.objects.count(), 0)
        self.assertEqual(self.vendor.calls, [])

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
    def test_a_rejected_key_saves_nothing(self):
        self.vendor.error = providers.ProviderAuthError("Solar Manager rejected this API key.")
        response = self.create()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["api_key"], ["Solar Manager rejected this API key."])
        self.assertEqual(SupplementarySource.objects.count(), 0)

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
    def test_an_unreachable_vendor_saves_nothing(self):
        self.vendor.error = providers.ProviderError("Solar Manager could not be reached.")
        self.assertEqual(self.create().status_code, 400)
        self.assertEqual(SupplementarySource.objects.count(), 0)

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
    def test_id_and_key_are_required(self):
        payload = solar_payload(self.point)
        del payload["api_key"]
        response = client_for(self.holder_user).post(SOURCES_URL, payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("api_key", response.json())

    def test_a_provider_that_is_not_registered_cannot_be_connected(self):
        with mock.patch.dict(providers.PROVIDERS, clear=True):
            response = self.create()
        self.assertEqual(response.status_code, 400)
        self.assertIn("provider", response.json())

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
    def test_the_key_never_reaches_the_audit_log(self):
        self.create()
        events = AuditEvent.objects.filter(action_type="supplementary_source.create")
        self.assertEqual(events.count(), 1)
        self.assertNotIn("the-participants-key", str(list(events.values())))


class ReadScopingTests(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.source_id = self.create_push_source().json()["id"]

    def ids(self, user):
        response = client_for(user).get(SOURCES_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        return [row["id"] for row in (data["results"] if isinstance(data, dict) else data)]

    def test_owner_manager_viewer_and_admin_see_it(self):
        for user in (self.holder_user, self.manager, self.viewer, self.admin):
            self.assertEqual(self.ids(user), [self.source_id], user.username)

    def test_another_participant_and_a_stranger_do_not(self):
        for user in (self.other_user, self.stranger):
            self.assertEqual(self.ids(user), [], user.username)
            self.assertEqual(client_for(user).get(f"{SOURCES_URL}{self.source_id}/").status_code, 404)

    def test_another_zevs_manager_does_not(self):
        other_manager = factories.OwnerFactory()
        factories.ZevFactory(owner=other_manager)
        self.assertEqual(self.ids(other_manager), [])

    def test_no_secret_is_ever_serialized(self):
        row = client_for(self.manager).get(f"{SOURCES_URL}{self.source_id}/").json()
        for forbidden in ("credential_encrypted", "push_token_hash", "push_token", "api_key"):
            self.assertNotIn(forbidden, row)

    def test_filter_by_metering_point(self):
        response = client_for(self.admin).get(SOURCES_URL, {"metering_point": str(self.point.pk)})
        self.assertEqual(len(response.json()["results"] if isinstance(response.json(), dict) else response.json()), 1)


class UpdateAndRemoveTests(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.source = SupplementarySource.objects.get(pk=self.create_push_source().json()["id"])
        self.url = f"{SOURCES_URL}{self.source.pk}/"
        SupplementaryReading.objects.create(
            source=self.source, metering_point=self.point, timestamp=datetime(2026, 7, 1, tzinfo=dt_timezone.utc),
            consumption_kwh=1, production_kwh=1, import_kwh=0, export_kwh=0,
        )

    def test_owner_edits_the_label_and_it_is_audited_with_a_diff(self):
        response = client_for(self.holder_user).patch(self.url, {"label": "New name"}, format="json")
        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.get(action_type="supplementary_source.update")
        self.assertEqual(event.changes_json["label"]["after"], "New name")
        self.assertIs(event.metadata_json["credential_changed"], False)

    def test_manager_can_switch_it_off_but_nothing_else(self):
        client = client_for(self.manager)
        self.assertEqual(client.patch(self.url, {"label": "Mine now"}, format="json").status_code, 403)
        off = client.patch(self.url, {"enabled": False}, format="json")
        self.assertEqual(off.status_code, 200)
        self.assertEqual(off.json()["status"], "disabled")
        self.assertEqual(client.patch(self.url, {"enabled": True}, format="json").json()["status"], "pending")

    def test_viewer_and_other_participants_cannot_write(self):
        self.assertEqual(client_for(self.viewer).patch(self.url, {"enabled": False}, format="json").status_code, 403)
        self.assertEqual(client_for(self.viewer).delete(self.url).status_code, 403)
        self.assertEqual(client_for(self.other_user).patch(self.url, {"enabled": False}, format="json").status_code, 404)

    def test_the_participant_cannot_be_changed(self):
        response = client_for(self.admin).patch(self.url, {"participant": str(self.other.pk)}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_the_provider_cannot_be_changed(self):
        response = client_for(self.holder_user).patch(self.url, {"provider": "solar_manager"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_disconnect_wipes_the_token_but_keeps_readings(self):
        response = client_for(self.manager).post(f"{self.url}disconnect/")
        self.assertEqual(response.status_code, 200)
        self.source.refresh_from_db()
        self.assertFalse(self.source.enabled)
        self.assertIsNone(self.source.push_token_prefix)
        self.assertEqual(self.source.readings.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action_type="supplementary_source.disconnect").exists())

    def test_purge_everything_resets_coverage(self):
        self.source.covers_from = datetime(2026, 7, 1, tzinfo=dt_timezone.utc)
        self.source.synced_through = datetime(2026, 7, 1, 0, 15, tzinfo=dt_timezone.utc)
        self.source.save()
        response = client_for(self.holder_user).post(f"{self.url}purge/", {}, format="json")
        self.assertEqual(response.json(), {"deleted": 1})
        self.source.refresh_from_db()
        self.assertIsNone(self.source.covers_from)
        self.assertIsNone(self.source.synced_through)

    def test_purge_a_range_of_civil_dates(self):
        SupplementaryReading.objects.create(
            source=self.source, metering_point=self.point, timestamp=datetime(2026, 7, 5, 10, tzinfo=dt_timezone.utc),
            consumption_kwh=1, production_kwh=1, import_kwh=0, export_kwh=0,
        )
        response = client_for(self.manager).post(
            f"{self.url}purge/", {"date_from": "2026-07-04", "date_to": "2026-07-06"}, format="json"
        )
        self.assertEqual(response.json(), {"deleted": 1})
        self.assertEqual(self.source.readings.count(), 1)

    def test_purge_rejects_a_backwards_range(self):
        response = client_for(self.manager).post(
            f"{self.url}purge/", {"date_from": "2026-07-06", "date_to": "2026-07-04"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_removes_the_source_and_its_readings(self):
        response = client_for(self.manager).delete(self.url)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(SupplementarySource.objects.count(), 0)
        self.assertEqual(SupplementaryReading.objects.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action_type="supplementary_source.delete").exists())

    def test_rotating_the_push_token_replaces_it_and_is_owner_only(self):
        old_prefix = self.source.push_token_prefix
        self.assertEqual(client_for(self.manager).post(f"{self.url}rotate-push-token/").status_code, 403)
        response = client_for(self.holder_user).post(f"{self.url}rotate-push-token/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["push_token"].startswith("ozs_"))
        self.source.refresh_from_db()
        self.assertNotEqual(self.source.push_token_prefix, old_prefix)

    def test_a_disabled_zev_is_read_only_for_a_non_admin(self):
        from django.utils import timezone

        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])
        # A disabled ZEV disappears for its participants and is read-only for its managers.
        self.assertEqual(client_for(self.holder_user).patch(self.url, {"label": "x"}, format="json").status_code, 404)
        for call in (
            lambda c: c.patch(self.url, {"enabled": False}, format="json"),
            lambda c: c.delete(self.url),
            lambda c: c.post(f"{self.url}disconnect/"),
        ):
            self.assertEqual(call(client_for(self.manager)).status_code, 400)
        self.assertEqual(client_for(self.manager).get(self.url).status_code, 200)
        self.assertEqual(client_for(self.admin).patch(self.url, {"label": "x"}, format="json").status_code, 200)

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
    def test_replacing_the_key_verifies_it_resets_the_status_and_is_audited(self):
        point = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        factories.MeteringPointAssignmentFactory(metering_point=point, participant=self.holder, valid_from=date(2025, 1, 1))
        vendor = FakeSolarManager()
        with mock.patch.dict(providers.PROVIDERS, {"solar_manager": vendor}):
            created = client_for(self.holder_user).post(SOURCES_URL, solar_payload(point), format="json").json()
            source = SupplementarySource.objects.get(pk=created["id"])
            source.mark_reconnect_required("The key was rejected.")
            source.save()
            response = client_for(self.holder_user).patch(
                f"{SOURCES_URL}{source.pk}/", {"api_key": "a-new-key"}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)
        source.refresh_from_db()
        self.assertEqual(source.credential, "rotated-a-new-key")
        self.assertEqual(source.status, SupplementaryStatus.PENDING)
        self.assertEqual(source.last_error, "")
        event = AuditEvent.objects.filter(action_type="supplementary_source.update").latest("created_at")
        self.assertIs(event.metadata_json["credential_changed"], True)
        self.assertNotIn("a-new-key", str(list(AuditEvent.objects.values())))

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
    def test_changing_the_solar_manager_id_needs_the_key_again(self):
        point = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        factories.MeteringPointAssignmentFactory(metering_point=point, participant=self.holder, valid_from=date(2025, 1, 1))
        with mock.patch.dict(providers.PROVIDERS, {"solar_manager": FakeSolarManager()}):
            created = client_for(self.holder_user).post(SOURCES_URL, solar_payload(point), format="json").json()
            response = client_for(self.holder_user).patch(
                f"{SOURCES_URL}{created['id']}/", {"external_id": "NEW999"}, format="json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("api_key", response.json())


class ClearingTheFlagTests(SupplementaryApiTestCase):
    def test_the_metering_point_flag_cannot_be_cleared_while_a_source_exists(self):
        self.create_push_source()
        response = client_for(self.admin).patch(
            f"/api/v1/zev/metering-points/{self.point.pk}/", {"has_behind_meter_generation": False}, format="json"
        )
        self.assertEqual(response.status_code, 400)
