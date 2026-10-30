"""Generalised energy data sources: capabilities, ZEV-held sources, grid connection point.

SPEC-2026-live-energy-data §3, §4.1, §5 (PR 1: no live ingest yet, forecast and Solar Manager live refused).
"""

import importlib
from datetime import date, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.apps import apps as django_apps
from django.utils import timezone

from accounts.models import FeatureFlag
from audit.models import AuditEvent
from metering import tasks
from metering.models import SupplementarySource
from metering.supplementary import sync as sync_service
from metering.supplementary.serializers import live_state_of
from metering.supplementary.testing import (
    INGEST_URL,
    SOURCES_URL,
    SupplementaryApiTestCase,
    client_for,
    quarter_hours,
    reading_payload,
)
from testing import factories
from zev.models import AllocationMode, MeteringPointType, ZevAccessGrant, ZevAccessRole, ZevType

ELIGIBLE_URL = SOURCES_URL + "eligible/"
ZEV_ELIGIBLE_URL = SOURCES_URL + "zev-eligible/"
LIVE_ONLY = {"provides_history": False, "provides_live": True}


def enable_live(enabled: bool = True) -> None:
    FeatureFlag.objects.update_or_create(name=FeatureFlag.LIVE_ENERGY_DATA_ENABLED, defaults={"enabled": enabled})


class CapabilityTestCase(SupplementaryApiTestCase):
    """The base ZEV plus the live flag, a plain consumption meter held by the holder, and an unheld meter."""

    def setUp(self):
        super().setUp()
        enable_live()
        self.plain = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        factories.MeteringPointAssignmentFactory(
            metering_point=self.plain, participant=self.holder, valid_from=date(2025, 1, 1)
        )
        self.unheld = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)

    def make_zev_source(self, point=None, **extra):
        values = dict(
            zev=self.zev, metering_point=point or self.unheld, held_by="zev", participant=None,
            provider="push", provides_history=False, provides_live=True,
        )
        values.update(extra)
        source = SupplementarySource(**values)
        source.issue_push_token()
        source.save()
        return source

    def physical_zev(self):
        zev = factories.ZevFactory(owner=self.manager, zev_type=ZevType.ZEV)
        return zev


class SourceCapabilityModelTests(CapabilityTestCase):
    def test_new_rows_default_to_a_participant_held_history_source_on_a_metering_point(self):
        source = SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        self.assertEqual(
            (source.target, source.held_by, source.provides_history, source.provides_live, source.provides_forecast),
            ("metering_point", "participant", True, False, False),
        )
        self.assertEqual(source.zev_id, self.zev.pk)
        self.assertIsNone(source.live_last_seen_at)

    def test_the_migration_backfills_the_zev_from_the_metering_point(self):
        migration = importlib.import_module("metering.migrations.0012_energy_source_capabilities")
        source = SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        other = factories.ZevFactory()
        SupplementarySource.objects.filter(pk=source.pk).update(zev=other)
        migration.backfill_zev(django_apps, None)
        source.refresh_from_db()
        self.assertEqual(source.zev_id, self.zev.pk)
        self.assertTrue(source.provides_history)

    def assert_integrity_error(self, **values):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupplementarySource.objects.create(provider="push", **values)

    def test_one_history_source_per_metering_point(self):
        SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        self.assert_integrity_error(metering_point=self.point, participant=self.holder)

    def test_a_live_source_may_sit_next_to_the_history_source_but_only_one(self):
        SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        live = dict(metering_point=self.point, participant=self.holder, provides_history=False, provides_live=True)
        SupplementarySource.objects.create(provider="push", **live)
        self.assert_integrity_error(**live)

    def test_one_forecast_source_per_metering_point(self):
        forecast = dict(metering_point=self.point, participant=self.holder, provides_history=False, provides_forecast=True)
        SupplementarySource.objects.create(provider="push", **forecast)
        self.assert_integrity_error(**forecast)

    def test_one_connection_point_per_zev(self):
        zev = self.physical_zev()
        values = dict(
            zev=zev, target="connection_point", held_by="zev", provides_history=False, provides_live=True
        )
        SupplementarySource.objects.create(provider="push", **values)
        self.assert_integrity_error(**values)

    def test_target_check_constraint(self):
        # A metering point target needs a metering point; the connection point must not have one.
        self.assert_integrity_error(zev=self.zev, participant=self.holder)
        self.assert_integrity_error(
            zev=self.zev, target="connection_point", held_by="zev", metering_point=self.point,
            provides_history=False, provides_live=True,
        )
        self.assert_integrity_error(
            zev=self.zev, target="connection_point", held_by="zev", provides_history=True, provides_live=True
        )

    def test_holder_check_constraint(self):
        self.assert_integrity_error(zev=self.zev, metering_point=self.point, held_by="participant")
        self.assert_integrity_error(
            zev=self.zev, metering_point=self.point, held_by="zev", participant=self.holder
        )

    def test_a_source_needs_a_capability(self):
        self.assert_integrity_error(
            zev=self.zev, metering_point=self.point, participant=self.holder, provides_history=False
        )

    def assert_invalid(self, **values):
        base = dict(provider="push", zev=self.zev)
        source = SupplementarySource(**{**base, **values})
        with self.assertRaises(ValidationError):
            source.full_clean(exclude=["credential_encrypted", "push_token_prefix", "push_token_hash"])

    def test_history_still_needs_generation_behind_the_meter(self):
        self.assert_invalid(metering_point=self.plain, participant=self.holder)

    def test_history_is_participant_held_only(self):
        self.assert_invalid(metering_point=self.point, held_by="zev", participant=None)

    def test_live_is_allowed_on_a_plain_consumption_meter(self):
        source = SupplementarySource(
            provider="push", zev=self.zev, metering_point=self.plain, participant=self.holder, **LIVE_ONLY
        )
        source.full_clean(exclude=["credential_encrypted", "push_token_prefix", "push_token_hash"])

    def test_the_connection_point_is_refused_for_a_vzev(self):
        self.assert_invalid(target="connection_point", held_by="zev", **LIVE_ONLY)

    def test_the_zev_must_be_the_metering_points_zev(self):
        self.assert_invalid(zev=factories.ZevFactory(), metering_point=self.point, participant=self.holder)

    def test_clearing_the_behind_the_meter_flag_is_allowed_with_a_live_only_source(self):
        SupplementarySource.objects.create(
            metering_point=self.point, participant=self.holder, provider="push", **LIVE_ONLY
        )
        self.point.has_behind_meter_generation = False
        self.point.clean()

    def test_clearing_the_behind_the_meter_flag_is_refused_with_a_history_source(self):
        SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        self.point.has_behind_meter_generation = False
        with self.assertRaisesMessage(ValidationError, "Disconnect the energy data source first."):
            self.point.clean()

    def test_history_source_helper_ignores_a_live_only_source(self):
        SupplementarySource.objects.create(
            metering_point=self.point, participant=self.holder, provider="push", **LIVE_ONLY
        )
        self.assertIsNone(self.point.history_source())
        history = SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        self.assertEqual(self.point.history_source(), history)
        self.assertIsNotNone(self.point.live_source())


class SourceCreationRightsTests(CapabilityTestCase):
    def post(self, user, point, **extra):
        payload = {"metering_point": str(point.pk), "provider": "push", "consent": True, **extra}
        return client_for(user).post(SOURCES_URL, payload, format="json")

    def test_the_holder_creates_a_live_push_source_on_a_plain_consumption_meter(self):
        response = self.post(self.holder_user, self.plain, **LIVE_ONLY)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["push_token"].startswith("ozs_"))
        self.assertEqual(
            (body["held_by"], body["target"], body["provides_history"], body["provides_live"], body["live_state"]),
            ("participant", "metering_point", False, True, "never"),
        )
        self.assertEqual(body["participant"], str(self.holder.pk))
        self.assertEqual(body["zev"], str(self.zev.pk))

    def test_history_and_live_can_share_one_source(self):
        response = self.post(self.holder_user, self.point, provides_live=True)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["provides_history"], True)
        event = AuditEvent.objects.get(action_type="supplementary_source.create")
        self.assertEqual(event.metadata_json["capabilities"], ["history", "live"])
        self.assertEqual(event.metadata_json["held_by"], "participant")
        self.assertEqual(event.metadata_json["target"], "metering_point")

    def test_a_second_live_source_names_the_field(self):
        self.assertEqual(self.post(self.holder_user, self.plain, **LIVE_ONLY).status_code, 201)
        response = self.post(self.holder_user, self.plain, **LIVE_ONLY)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"provides_live": ["This metering point already has a live data source."]})

    def test_a_second_history_source_names_the_field(self):
        self.assertEqual(self.create_push_source().status_code, 201)
        response = self.post(self.holder_user, self.point)
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_history", response.json())

    def test_a_history_source_needs_generation_behind_the_meter(self):
        response = self.post(self.holder_user, self.plain)
        self.assertEqual(response.status_code, 400)
        self.assertIn("metering_point", response.json())

    def test_consent_is_required_for_live(self):
        response = client_for(self.holder_user).post(
            SOURCES_URL, {"metering_point": str(self.plain.pk), "provider": "push", **LIVE_ONLY}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("consent", response.json())

    def test_a_manager_creates_a_zev_held_source_where_nobody_holds_the_meter(self):
        response = self.post(self.manager, self.unheld, held_by="zev", **LIVE_ONLY)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["held_by"], body["participant"], body["participant_name"]), ("zev", None, None))
        self.assertTrue(body["push_token"])
        event = AuditEvent.objects.get(action_type="supplementary_source.create")
        self.assertEqual(event.metadata_json["held_by"], "zev")
        self.assertFalse(event.metadata_json["created_by_admin"])

    def test_a_manager_is_refused_on_a_meter_somebody_holds(self):
        response = self.post(self.manager, self.plain, held_by="zev", **LIVE_ONLY)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SupplementarySource.objects.count(), 0)

    def test_a_community_assignment_does_not_count_as_a_holder(self):
        factories.MeteringPointAssignmentFactory(
            metering_point=self.unheld, participant=self.other, valid_from=date(2025, 1, 1),
            allocation_mode=AllocationMode.COMMUNITY,
        )
        self.assertEqual(self.post(self.manager, self.unheld, held_by="zev", **LIVE_ONLY).status_code, 201)

    def test_a_participant_may_not_pick_held_by_zev(self):
        response = self.post(self.holder_user, self.plain, held_by="zev", **LIVE_ONLY)
        self.assertEqual(response.status_code, 403)

    def test_a_viewer_may_not_create_zev_held_sources(self):
        self.assertEqual(self.post(self.viewer, self.unheld, held_by="zev", **LIVE_ONLY).status_code, 403)

    def test_zev_held_sources_never_have_history(self):
        response = self.post(self.manager, self.unheld, held_by="zev", provides_history=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_history", response.json())

    def test_an_admin_may_connect_either_kind(self):
        held = self.post(self.admin, self.plain, participant=str(self.holder.pk), **LIVE_ONLY)
        self.assertEqual(held.status_code, 201, held.content)
        zev_held = self.post(self.admin, self.unheld, held_by="zev", **LIVE_ONLY)
        self.assertEqual(zev_held.status_code, 201, zev_held.content)
        refused = self.post(self.admin, self.plain, held_by="zev", provides_live=True, provides_history=False)
        self.assertEqual(refused.status_code, 400)

    # ---- grid connection point ----

    def connection_point(self, user, zev, **extra):
        payload = {"target": "connection_point", "zev": str(zev.pk), "provider": "push", "consent": True, **extra}
        return client_for(user).post(SOURCES_URL, payload, format="json")

    def test_a_manager_connects_the_grid_connection_point_of_a_physical_zev(self):
        zev = self.physical_zev()
        response = self.connection_point(self.manager, zev)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(
            (body["target"], body["held_by"], body["provides_live"], body["provides_history"]),
            ("connection_point", "zev", True, False),
        )
        self.assertIsNone(body["metering_point"])
        self.assertIsNone(body["metering_point_meter_id"])
        self.assertEqual(body["zev"], str(zev.pk))
        event = AuditEvent.objects.get(action_type="supplementary_source.create")
        self.assertEqual(event.metadata_json["target"], "connection_point")

    def test_there_is_one_connection_point_per_zev(self):
        zev = self.physical_zev()
        self.assertEqual(self.connection_point(self.manager, zev).status_code, 201)
        self.assertEqual(self.connection_point(self.manager, zev).status_code, 400)

    def test_a_vzev_has_no_connection_point(self):
        response = self.connection_point(self.manager, self.zev)
        self.assertEqual(response.status_code, 400)
        self.assertIn("target", response.json())

    def test_the_connection_point_is_held_by_the_zev_and_has_no_metering_point(self):
        zev = self.physical_zev()
        self.assertEqual(self.connection_point(self.manager, zev, held_by="participant").status_code, 400)
        self.assertEqual(self.connection_point(self.manager, zev, metering_point=str(self.point.pk)).status_code, 400)
        self.assertEqual(self.connection_point(self.manager, zev, provides_history=True).status_code, 400)

    def test_only_a_manager_of_that_zev_connects_it(self):
        zev = self.physical_zev()
        viewer = factories.ZevFactory(owner=self.manager, zev_type=ZevType.ZEV)
        ZevAccessGrant.objects.create(zev=viewer, user=self.viewer, role=ZevAccessRole.VIEWER)
        self.assertEqual(self.connection_point(self.viewer, viewer).status_code, 403)
        # Somebody who cannot see the ZEV gets the same "invalid pk" answer as for a metering point.
        response = self.connection_point(self.stranger, zev)
        self.assertEqual(response.status_code, 400)
        self.assertIn("zev", response.json())
        self.assertEqual(self.connection_point(self.admin, zev).status_code, 201)

    def test_the_connection_point_needs_consent(self):
        zev = self.physical_zev()
        response = self.connection_point(self.manager, zev, consent=False)
        self.assertEqual(response.status_code, 400)

    # ---- rollout restrictions of this release ----

    def test_forecast_is_not_available_yet(self):
        response = self.post(self.holder_user, self.plain, provides_forecast=True, **LIVE_ONLY)
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_forecast", response.json())

    def test_live_is_push_only_for_now(self):
        response = client_for(self.holder_user).post(
            SOURCES_URL,
            {"metering_point": str(self.point.pk), "provider": "solar_manager", "external_id": "ABC123",
             "api_key": "k", "consent": True, "provides_live": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_live", response.json())

    def test_a_solar_manager_source_keeps_history(self):
        response = client_for(self.holder_user).post(
            SOURCES_URL,
            {"metering_point": str(self.point.pk), "provider": "solar_manager", "external_id": "ABC123",
             "api_key": "k", "consent": True, "provides_history": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_history", response.json())

    def test_everything_new_is_refused_while_the_live_flag_is_off(self):
        enable_live(False)
        live = self.post(self.holder_user, self.plain, **LIVE_ONLY)
        zev_held = self.post(self.manager, self.unheld, held_by="zev", provides_history=True)
        connection = self.connection_point(self.manager, self.physical_zev())
        self.assertEqual([live.status_code, zev_held.status_code, connection.status_code], [400, 400, 400])
        self.assertIn("provides_live", live.json())
        self.assertIn("held_by", zev_held.json())
        self.assertIn("provides_live", connection.json())
        self.assertEqual(SupplementarySource.objects.count(), 0)

    def test_the_live_flag_needs_the_energy_data_flag_too(self):
        from metering.supplementary.testing import enable_feature

        enable_feature(False)
        self.assertEqual(self.post(self.holder_user, self.plain, **LIVE_ONLY).status_code, 404)

    def test_history_creation_is_unchanged_while_the_live_flag_is_off(self):
        enable_live(False)
        self.assertEqual(self.create_push_source().status_code, 201)

    # ---- changing capabilities later ----

    def test_the_owner_adds_live_to_a_history_source_with_consent(self):
        source_id = self.create_push_source().json()["id"]
        url = f"{SOURCES_URL}{source_id}/"
        without = client_for(self.holder_user).patch(url, {"provides_live": True}, format="json")
        self.assertEqual(without.status_code, 400)
        response = client_for(self.holder_user).patch(url, {"provides_live": True, "consent": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["provides_live"])
        event = AuditEvent.objects.filter(action_type="supplementary_source.update").latest("created_at")
        self.assertEqual(event.metadata_json["capabilities"], ["history", "live"])

    def test_capabilities_stay_within_the_rollout_when_patched(self):
        source_id = self.create_push_source().json()["id"]
        url = f"{SOURCES_URL}{source_id}/"
        self.assertEqual(client_for(self.holder_user).patch(url, {"provides_forecast": True}, format="json").status_code, 400)
        self.assertEqual(client_for(self.holder_user).patch(url, {"provides_history": False}, format="json").status_code, 400)

    def test_target_and_holder_cannot_be_changed(self):
        source_id = self.create_push_source().json()["id"]
        url = f"{SOURCES_URL}{source_id}/"
        response = client_for(self.holder_user).patch(url, {"held_by": "zev"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_a_manager_of_a_participant_held_source_still_only_switches_it(self):
        source_id = self.create_push_source().json()["id"]
        url = f"{SOURCES_URL}{source_id}/"
        self.assertEqual(client_for(self.manager).patch(url, {"provides_live": True}, format="json").status_code, 403)

    def test_a_manager_operates_a_zev_held_source_like_its_owner(self):
        source = self.make_zev_source()
        client = client_for(self.manager)
        url = f"{SOURCES_URL}{source.pk}/"
        self.assertEqual(client.patch(url, {"label": "Shelly"}, format="json").status_code, 200)
        rotated = client.post(url + "rotate-push-token/")
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(client.post(url + "revoke-push-token/").status_code, 200)
        self.assertEqual(client.post(url + "disconnect/").status_code, 200)
        self.assertEqual(client.delete(url).status_code, 204)

    def test_other_roles_do_not_operate_a_zev_held_source(self):
        source = self.make_zev_source()
        url = f"{SOURCES_URL}{source.pk}/"
        self.assertEqual(client_for(self.viewer).patch(url, {"label": "x"}, format="json").status_code, 403)
        self.assertEqual(client_for(self.viewer).get(url).status_code, 200)
        self.assertEqual(client_for(self.holder_user).get(url).status_code, 404)


class OrphanTaskTests(CapabilityTestCase):
    def test_a_zev_held_source_is_disconnected_once_somebody_holds_the_meter(self):
        source = self.make_zev_source()
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 0})
        factories.MeteringPointAssignmentFactory(
            metering_point=self.unheld, participant=self.other, valid_from=timezone.localdate() - timedelta(days=1)
        )
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 1})
        source.refresh_from_db()
        self.assertFalse(source.enabled)
        self.assertEqual(source.push_token_prefix, None)
        event = AuditEvent.objects.get(action_type="supplementary_source.disconnect")
        self.assertEqual(event.metadata_json["reason"], "personal_holder_assigned")
        self.assertEqual(event.metadata_json["held_by"], "zev")
        self.assertEqual(event.metadata_json["capabilities"], ["live"])

    def test_a_community_holder_does_not_disconnect_a_zev_held_source(self):
        source = self.make_zev_source()
        factories.MeteringPointAssignmentFactory(
            metering_point=self.unheld, participant=self.other, valid_from=timezone.localdate() - timedelta(days=1),
            allocation_mode=AllocationMode.COMMUNITY,
        )
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 0})
        source.refresh_from_db()
        self.assertTrue(source.enabled)

    def test_the_connection_point_is_never_touched(self):
        source = SupplementarySource(
            zev=self.physical_zev(), target="connection_point", held_by="zev", provider="push", **LIVE_ONLY
        )
        source.issue_push_token()
        source.save()
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 0})
        source.refresh_from_db()
        self.assertTrue(source.enabled)

    def test_a_participant_held_source_is_still_disconnected_when_the_tenancy_ends(self):
        source = SupplementarySource.objects.create(
            metering_point=self.plain, participant=self.holder, provider="push", **LIVE_ONLY
        )
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 0})
        self.assignment.valid_to = None
        plain_assignment = self.plain.assignments.get()
        plain_assignment.valid_to = timezone.localdate() - timedelta(days=1)
        plain_assignment.save()
        self.assertEqual(tasks.disable_orphaned_supplementary_sources(), {"disabled": 1})
        source.refresh_from_db()
        self.assertFalse(source.enabled)
        event = AuditEvent.objects.get(action_type="supplementary_source.disconnect")
        self.assertEqual(event.metadata_json["reason"], "assignment_ended")


class EligibleTests(CapabilityTestCase):
    def test_while_the_live_flag_is_off_the_response_is_the_old_one(self):
        enable_live(False)
        rows = client_for(self.holder_user).get(ELIGIBLE_URL).json()
        self.assertEqual([r["metering_point"] for r in rows], [str(self.point.pk)])
        self.assertEqual(set(rows[0]), {"metering_point", "meter_id", "zev", "zev_name", "participant", "source"})

    def test_with_the_live_flag_every_held_meter_is_listed_with_its_capabilities(self):
        history_id = self.create_push_source().json()["id"]
        live_id = client_for(self.holder_user).post(
            SOURCES_URL,
            {"metering_point": str(self.plain.pk), "provider": "push", "consent": True, **LIVE_ONLY},
            format="json",
        ).json()["id"]
        rows = {r["metering_point"]: r for r in client_for(self.holder_user).get(ELIGIBLE_URL).json()}
        self.assertEqual(set(rows), {str(self.point.pk), str(self.plain.pk)})
        flagged, plain = rows[str(self.point.pk)], rows[str(self.plain.pk)]
        self.assertEqual(flagged["eligible_capabilities"], ["history", "live"])
        self.assertEqual(flagged["sources"], {"history": history_id, "live": None, "forecast": None})
        self.assertEqual(flagged["source"], history_id)
        self.assertEqual(plain["eligible_capabilities"], ["live"])
        self.assertEqual(plain["sources"], {"history": None, "live": live_id, "forecast": None})
        self.assertIsNone(plain["source"])

    def test_it_stays_limited_to_what_the_user_holds_personally(self):
        for user in (self.manager, self.viewer, self.stranger):
            self.assertEqual(client_for(user).get(ELIGIBLE_URL).json(), [], user.username)


class ZevEligibleTests(CapabilityTestCase):
    def get(self, user, zev=None, **params):
        params = {"zev_id": str((zev or self.zev).pk), **params}
        return client_for(user).get(ZEV_ELIGIBLE_URL, params)

    def test_a_manager_sees_the_meters_nobody_holds(self):
        source = self.make_zev_source()
        body = self.get(self.manager).json()
        self.assertEqual(body["zev"], str(self.zev.pk))
        rows = {r["metering_point"]: r for r in body["metering_points"]}
        self.assertEqual(set(rows), {str(self.unheld.pk)})
        row = rows[str(self.unheld.pk)]
        self.assertEqual(row["meter_id"], self.unheld.meter_id)
        self.assertEqual(row["meter_type"], "consumption")
        self.assertEqual(row["eligible_capabilities"], ["live"])
        self.assertEqual(row["sources"], {"history": None, "live": str(source.pk), "forecast": None})
        self.assertEqual(body["connection_point"], {"available": False, "source": None})

    def test_inactive_meters_are_not_offered(self):
        self.unheld.is_active = False
        self.unheld.save()
        self.assertEqual(self.get(self.manager).json()["metering_points"], [])

    def test_the_connection_point_is_available_in_a_physical_zev_until_it_is_taken(self):
        zev = self.physical_zev()
        self.assertEqual(self.get(self.manager, zev).json()["connection_point"], {"available": True, "source": None})
        response = client_for(self.manager).post(
            SOURCES_URL,
            {"target": "connection_point", "zev": str(zev.pk), "provider": "push", "consent": True},
            format="json",
        )
        self.assertEqual(
            self.get(self.manager, zev).json()["connection_point"], {"available": False, "source": response.json()["id"]}
        )

    def test_an_admin_may_ask(self):
        self.assertEqual(self.get(self.admin).status_code, 200)

    def test_scoping(self):
        self.assertEqual(self.get(self.viewer).status_code, 403)
        self.assertEqual(self.get(self.holder_user).status_code, 404)
        self.assertEqual(self.get(self.stranger).status_code, 404)
        self.assertEqual(self.get(self.manager, factories.ZevFactory()).status_code, 404)
        self.assertEqual(client_for(None).get(ZEV_ELIGIBLE_URL, {"zev_id": str(self.zev.pk)}).status_code, 401)

    def test_zev_id_is_required_and_validated(self):
        self.assertEqual(client_for(self.manager).get(ZEV_ELIGIBLE_URL).status_code, 400)
        self.assertEqual(client_for(self.manager).get(ZEV_ELIGIBLE_URL, {"zev_id": "nope"}).status_code, 400)

    def test_it_is_404_while_the_live_flag_is_off(self):
        enable_live(False)
        self.assertEqual(self.get(self.manager).status_code, 404)


class HistoryCapabilityGuardTests(CapabilityTestCase):
    def live_only(self):
        response = client_for(self.holder_user).post(
            SOURCES_URL,
            {"metering_point": str(self.plain.pk), "provider": "push", "consent": True, **LIVE_ONLY},
            format="json",
        )
        return response.json()

    def test_history_push_is_refused_for_a_live_only_source(self):
        token = self.live_only()["push_token"]
        row = reading_payload(quarter_hours(1)[0])
        response = client_for(None).post(
            INGEST_URL, {"readings": [row]}, format="json", HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "This source does not provide history."})

    def test_csv_import_is_refused_for_a_live_only_source(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        source_id = self.live_only()["id"]
        upload = SimpleUploadedFile("e.csv", b"timestamp,consumption_kwh,production_kwh,import_kwh,export_kwh\n")
        response = client_for(self.holder_user).post(
            f"{SOURCES_URL}{source_id}/import-csv/", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "This source does not provide history."})

    def test_test_sync_and_reconciliation_are_refused_for_a_live_only_source(self):
        source_id = self.live_only()["id"]
        client = client_for(self.holder_user)
        for action, method in (("test", client.post), ("sync", client.post), ("reconciliation", client.get)):
            response = method(f"{SOURCES_URL}{source_id}/{action}/")
            self.assertEqual(response.status_code, 400, action)
            self.assertEqual(response.json(), {"detail": "This source does not provide history."}, action)

    def pull_live_only(self):
        source = SupplementarySource(
            zev=self.zev, metering_point=self.plain, participant=self.holder, provider="solar_manager",
            external_id="ABC123", provides_history=False, provides_live=True,
        )
        source.set_credential("key-1")
        source.save()
        return source

    def test_the_beat_fan_out_skips_sources_without_history(self):
        self.pull_live_only()
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay:
            self.assertEqual(tasks.refresh_supplementary_sources(), {"queued": 0})
        delay.assert_not_called()

    def test_a_direct_sync_skips_a_source_without_history(self):
        source = self.pull_live_only()
        self.assertEqual(
            tasks.sync_supplementary_source_impl(str(source.pk)), {"source_id": str(source.pk), "skipped": "no_history"}
        )
        with self.assertRaises(sync_service.SyncSkipped):
            sync_service.sync_source(source)

    def test_nothing_is_queued_after_creating_a_live_only_source(self):
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay:
            self.live_only()
        delay.assert_not_called()

    def test_a_live_only_source_never_counts_in_the_statistics_surfaces(self):
        from metering.supplementary import surfaces

        SupplementarySource.objects.create(
            metering_point=self.plain, participant=self.holder, provider="push", **LIVE_ONLY
        )
        self.assertEqual(surfaces.participants_gross([self.holder.pk], timezone.now() - timedelta(days=1), timezone.now()), {})
        self.assertEqual(surfaces.statement_gross(self.holder.pk, 2026), (None, None))


class SourceListScopingTests(CapabilityTestCase):
    def test_the_connection_point_is_listed_for_its_zevs_managers_viewers_and_admins(self):
        zev = self.physical_zev()
        ZevAccessGrant.objects.create(zev=zev, user=self.viewer, role=ZevAccessRole.VIEWER)
        source = SupplementarySource(zev=zev, target="connection_point", held_by="zev", provider="push", **LIVE_ONLY)
        source.save()
        for user in (self.manager, self.viewer, self.admin):
            body = client_for(user).get(SOURCES_URL).json()
            rows = body["results"] if isinstance(body, dict) else body
            self.assertIn(str(source.pk), [row["id"] for row in rows], user.username)
        for user in (self.holder_user, self.other_user, self.stranger):
            body = client_for(user).get(SOURCES_URL).json()
            rows = body["results"] if isinstance(body, dict) else body
            self.assertNotIn(str(source.pk), [row["id"] for row in rows], user.username)

    def test_zev_held_sources_are_listed_for_managers_but_not_for_participants(self):
        source = self.make_zev_source()
        mine = SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        def ids(user):
            body = client_for(user).get(SOURCES_URL).json()
            return {row["id"] for row in (body["results"] if isinstance(body, dict) else body)}

        self.assertEqual(ids(self.manager), {str(source.pk), str(mine.pk)})
        self.assertEqual(ids(self.holder_user), {str(mine.pk)})
        self.assertEqual(ids(self.other_user), set())


class LiveStateTests(CapabilityTestCase):
    def test_values(self):
        history_only = SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        live = SupplementarySource.objects.create(
            metering_point=self.plain, participant=self.holder, provider="push", **LIVE_ONLY
        )
        now = timezone.now()
        self.assertIsNone(live_state_of(history_only))
        self.assertEqual(live_state_of(live, now), "never")
        live.live_last_seen_at = now - timedelta(seconds=30)
        self.assertEqual(live_state_of(live, now), "fresh")
        live.live_last_seen_at = now - timedelta(seconds=61)
        self.assertEqual(live_state_of(live, now), "stale")
        with override_settings(LIVE_MAX_AGE_S=120):
            self.assertEqual(live_state_of(live, now), "fresh")

    def test_it_is_in_the_api(self):
        live = SupplementarySource.objects.create(
            metering_point=self.plain, participant=self.holder, provider="push", **LIVE_ONLY
        )
        url = f"{SOURCES_URL}{live.pk}/"
        body = client_for(self.holder_user).get(url).json()
        self.assertEqual((body["live_state"], body["live_last_seen_at"]), ("never", None))
        live.live_last_seen_at = timezone.now()
        live.save()
        self.assertEqual(client_for(self.holder_user).get(url).json()["live_state"], "fresh")


class MeteringPointStatusTests(CapabilityTestCase):
    URL = "/api/v1/zev/metering-points/"

    def rows(self, user):
        body = client_for(user).get(self.URL, {"zev_id": str(self.zev.pk)}).json()
        return {row["id"]: row for row in (body["results"] if isinstance(body, dict) else body)}

    def test_the_status_is_the_history_sources_and_the_live_state_the_live_sources(self):
        history = SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        history.mark_ok()
        history.save()
        live = SupplementarySource.objects.create(
            metering_point=self.point, participant=self.holder, provider="push",
            provides_history=False, provides_live=True, live_last_seen_at=timezone.now(),
        )
        for user in (self.holder_user, self.manager, self.viewer, self.admin):
            row = self.rows(user)[str(self.point.pk)]
            self.assertEqual(row["supplementary_source_status"], "ok", user.username)
            self.assertEqual(row["live_state"], "fresh", user.username)
        # The meter without a live source says nothing, and nobody learns of a neighbour's source.
        self.assertIsNone(self.rows(self.manager)[str(self.plain.pk)]["live_state"])
        row = self.rows(self.other_user).get(str(self.point.pk))
        if row is not None:
            self.assertIsNone(row["supplementary_source_status"])
            self.assertIsNone(row["live_state"])
        self.assertEqual(live.metering_point_id, self.point.pk)

    def test_a_live_only_meter_has_no_history_status(self):
        SupplementarySource.objects.create(
            metering_point=self.plain, participant=self.holder, provider="push", **LIVE_ONLY
        )
        row = self.rows(self.manager)[str(self.plain.pk)]
        self.assertIsNone(row["supplementary_source_status"])
        self.assertEqual(row["live_state"], "never")

    def test_live_state_is_null_while_the_live_flag_is_off(self):
        SupplementarySource.objects.create(
            metering_point=self.plain, participant=self.holder, provider="push", **LIVE_ONLY
        )
        enable_live(False)
        self.assertIsNone(self.rows(self.manager)[str(self.plain.pk)]["live_state"])

    def test_the_list_does_not_query_per_metering_point(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count():
            with CaptureQueriesContext(connection) as queries:
                client_for(self.manager).get(self.URL, {"zev_id": str(self.zev.pk)})
            return len(queries)

        SupplementarySource.objects.create(metering_point=self.point, participant=self.holder, provider="push")
        before = count()
        for _ in range(3):
            point = factories.MeteringPointFactory(zev=self.zev, has_behind_meter_generation=True, meter_type=MeteringPointType.BIDIRECTIONAL)
            factories.MeteringPointAssignmentFactory(metering_point=point, participant=self.other, valid_from=date(2025, 1, 1))
            SupplementarySource.objects.create(metering_point=point, participant=self.other, provider="push")
        self.assertEqual(count(), before)
