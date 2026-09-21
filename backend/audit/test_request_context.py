"""Regression tests for audit request context and write failures."""

import uuid
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import SimpleTestCase, TestCase
from django.test.client import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.constants import REQUEST_ID_PATTERN
from audit.middleware import AuditRequestContextMiddleware
from audit.models import AuditActionCategory, AuditEvent
from audit.services import record_audit_event
from testing.helpers import authenticate as auth, make_user, trusted_proxies
from zev.models import Zev, Participant


class AuditApiTestCase(TestCase):
    """Shared admin/owner/ZEV/participant graph for audit API tests."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("audit_admin", UserRole.ADMIN)
        self.owner = make_user("audit_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="Audit ZEV", owner=self.owner)
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="Ada",
            last_name="Audit",
            email="ada@example.com",
            valid_from=timezone.localdate(),
        )
        auth(self.client, self.admin)

    def _patch_participant(self, data=None, **headers):
        return self.client.patch(
            f"/api/v1/zev/participants/{self.participant.id}/",
            data or {"first_name": "Ada2"},
            format="json",
            **headers,
        )

    def _create_participant(self, **overrides):
        payload = {
            "zev": str(self.zev.id),
            "first_name": "New",
            "last_name": "Participant",
            "email": "new@example.com",
            "valid_from": timezone.localdate().isoformat(),
        }
        payload.update(overrides)
        return self.client.post("/api/v1/zev/participants/", payload, format="json")

    def _latest_participant_event(self, action_type="participant.update"):
        return AuditEvent.objects.filter(
            action_type=action_type,
            target_id=str(self.participant.id),
        ).latest("created_at")


class AuditRequestIdValidationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_id_for(self, raw):
        extra = {} if raw is None else {"HTTP_X_REQUEST_ID": raw}
        request = self.factory.get("/", **extra)
        AuditRequestContextMiddleware(lambda req: None)(request)
        return request.audit_request_id

    def test_request_id_boundaries(self):
        cases = [
            (None, False),  # absent header -> server UUID
            ("", False),
            ("req-123_ABC.:-1", True),
            ("x" * 64, True),
            ("x" * 65, False),
            ("has space", False),
            ("bad<id>", False),
            ("abc\n", False),
        ]
        for raw, preserved in cases:
            with self.subTest(raw=raw):
                request_id = self._request_id_for(raw)
                if preserved:
                    self.assertEqual(request_id, raw)
                else:
                    self.assertNotEqual(request_id, raw)
                    self.assertTrue(REQUEST_ID_PATTERN.fullmatch(request_id))

    def test_long_user_agent_is_truncated(self):
        request = self.factory.get("/", HTTP_USER_AGENT="a" * 600)
        AuditRequestContextMiddleware(lambda req: None)(request)
        self.assertEqual(len(request.audit_user_agent), 500)


class AuditRequestContextTests(AuditApiTestCase):
    def _assert_server_uuid(self, request_id, rejected):
        self.assertNotEqual(request_id, rejected)
        self.assertTrue(REQUEST_ID_PATTERN.fullmatch(request_id))
        self.assertEqual(uuid.UUID(request_id).version, 4)

    def test_long_request_id_is_replaced_with_server_uuid(self):
        response = self._patch_participant(HTTP_X_REQUEST_ID="x" * 65)
        self.assertEqual(response.status_code, 200)
        self._assert_server_uuid(self._latest_participant_event().request_id, "x" * 65)

    def test_missing_request_id_generates_server_uuid(self):
        response = self._patch_participant()
        self.assertEqual(response.status_code, 200)
        event = self._latest_participant_event()
        self.assertTrue(REQUEST_ID_PATTERN.fullmatch(event.request_id))
        self.assertEqual(uuid.UUID(event.request_id).version, 4)

    def test_invalid_forwarded_for_results_in_null_ip(self):
        with trusted_proxies(1):
            response = self._patch_participant(HTTP_X_FORWARDED_FOR="notanip")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._latest_participant_event().ip_address)

    def test_valid_request_id_and_ip_are_preserved(self):
        good_id = "req-123_ABC.:-1"
        with trusted_proxies(1):
            response = self._patch_participant(
                HTTP_X_REQUEST_ID=good_id,
                HTTP_X_FORWARDED_FOR="203.0.113.10",
            )
        self.assertEqual(response.status_code, 200)
        event = self._latest_participant_event()
        self.assertEqual(event.request_id, good_id)
        self.assertEqual(str(event.ip_address), "203.0.113.10")


class AuditServiceSanitizationTests(TestCase):
    def setUp(self):
        self.owner = make_user("audit_sanitize_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("audit_sanitize_admin", UserRole.ADMIN)
        self.zev = Zev.objects.create(name="Sanitize ZEV", owner=self.owner)

    def _invalid_context(self):
        request = mock.Mock()
        request.audit_request_id = "x" * 65
        request.audit_ip_address = "notanip"
        request.audit_user_agent = "a" * 600
        request.audit_source = "api"
        request.user = self.admin
        request.api_key = None
        return request

    def test_invalid_context_is_dropped_before_insert(self):
        event = record_audit_event(
            request=self._invalid_context(),
            action_category=AuditActionCategory.SYSTEM,
            action_type="system.sanitize_test",
            target_type="system.Event",
            summary="sanitize",
        )
        self.assertIsNone(event.request_id)
        self.assertIsNone(event.ip_address)
        self.assertEqual(len(event.user_agent), 500)

    def test_invalid_context_succeeds_inside_atomic_block(self):
        with transaction.atomic():
            event = record_audit_event(
                request=self._invalid_context(),
                action_category=AuditActionCategory.SYSTEM,
                action_type="system.sanitize_atomic",
                target_type="system.Event",
                summary="sanitize atomic",
            )
        self.assertIsNone(event.request_id)
        self.assertTrue(AuditEvent.objects.filter(pk=event.pk).exists())

    def test_overlong_display_fields_are_truncated(self):
        self.admin.email = ""
        self.admin.first_name = "f" * 150
        self.admin.last_name = "l" * 150
        event = record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type="system.truncate_test",
            target_type="system.Event",
            target_display="d" * 300,
            summary="s" * 600,
            correlation_id="c" * 100,
            user=self.admin,
            zev=self.zev,
        )
        self.assertEqual(len(event.target_display), 255)
        self.assertEqual(len(event.summary), 500)
        self.assertEqual(len(event.correlation_id), 64)
        self.assertEqual(len(event.actor_display), 255)
        self.assertTrue(event.actor_display.endswith("..."))


class AuditMixinAtomicityTests(AuditApiTestCase):
    def test_failed_audit_rolls_back_model_change(self):
        with mock.patch(
            "audit.mixins.record_audit_event",
            side_effect=DatabaseError("audit db down"),
        ):
            with self.assertRaises(DatabaseError):
                self._patch_participant({"first_name": "After"})
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.first_name, "Ada")
        self.assertFalse(
            AuditEvent.objects.filter(
                action_type="participant.update",
                target_id=str(self.participant.id),
                changes_json__first_name__after="After",
            ).exists()
        )

    def test_create_emits_audit_event(self):
        response = self._create_participant()
        self.assertEqual(response.status_code, 201, response.content)
        created = Participant.objects.get(pk=response.data["id"])
        event = AuditEvent.objects.filter(
            action_type="participant.create",
            target_id=str(created.pk),
        ).latest("created_at")
        self.assertEqual(event.target_display, created.full_name)

    def test_failed_audit_rolls_back_create(self):
        with mock.patch(
            "audit.mixins.record_audit_event",
            side_effect=DatabaseError("audit db down"),
        ):
            with self.assertRaises(DatabaseError):
                self._create_participant(email="rollback@example.com")
        self.assertFalse(Participant.objects.filter(email="rollback@example.com").exists())

    def test_destroy_emits_audit_event(self):
        participant_id = str(self.participant.id)
        full_name = self.participant.full_name
        response = self.client.delete(f"/api/v1/zev/participants/{participant_id}/")
        self.assertEqual(response.status_code, 204, response.content)
        event = AuditEvent.objects.filter(
            action_type="participant.delete",
            target_id=participant_id,
        ).latest("created_at")
        self.assertEqual(event.target_display, full_name)

    def test_failed_audit_rolls_back_destroy(self):
        participant_id = str(self.participant.id)
        with mock.patch(
            "audit.mixins.record_audit_event",
            side_effect=DatabaseError("audit db down"),
        ):
            with self.assertRaises(DatabaseError):
                self.client.delete(f"/api/v1/zev/participants/{participant_id}/")
        self.assertTrue(Participant.objects.filter(pk=participant_id).exists())
