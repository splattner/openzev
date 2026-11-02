"""0046 preserves legacy data when alias normalization would collide."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


BEFORE = [("zev", "0046_meteringpoint_secondary_meter_id")]
AFTER = [("zev", "0047_meteringpoint_metering_point_secondary_differs_from_primary")]


class MeterIdentityMigrationTests(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        # Historical models: the real ones query columns that later migrations added.
        apps = executor.loader.project_state(BEFORE).apps
        self.Building = apps.get_model("zev", "Building")
        self.Point = apps.get_model("zev", "MeteringPoint")
        self.zev = apps.get_model("zev", "Zev").objects.create(name="Migration ZEV")

    def tearDown(self):
        self.Point.objects.all().delete()
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def point(self, primary, secondary):
        building = self.Building.objects.filter(zev_id=self.zev.pk).first() or self.Building.objects.create(
            zev_id=self.zev.pk, name="Migration building"
        )
        return self.Point.objects.create(zev_id=self.zev.pk, building=building, meter_id=primary, secondary_meter_id=secondary)

    def test_normalization_collision_aborts_without_changing_any_id(self):
        first = self.point("MIG-A", "MIG-ALIAS")
        second = self.point("MIG-B", None)
        blank = self.point("MIG-C", None)
        self.Point.objects.filter(pk=second.pk).update(secondary_meter_id=" MIG-ALIAS ")
        self.Point.objects.filter(pk=blank.pk).update(secondary_meter_id="   ")
        with self.assertRaisesMessage(RuntimeError, "Correct their secondary IDs"):
            MigrationExecutor(connection).migrate(AFTER)
        first.refresh_from_db()
        second.refresh_from_db()
        blank.refresh_from_db()
        self.assertEqual(first.secondary_meter_id, "MIG-ALIAS")
        self.assertEqual(second.secondary_meter_id, " MIG-ALIAS ")
        self.assertEqual(blank.secondary_meter_id, "   ")

    def test_normalizes_blanks_and_redundancy_while_preserving_cross_point_collisions(self):
        redundant = self.point("MIG-SELF", None)
        trimmed = self.point("MIG-TRIM", None)
        blank = self.point("MIG-BLANK", None)
        self.Point.objects.filter(pk=redundant.pk).update(secondary_meter_id="MIG-SELF")
        self.Point.objects.filter(pk=trimmed.pk).update(secondary_meter_id=" MIG-SELF ")
        self.Point.objects.filter(pk=blank.pk).update(secondary_meter_id="   ")
        MigrationExecutor(connection).migrate(AFTER)
        redundant.refresh_from_db()
        trimmed.refresh_from_db()
        blank.refresh_from_db()
        self.assertIsNone(redundant.secondary_meter_id)
        self.assertIsNone(blank.secondary_meter_id)
        self.assertEqual(trimmed.secondary_meter_id, "MIG-SELF")
