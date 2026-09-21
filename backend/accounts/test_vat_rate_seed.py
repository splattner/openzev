"""Regression tests for the 0015_seed_vat_rates data migration.

The migration installs the standard Swiss VAT history (7.7 % for
2018-01-01..2023-12-31, 8.1 % open-ended from 2024-01-01) exactly when no
stored row overlaps the candidate, and leaves everything else untouched.
These tests drive the real migration function against historical models —
never a copy of the seed algorithm.
"""

import datetime
import importlib
from decimal import Decimal
from types import SimpleNamespace

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from testing.helpers import clear_vat_rates

MIGRATION = importlib.import_module("accounts.migrations.0015_seed_vat_rates")

PREDECESSOR = ("accounts", "0014_user_preferred_zev")
TARGET = ("accounts", "0015_seed_vat_rates")

CANONICAL = (
    (Decimal("0.0770"), datetime.date(2018, 1, 1), datetime.date(2023, 12, 31)),
    (Decimal("0.0810"), datetime.date(2024, 1, 1), None),
)


def _migrate_to_latest():
    """Leave the schema fully migrated.

    These tests step ``accounts`` back to a predecessor, which also unapplies
    everything depending on later ``accounts`` migrations. Cleaning up by
    migrating only to ``TARGET`` would leave those later columns (and every app
    that depends on them) missing for whichever test the same worker runs next,
    which is what made an unrelated PDF test fail intermittently under xdist.
    """
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


def _predecessor_apps():
    """Historical app registry as of the migration predecessor."""
    return MigrationExecutor(connection).loader.project_state([PREDECESSOR]).apps


def _run_seed(apps):
    # The seed function only reads schema_editor.connection.alias for
    # database routing; a real schema editor cannot be entered inside the
    # TestCase atomic block on SQLite, so bind the test connection directly.
    # Alias routing itself is covered by test_seed_uses_schema_editor_database_alias.
    MIGRATION.seed_vat_rates(apps, SimpleNamespace(connection=connection))


def _snapshot(rows):
    return [
        (row.id, str(row.rate), row.valid_from, row.valid_to, row.created_at, row.updated_at)
        for row in rows.order_by("id")
    ]


class SeedVatRatesMigrationTests(TransactionTestCase):
    """Actual forward/reverse execution through the real migration graph."""

    def test_forward_migration_seeds_empty_table(self):
        executor = MigrationExecutor(connection)
        executor.migrate([PREDECESSOR])
        self.addCleanup(_migrate_to_latest)
        apps = executor.loader.project_state([PREDECESSOR]).apps
        apps.get_model("accounts", "VatRate").objects.all().delete()

        executor.loader.build_graph()
        executor.migrate([TARGET])

        rates = executor.loader.project_state([TARGET]).apps.get_model("accounts", "VatRate")
        seeded = list(rates.objects.order_by("valid_from").values_list("rate", "valid_from", "valid_to"))
        self.assertEqual(
            [(str(rate), valid_from, valid_to) for rate, valid_from, valid_to in seeded],
            [(str(rate), valid_from, valid_to) for rate, valid_from, valid_to in CANONICAL],
        )
        # The seeded rows are usable by the runtime lookup.
        from accounts.models import VatRate

        self.assertEqual(VatRate.active_for_day(datetime.date(2023, 6, 1)).rate, Decimal("0.0770"))
        self.assertEqual(VatRate.active_for_day(datetime.date(2024, 6, 1)).rate, Decimal("0.0810"))

    def test_reverse_and_reapply_preserve_rates(self):
        executor = MigrationExecutor(connection)
        executor.migrate([PREDECESSOR])
        self.addCleanup(_migrate_to_latest)
        apps = executor.loader.project_state([PREDECESSOR]).apps
        vat_rate = apps.get_model("accounts", "VatRate")
        vat_rate.objects.all().delete()
        edited = vat_rate.objects.create(
            rate=Decimal("0.0850"), valid_from=datetime.date(2024, 1, 1), valid_to=None
        )
        before = _snapshot(vat_rate.objects.all())

        executor.loader.build_graph()
        executor.migrate([TARGET])
        after_forward = _snapshot(
            executor.loader.project_state([TARGET]).apps.get_model("accounts", "VatRate").objects.all()
        )
        # The 2018 default is added; the administrator edit is untouched.
        self.assertEqual(len(after_forward), 2)
        self.assertIn(
            (edited.id, "0.0850", datetime.date(2024, 1, 1), None, edited.created_at, edited.updated_at),
            after_forward,
        )

        # Reverse is a deliberate no-op: rows survive the rollback.
        executor.loader.build_graph()
        executor.migrate([PREDECESSOR])
        after_reverse = _snapshot(apps.get_model("accounts", "VatRate").objects.all())
        self.assertEqual(after_reverse, after_forward)

        # Reapplying adds no duplicate and preserves the edit.
        executor.loader.build_graph()
        executor.migrate([TARGET])
        after_reapply = _snapshot(
            executor.loader.project_state([TARGET]).apps.get_model("accounts", "VatRate").objects.all()
        )
        self.assertEqual(after_reapply, after_forward)
        self.assertEqual(before[0][:3], (edited.id, "0.0850", datetime.date(2024, 1, 1)))


class SeedVatRatesForwardFunctionTests(TestCase):
    """Preservation policy of the forward function against historical models."""

    def setUp(self):
        self.apps = _predecessor_apps()
        self.vat_rate = self.apps.get_model("accounts", "VatRate")
        self.vat_rate.objects.all().delete()

    def _seed(self):
        _run_seed(self.apps)

    def test_forward_function_is_idempotent(self):
        self._seed()
        before = _snapshot(self.vat_rate.objects.all())
        self.assertEqual(len(before), 2)
        self._seed()
        self.assertEqual(_snapshot(self.vat_rate.objects.all()), before)

    def test_adds_missing_non_overlapping_default(self):
        for rate, valid_from, valid_to in CANONICAL:
            with self.subTest(valid_from=valid_from):
                self.vat_rate.objects.all().delete()
                self.vat_rate.objects.create(rate=rate, valid_from=valid_from, valid_to=valid_to)
                self._seed()
                seeded = list(self.vat_rate.objects.order_by("valid_from"))
                self.assertEqual(len(seeded), 2)
                self.assertEqual(
                    [(str(row.rate), row.valid_from, row.valid_to) for row in seeded],
                    [(str(rate), valid_from, valid_to) for rate, valid_from, valid_to in CANONICAL],
                )

    def test_preserves_edited_canonical_rate(self):
        custom = self.vat_rate.objects.create(
            rate=Decimal("0.0850"), valid_from=datetime.date(2024, 1, 1), valid_to=None
        )
        self._seed()
        custom.refresh_from_db()
        self.assertEqual(custom.rate, Decimal("0.0850"))
        self.assertEqual(
            [(str(row.rate), row.valid_from, row.valid_to) for row in self.vat_rate.objects.order_by("valid_from")],
            [
                ("0.0770", datetime.date(2018, 1, 1), datetime.date(2023, 12, 31)),
                ("0.0850", datetime.date(2024, 1, 1), None),
            ],
        )

    def test_preserves_custom_overlapping_windows(self):
        cases = {
            # Open-ended custom row inside the 2024 window: only 2018 is added.
            "open_ended_2025": (
                dict(rate=Decimal("0.0850"), valid_from=datetime.date(2025, 1, 1), valid_to=None),
                2,
                False,
            ),
            # Open-ended custom row starting before 2018: both skipped.
            "open_ended_pre_2018": (
                dict(rate=Decimal("0.0500"), valid_from=datetime.date(2017, 6, 1), valid_to=None),
                1,
                False,
            ),
            # Bounded custom row wholly inside the 2018 window: only 2024 added.
            "bounded_inside_2018": (
                dict(
                    rate=Decimal("0.0500"),
                    valid_from=datetime.date(2020, 1, 1),
                    valid_to=datetime.date(2020, 12, 31),
                ),
                2,
                True,
            ),
        }
        for name, (kwargs, expected_count, has_2024_default) in cases.items():
            with self.subTest(case=name):
                self.vat_rate.objects.all().delete()
                custom = self.vat_rate.objects.create(**kwargs)
                before = _snapshot(self.vat_rate.objects.all())
                self._seed()
                rows = self.vat_rate.objects.order_by("valid_from")
                self.assertEqual(rows.count(), expected_count)
                custom.refresh_from_db()
                self.assertEqual(
                    (str(custom.rate), custom.valid_from, custom.valid_to),
                    (str(kwargs["rate"]), kwargs["valid_from"], kwargs["valid_to"]),
                )
                self.assertEqual(_snapshot(self.vat_rate.objects.filter(pk=custom.pk)), before)
                self.assertEqual(
                    self.vat_rate.objects.filter(
                        rate=Decimal("0.0810"), valid_from=datetime.date(2024, 1, 1)
                    ).exists(),
                    has_2024_default,
                )

    def test_preserves_non_overlapping_history(self):
        self.vat_rate.objects.create(
            rate=Decimal("0.0800"), valid_from=datetime.date(2017, 1, 1), valid_to=datetime.date(2017, 12, 31)
        )
        self._seed()
        self.assertEqual(
            [(str(row.rate), row.valid_from, row.valid_to) for row in self.vat_rate.objects.order_by("valid_from")],
            [
                ("0.0800", datetime.date(2017, 1, 1), datetime.date(2017, 12, 31)),
                ("0.0770", datetime.date(2018, 1, 1), datetime.date(2023, 12, 31)),
                ("0.0810", datetime.date(2024, 1, 1), None),
            ],
        )

    def test_overlap_boundaries_are_inclusive(self):
        # A stored row sharing a boundary day blocks the candidate; an
        # adjacent row separated by one day does not.
        cases = {
            # Existing row ends exactly when the 2018 candidate starts.
            "shared_start_boundary_blocks_2018": (
                dict(rate=Decimal("0.0500"), valid_from=datetime.date(2017, 1, 1), valid_to=datetime.date(2018, 1, 1)),
                False,
                True,
            ),
            # Existing row ends the day before the 2018 candidate starts.
            "adjacent_before_allows_both": (
                dict(rate=Decimal("0.0500"), valid_from=datetime.date(2017, 1, 1), valid_to=datetime.date(2017, 12, 31)),
                True,
                True,
            ),
            # Existing single-day row on the 2024 candidate's first day.
            "shared_2024_start_blocks_2024": (
                dict(rate=Decimal("0.0500"), valid_from=datetime.date(2024, 1, 1), valid_to=datetime.date(2024, 1, 1)),
                True,
                False,
            ),
            # Existing row starts the day after the 2018 candidate ends
            # (so 2018 is added) but overlaps the 2024 candidate (blocked).
            "adjacent_after_2018_blocks_2024": (
                dict(rate=Decimal("0.0500"), valid_from=datetime.date(2024, 1, 1), valid_to=datetime.date(2024, 6, 30)),
                True,
                False,
            ),
        }
        for name, (kwargs, has_2018_default, has_2024_default) in cases.items():
            with self.subTest(case=name):
                self.vat_rate.objects.all().delete()
                self.vat_rate.objects.create(**kwargs)
                self._seed()
                self.assertEqual(
                    self.vat_rate.objects.filter(
                        rate=Decimal("0.0770"), valid_from=datetime.date(2018, 1, 1)
                    ).exists(),
                    has_2018_default,
                    name,
                )
                self.assertEqual(
                    self.vat_rate.objects.filter(
                        rate=Decimal("0.0810"), valid_from=datetime.date(2024, 1, 1)
                    ).exists(),
                    has_2024_default,
                    name,
                )

    def test_seed_uses_schema_editor_database_alias(self):
        """Every read and write is bound to the schema editor's connection."""
        calls = {"alias": [], "created": []}

        class _StubQuerySet:
            def filter(self, *args, **kwargs):
                return self

            def exists(self):
                return False

            def create(self, **kwargs):
                calls["created"].append(kwargs)
                return SimpleNamespace(**kwargs)

        class _StubObjects:
            def using(self, alias):
                calls["alias"].append(alias)
                return _StubQuerySet()

        stub_apps = SimpleNamespace(get_model=lambda app_label, model_name: SimpleNamespace(objects=_StubObjects()))
        stub_editor = SimpleNamespace(connection=SimpleNamespace(alias="sentinel"))

        MIGRATION.seed_vat_rates(stub_apps, stub_editor)

        self.assertTrue(calls["alias"], "the historical queryset must be routed via using()")
        self.assertTrue(all(alias == "sentinel" for alias in calls["alias"]))
        self.assertEqual(
            [(str(kw["rate"]), kw["valid_from"], kw["valid_to"]) for kw in calls["created"]],
            [(str(rate), valid_from, valid_to) for rate, valid_from, valid_to in CANONICAL],
        )

    def test_seed_does_not_modify_existing_invoice(self):
        from datetime import timezone

        from accounts.models import UserRole
        from invoices.engine import generate_invoice
        from invoices.test_helpers import make_participant, make_user, make_zev
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
        from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

        owner = make_user("seed_invoice_owner", UserRole.ZEV_OWNER)
        zev = make_zev(owner, "Seed Invoice ZEV")
        participant = make_participant(zev, first="Seed", last="Invoice")
        metering_point = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-SEED-INV-1", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=participant, valid_from=datetime.date(2026, 1, 1)
        )
        tariff = Tariff.objects.create(
            zev=zev,
            name="Grid",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=datetime.date(2026, 1, 1),
        )
        TariffPeriod.objects.create(tariff=tariff, period_type="flat", price_chf_per_kwh=Decimal("1.00000"))
        MeterReading.objects.create(
            metering_point=metering_point,
            timestamp=datetime.datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("10.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )
        invoice = generate_invoice(participant, datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        before_fields = {
            field: getattr(invoice, field)
            for field in ("subtotal_chf", "vat_rate", "vat_chf", "embedded_vat_chf", "total_chf", "status")
        }
        before_items = list(invoice.items.order_by("id").values())

        self.vat_rate.objects.all().delete()
        self._seed()

        invoice.refresh_from_db()
        self.assertEqual(
            {field: getattr(invoice, field) for field in before_fields},
            before_fields,
        )
        self.assertEqual(list(invoice.items.order_by("id").values()), before_items)


class SeededVatLookupTests(TestCase):
    """The migration-seeded table drives the runtime lookup and zero fallback."""

    def setUp(self):
        clear_vat_rates()
        _run_seed(_predecessor_apps())

    def test_lookup_boundaries_against_seeded_table(self):
        from accounts.models import VatRate
        from invoices.engine import _active_vat_rate

        cases = [
            (datetime.date(2017, 12, 31), None, Decimal("0")),
            (datetime.date(2018, 1, 1), Decimal("0.0770"), Decimal("0.0770")),
            (datetime.date(2023, 12, 31), Decimal("0.0770"), Decimal("0.0770")),
            (datetime.date(2024, 1, 1), Decimal("0.0810"), Decimal("0.0810")),
            (datetime.date(2026, 9, 11), Decimal("0.0810"), Decimal("0.0810")),
        ]
        for day, expected_rate, expected_engine_rate in cases:
            with self.subTest(day=day):
                active = VatRate.active_for_day(day)
                self.assertEqual(active.rate if active else None, expected_rate)
                self.assertEqual(_active_vat_rate(day), expected_engine_rate)

    def test_missing_rate_falls_back_to_zero(self):
        from accounts.models import VatRate
        from invoices.engine import _active_vat_rate

        clear_vat_rates()
        self.assertIsNone(VatRate.active_for_day(datetime.date(2026, 9, 11)))
        self.assertEqual(_active_vat_rate(datetime.date(2026, 9, 11)), Decimal("0"))


class SchemaLeftFullyMigratedTests(TransactionTestCase):
    """Runs after the migration tests above (same module, same worker).

    Regression test: their cleanup used to stop at ``TARGET``, leaving later
    ``accounts`` columns missing, so any test scheduled next on that worker
    (xdist work-stealing makes that possible) failed to insert a user.
    """

    def test_a_user_can_still_be_created_afterwards(self):
        from accounts.models import UserRole
        from testing.helpers import make_user

        make_user("after-the-migration-tests", UserRole.ZEV_OWNER)
