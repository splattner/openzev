"""Models of SPEC-2026-supplementary-energy-data §4.1 and §4.2."""

from datetime import datetime, timezone
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from cryptography.fernet import Fernet

from metering.models import (
    SupplementaryProvider,
    SupplementaryReading,
    SupplementarySource,
    SupplementaryStatus,
)
from rest_framework.test import APIClient
from testing import factories
from testing.helpers import authenticate, make_user
from accounts.models import UserRole
from zev.models import MeteringPointType

KEY = Fernet.generate_key().decode()


def flagged_point(zev, **kwargs):
    return factories.MeteringPointFactory(
        zev=zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True, **kwargs
    )


def make_source(participant, point, **kwargs):
    defaults = {"provider": SupplementaryProvider.PUSH}
    defaults.update(kwargs)
    return SupplementarySource.objects.create(metering_point=point, participant=participant, **defaults)


class SupplementaryModelTests(TestCase):
    def setUp(self):
        self.zev = factories.ZevFactory()
        self.participant = factories.ParticipantFactory(zev=self.zev)
        self.point = flagged_point(self.zev)

    def test_source_requires_flagged_metering_point(self):
        plain = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL)
        source = SupplementarySource(metering_point=plain, participant=self.participant, provider="push")
        with self.assertRaises(ValidationError) as ctx:
            source.full_clean()
        self.assertIn("metering_point", ctx.exception.message_dict)

    def test_source_participant_must_share_zev(self):
        stranger = factories.ParticipantFactory()
        source = SupplementarySource(metering_point=self.point, participant=stranger, provider="push")
        with self.assertRaises(ValidationError) as ctx:
            source.full_clean()
        self.assertIn("participant", ctx.exception.message_dict)

    def test_external_id_rules_per_provider(self):
        solar = SupplementarySource(
            metering_point=self.point, participant=self.participant, provider="solar_manager", external_id="a b"
        )
        with self.assertRaises(ValidationError) as ctx:
            solar.full_clean()
        self.assertIn("external_id", ctx.exception.message_dict)
        solar.external_id = "00000000F1584HB3"
        solar.full_clean()

        push = SupplementarySource(
            metering_point=self.point, participant=self.participant, provider="push", external_id="X123"
        )
        with self.assertRaises(ValidationError) as ctx:
            push.full_clean()
        self.assertIn("external_id", ctx.exception.message_dict)

    def test_one_source_per_metering_point(self):
        make_source(self.participant, self.point)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_source(self.participant, self.point)

    def test_clearing_flag_blocked_while_source_exists(self):
        make_source(self.participant, self.point)
        point = type(self.point).objects.get(pk=self.point.pk)
        point.has_behind_meter_generation = False
        with self.assertRaises(ValidationError) as ctx:
            point.full_clean()
        self.assertEqual(
            ctx.exception.message_dict["has_behind_meter_generation"], ["Disconnect the energy data source first."]
        )

    def test_clearing_flag_blocked_through_the_api(self):
        make_source(self.participant, self.point)
        admin = make_user("sup_admin", UserRole.ADMIN)
        client = APIClient()
        authenticate(client, admin)
        response = client.patch(
            f"/api/v1/zev/metering-points/{self.point.pk}/", {"has_behind_meter_generation": False}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("has_behind_meter_generation", response.json())
        self.point.refresh_from_db()
        self.assertTrue(self.point.has_behind_meter_generation)

    def test_flag_can_be_cleared_once_the_source_is_gone(self):
        make_source(self.participant, self.point).delete()
        admin = make_user("sup_admin2", UserRole.ADMIN)
        client = APIClient()
        authenticate(client, admin)
        response = client.patch(
            f"/api/v1/zev/metering-points/{self.point.pk}/", {"has_behind_meter_generation": False}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_reading_unique_per_metering_point_and_timestamp(self):
        source = make_source(self.participant, self.point)
        ts = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        values = dict(consumption_kwh=1, production_kwh=2, import_kwh=0, export_kwh=1)
        SupplementaryReading.objects.create(source=source, metering_point=self.point, timestamp=ts, **values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupplementaryReading.objects.create(source=source, metering_point=self.point, timestamp=ts, **values)

    def test_reading_rejects_negative_values(self):
        source = make_source(self.participant, self.point)
        ts = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        for field in ("consumption_kwh", "production_kwh", "import_kwh", "export_kwh"):
            values = dict(consumption_kwh=1, production_kwh=1, import_kwh=1, export_kwh=1)
            values[field] = Decimal("-0.0001")
            with self.subTest(field), self.assertRaises(IntegrityError), transaction.atomic():
                SupplementaryReading.objects.create(
                    source=source, metering_point=self.point, timestamp=ts, **values
                )

    def test_deleting_a_source_deletes_its_readings(self):
        source = make_source(self.participant, self.point)
        SupplementaryReading.objects.create(
            source=source, metering_point=self.point, timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
            consumption_kwh=1, production_kwh=1, import_kwh=0, export_kwh=0,
        )
        source.delete()
        self.assertEqual(SupplementaryReading.objects.count(), 0)

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
    def test_credential_roundtrip_stores_only_ciphertext(self):
        source = make_source(self.participant, self.point, provider="solar_manager", external_id="ABC123")
        self.assertFalse(source.has_credential)
        self.assertEqual(source.credential, "")
        source.set_credential("refresh-token-123")
        source.save()
        source.refresh_from_db()
        self.assertTrue(source.has_credential)
        self.assertNotIn(b"refresh-token-123", bytes(source.credential_encrypted))
        self.assertEqual(source.credential, "refresh-token-123")

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[])
    def test_set_credential_without_key_raises(self):
        source = make_source(self.participant, self.point, provider="solar_manager", external_id="ABC123")
        with self.assertRaises(ValidationError) as ctx:
            source.set_credential("refresh-token-123")
        self.assertIn("INTEGRATION_ENCRYPTION_KEYS", str(ctx.exception))
        self.assertFalse(source.has_credential)

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
    def test_status_transitions(self):
        source = make_source(self.participant, self.point, provider="solar_manager", external_id="ABC123")
        self.assertEqual(source.status, SupplementaryStatus.PENDING)

        source.mark_ok()
        self.assertEqual((source.status, source.last_error), (SupplementaryStatus.OK, ""))
        self.assertIsNotNone(source.last_success_at)

        source.mark_error("Vendor unreachable.")
        self.assertEqual(source.status, SupplementaryStatus.ERROR)
        self.assertEqual(source.last_error, "Vendor unreachable.")

        source.mark_reconnect_required("The key was rejected.")
        self.assertEqual(source.status, SupplementaryStatus.RECONNECT_REQUIRED)

        source.mark_ok()
        self.assertEqual(source.status, SupplementaryStatus.OK)

        source.enabled = False
        source.save()
        source.refresh_from_db()
        self.assertEqual(source.status, SupplementaryStatus.DISABLED)

        source.enabled = True
        source.save(update_fields=["enabled"])
        source.refresh_from_db()
        self.assertEqual(source.status, SupplementaryStatus.PENDING)

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
    def test_disconnect_disables_and_wipes_secrets_but_keeps_readings(self):
        source = make_source(
            self.participant, self.point, provider="solar_manager", external_id="ABC123",
            push_token_prefix="abc", push_token_hash="h" * 64,
        )
        source.set_credential("refresh-token-123")
        source.save()
        SupplementaryReading.objects.create(
            source=source, metering_point=self.point, timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
            consumption_kwh=1, production_kwh=1, import_kwh=0, export_kwh=0,
        )

        source.disconnect()
        source.save()
        source.refresh_from_db()

        self.assertEqual(source.status, SupplementaryStatus.DISABLED)
        self.assertFalse(source.enabled)
        self.assertFalse(source.has_credential)
        self.assertIsNone(source.push_token_prefix)
        self.assertEqual(source.push_token_hash, "")
        self.assertEqual(SupplementaryReading.objects.count(), 1)

    def test_last_error_is_truncated(self):
        source = make_source(self.participant, self.point)
        source.mark_error("x" * 900)
        self.assertEqual(len(source.last_error), 500)
