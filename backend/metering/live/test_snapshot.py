"""``metering.live.snapshot``: tiers, split and visibility (SPEC-2026-live-energy-data §5.2, ADR 0044)."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from allocation.split import split_consumption, split_production
from metering.live import snapshot
from metering.live.testing import LiveTestCase, client_for, snapshot_url
from metering.models import SourceHolder, SupplementarySource
from zev.models import (
    AllocationMode,
    MeteringPointAssignment,
    MeteringPointType,
    Zev,
    ZevType,
)

D = Decimal


class SnapshotCase(LiveTestCase):
    def snap(self, user=None, **kwargs):
        return snapshot.zev_snapshot(self.zev, now=self.now, viewer=user or self.manager, **kwargs)


class ClassifyTests(LiveTestCase):
    """The pure tier rule, without a database fixture."""

    def classify(self, producing, consuming, connection=None, physical=True):
        return snapshot.classify(
            {k: None if v is None else D(v) for k, v in producing.items()},
            {k: None if v is None else D(v) for k, v in consuming.items()},
            connection_w=None if connection is None else D(connection),
            physical=physical,
        )

    def test_a_missing_producer_hides_everything(self):
        totals = self.classify({"a": -100, "b": None}, {"c": 50})

        self.assertEqual((totals.tier, totals.production_w, totals.consumption_w), ("none", None, None))

    def test_no_producer_at_all_is_none(self):
        self.assertEqual(self.classify({}, {"c": 50}).tier, "none")

    def test_production_without_known_consumption_shows_production_only(self):
        totals = self.classify({"a": -8000}, {"c": 50, "d": None})

        self.assertEqual((totals.tier, totals.production_w), ("production", D(8000)))
        self.assertIsNone(totals.consumption_w)
        self.assertIsNone(totals.surplus_w)
        self.assertIsNone(totals.local_share_pct)

    def test_every_consumer_known_makes_it_exact(self):
        totals = self.classify({"a": -8000}, {"c": 1000, "d": 2000})

        self.assertEqual((totals.tier, totals.basis), ("exact", "all_points"))
        self.assertEqual((totals.consumption_w, totals.surplus_w, totals.grid_import_w), (D(3000), D(5000), D(0)))
        self.assertEqual(totals.local_share_pct, D(100))

    def test_the_connection_point_gives_the_consumption_in_a_physical_zev(self):
        totals = self.classify({"a": -8000}, {"c": None}, connection=-3000)

        self.assertEqual((totals.tier, totals.basis, totals.consumption_w), ("exact", "connection_point", D(5000)))

    def test_the_connection_point_counts_for_nothing_in_a_vzev(self):
        self.assertEqual(self.classify({"a": -8000}, {"c": None}, connection=-3000, physical=False).tier, "production")

    def test_all_points_win_over_the_connection_point(self):
        totals = self.classify({"a": -8000}, {"c": 1000}, connection=-3000)

        self.assertEqual((totals.basis, totals.consumption_w), ("all_points", D(1000)))

    def test_a_grid_import_means_the_zev_is_short_of_production(self):
        totals = self.classify({"a": -2000}, {"c": 5000})

        self.assertEqual((totals.surplus_w, totals.grid_import_w, totals.local_share_pct), (D(0), D(3000), D(40)))

    def test_the_connection_point_cannot_make_consumption_negative(self):
        totals = self.classify({"a": -2000}, {"c": None}, connection=-9000)

        self.assertEqual(totals.consumption_w, D(0))
        self.assertIsNone(totals.local_share_pct)

    def test_a_production_meter_drawing_power_and_a_consumer_feeding_out_add_nothing(self):
        totals = self.classify({"pv": 50}, {"flat": -80})

        self.assertEqual((totals.production_w, totals.consumption_w), (D(0), D(0)))

    def test_a_bidirectional_point_counts_by_the_sign_of_its_power(self):
        feeding = self.classify({"bi": -700, "pv": -1000}, {"bi": -700, "flat": 200})
        drawing = self.classify({"bi": 300, "pv": -1000}, {"bi": 300, "flat": 200})

        self.assertEqual((feeding.production_w, feeding.consumption_w), (D(1700), D(200)))
        self.assertEqual((drawing.production_w, drawing.consumption_w), (D(1000), D(500)))


class SnapshotTierTests(SnapshotCase):
    def test_none_without_a_producing_metering_point(self):
        self.pv.is_active = False
        self.pv.save()
        self.wire(pv=None, flat1=500)

        shot = self.snap()

        self.assertEqual(shot["tier"], "none")
        self.assertEqual(shot["coverage"]["producing_points"], 0)
        self.assertIsNone(shot["production_w"])
        self.assertIsNone(shot["as_of"])

    def test_none_when_the_only_producer_has_no_source(self):
        self.wire(pv=None, flat1=500)

        self.assertEqual(self.snap()["tier"], "none")

    def test_none_when_the_producer_value_is_stale(self):
        source = self.live_source(self.pv)
        self.sample(source, -8000, age=61)

        shot = self.snap()

        self.assertEqual(shot["tier"], "none")
        self.assertEqual(shot["coverage"]["producing_fresh"], 0)

    def test_a_value_of_exactly_the_maximum_age_still_counts(self):
        self.sample(self.live_source(self.pv), -8000, age=60)

        self.assertEqual(self.snap()["tier"], "production")

    def test_production_when_only_some_consumers_report(self):
        self.wire(pv=-8000, flat1=1200)

        shot = self.snap()

        self.assertEqual(shot["tier"], "production")
        self.assertEqual(shot["production_w"], 8000.0)
        for key in ("consumption_w", "surplus_w", "grid_import_w", "local_share_pct", "consumption_basis"):
            self.assertIsNone(shot[key], key)
        self.assertEqual(
            shot["coverage"],
            {"producing_points": 1, "producing_fresh": 1, "consuming_points": 3, "consuming_fresh": 1,
             "connection_point": None, "live_sources": 2},
        )

    def test_exact_when_every_point_reports(self):
        self.wire(pv=-8000, flat1=1000, flat2=2000, flat3=500)

        shot = self.snap()

        self.assertEqual((shot["tier"], shot["consumption_basis"]), ("exact", "all_points"))
        self.assertEqual((shot["production_w"], shot["consumption_w"]), (8000.0, 3500.0))
        self.assertEqual((shot["surplus_w"], shot["grid_import_w"], shot["local_share_pct"]), (4500.0, 0.0, 100.0))

    def test_exact_through_the_connection_point(self):
        self.wire(pv=-8000, connection=-3000)

        shot = self.snap()

        self.assertEqual((shot["tier"], shot["consumption_basis"]), ("exact", "connection_point"))
        self.assertEqual(shot["consumption_w"], 5000.0)
        self.assertEqual(shot["coverage"]["connection_point"], "fresh")

    def test_a_stale_connection_point_is_not_used(self):
        self.wire(pv=-8000)
        self.sample(self.live_source(), -3000, age=120)

        shot = self.snap()

        self.assertEqual(shot["tier"], "production")
        self.assertEqual(shot["coverage"]["connection_point"], "never")  # never delivered through the API

    def test_a_connection_point_that_reported_before_reads_stale(self):
        self.wire(pv=-8000)
        source = self.sample(self.live_source(), -3000, age=120)
        type(source).objects.filter(pk=source.pk).update(live_last_seen_at=self.now - timedelta(seconds=120))

        self.assertEqual(self.snap()["coverage"]["connection_point"], "stale")

    def test_the_connection_point_is_ignored_in_a_vzev(self):
        Zev.objects.filter(pk=self.zev.pk).update(zev_type=ZevType.VZEV)
        self.zev.refresh_from_db()
        self.wire(pv=-8000, connection=-3000)

        self.assertEqual(self.snap()["tier"], "production")

    def test_all_points_win_over_the_connection_point(self):
        self.wire(pv=-8000, flat1=1000, flat2=1000, flat3=1000, connection=-1)

        shot = self.snap()

        self.assertEqual((shot["consumption_basis"], shot["consumption_w"]), ("all_points", 3000.0))

    def test_a_disabled_source_counts_as_missing(self):
        sources = self.wire(pv=-8000)
        type(sources["pv"]).objects.filter(pk=sources["pv"].pk).update(enabled=False)

        self.assertEqual(self.snap()["tier"], "none")

    def test_as_of_is_the_oldest_sample_used(self):
        self.sample(self.live_source(self.pv), -8000, age=3)
        self.sample(self.live_source(self.flat1, participant=self.p1), 1000, age=40)
        self.sample(self.live_source(self.flat2, participant=self.p2), 1000, age=10)
        self.sample(self.live_source(self.flat3, participant=self.quiet), 1000, age=20)

        self.assertEqual(self.snap()["as_of"], snapshot.iso(self.now - timedelta(seconds=40)))

    def test_as_of_ignores_a_sample_that_is_not_part_of_the_figures(self):
        self.sample(self.live_source(self.pv), -8000, age=3)
        self.sample(self.live_source(self.flat1, participant=self.p1), 1000, age=45)  # tier production: unused
        self.sample(self.live_source(), -2000, age=1)

        shot = self.snap()

        self.assertEqual(shot["consumption_basis"], "connection_point")
        self.assertEqual(shot["as_of"], snapshot.iso(self.now - timedelta(seconds=3)))

    def test_the_worked_example_to_the_watt(self):
        # SPEC §1: PV feeds 8 kW in, 3 kW leave to the grid, flat 2 draws 1.2 kW.
        self.wire(pv=-8000, flat2=1200, connection=-3000)

        shot = self.snap(self.user2)

        self.assertEqual(shot["tier"], "exact")
        self.assertEqual(
            (shot["production_w"], shot["consumption_w"], shot["surplus_w"], shot["local_share_pct"]),
            (8000.0, 5000.0, 3000.0, 100.0),
        )
        self.assertEqual(
            {key: shot["own"][key] for key in ("consumption_w", "local_w", "grid_w")},
            {"consumption_w": 1200.0, "local_w": 1200.0, "grid_w": 0.0},
        )

    def test_the_worked_example_without_the_connection_point_shows_production_only(self):
        self.wire(pv=-8000, flat2=1200)

        shot = self.snap(self.user2)

        self.assertEqual((shot["tier"], shot["production_w"], shot["surplus_w"]), ("production", 8000.0, None))
        self.assertEqual(shot["own"]["consumption_w"], 1200.0)
        self.assertIsNone(shot["own"]["local_w"])

    def test_a_bidirectional_household_feeds_production_and_draws_consumption(self):
        self.flat1.meter_type = MeteringPointType.BIDIRECTIONAL
        self.flat1.save()
        self.wire(pv=-1000, flat1=-400, flat2=300, flat3=200)

        shot = self.snap()

        self.assertEqual(shot["coverage"]["producing_points"], 2)
        self.assertEqual((shot["production_w"], shot["consumption_w"]), (1400.0, 500.0))

    def test_a_bidirectional_household_without_a_source_keeps_the_zev_at_none(self):
        self.flat1.meter_type = MeteringPointType.BIDIRECTIONAL
        self.flat1.save()
        self.wire(pv=-1000, flat2=300, flat3=200)

        self.assertEqual(self.snap()["tier"], "none")

    def test_an_inactive_metering_point_is_not_part_of_the_coverage(self):
        self.flat3.is_active = False
        self.flat3.save()
        self.wire(pv=-8000, flat1=1000, flat2=1000)

        shot = self.snap()

        self.assertEqual((shot["tier"], shot["coverage"]["consuming_points"]), ("exact", 2))

    def test_live_sources_counts_enabled_live_sources_with_the_connection_point(self):
        self.assertEqual(self.snap()["coverage"]["live_sources"], 0)
        self.wire(pv=-8000, flat1=1000, connection=-3000)

        self.assertEqual(self.snap()["coverage"]["live_sources"], 3)

    def test_live_sources_leaves_out_disabled_inactive_and_non_live_sources(self):
        sources = self.wire(pv=-8000, flat1=1000, flat2=500, connection=-3000)
        sources["flat1"].enabled = False
        sources["flat1"].save()
        self.flat2.is_active = False
        self.flat2.save()
        SupplementarySource.objects.create(
            zev=self.zev, metering_point=self.flat3, held_by=SourceHolder.PARTICIPANT, participant=self.quiet,
            provider="push", provides_history=True, provides_live=False,
        )

        self.assertEqual(self.snap()["coverage"]["live_sources"], 2)  # the PV point and the connection point

    def test_numbers_are_rounded_to_one_decimal(self):
        self.wire(pv="-8000.04", flat1="1000.05", flat2=0, flat3=0)

        shot = self.snap()

        self.assertEqual((shot["production_w"], shot["consumption_w"]), (8000.0, 1000.1))

    def test_the_maximum_age_is_reported(self):
        self.assertEqual(self.snap()["max_age_s"], 60)


class SnapshotSplitTests(SnapshotCase):
    def test_the_own_split_is_the_billing_arithmetic_on_watts(self):
        self.wire(pv=-8000, flat1=1500, flat2=2500, flat3=1000)

        own = self.snap(self.user1)["own"]

        local, grid = split_consumption(D(1500), D(5000), D(8000))
        self.assertEqual((own["local_w"], own["grid_w"]), (float(local), float(grid)))
        self.assertEqual((own["local_w"], own["grid_w"]), (1500.0, 0.0))

    def test_a_short_zev_splits_the_pool_in_proportion(self):
        self.wire(pv=-1000, flat1=1500, flat2=2500, flat3=1000)

        own = self.snap(self.user1)["own"]

        local, grid = split_consumption(D(1500), D(5000), D(1000))
        self.assertEqual((own["local_w"], own["grid_w"]), (float(local), float(grid)))
        self.assertEqual((own["local_w"], own["grid_w"]), (300.0, 1200.0))

    def test_a_producing_participant_gets_the_production_split(self):
        # p1 also holds the PV plant, so their own view has both sides.
        MeteringPointAssignment.objects.create(
            metering_point=self.pv, participant=self.p1, valid_from=timezone.localdate() - timedelta(days=30)
        )
        self.wire(pv=-1000, flat1=500, flat2=1500, flat3=1000)
        # The PV point needs a participant-held source now that p1 holds it.
        pv_source = self.pv.supplementary_sources.get()
        type(pv_source).objects.filter(pk=pv_source.pk).update(held_by="participant", participant=self.p1)

        own = self.snap(self.user1)["own"]

        to_zev, to_grid = split_production(D(1000), D(1000), D(3000))
        self.assertEqual((own["production_w"], own["to_zev_w"], own["to_grid_w"]), (1000.0, float(to_zev), float(to_grid)))
        self.assertEqual((own["consumption_w"], own["local_w"]), (500.0, 166.7))

    def test_a_pure_consumer_has_no_production_side(self):
        self.wire(pv=-8000, flat1=1500, flat2=2500, flat3=1000)

        own = self.snap(self.user1)["own"]

        self.assertEqual((own["production_w"], own["to_zev_w"], own["to_grid_w"]), (None, None, None))

    def test_the_split_is_withheld_when_the_inputs_contradict_each_other(self):
        # The connection point says 1 kW in total while flat 2 reports 1.2 kW (timing between two devices).
        self.wire(pv=-8000, flat2=1200, connection=-7000)

        shot = self.snap(self.user2)

        self.assertEqual(shot["tier"], "exact")
        self.assertEqual(shot["own"]["split_withheld_reason"], "inconsistent")
        self.assertEqual((shot["own"]["local_w"], shot["own"]["grid_w"]), (None, None))
        self.assertEqual(shot["own"]["consumption_w"], 1200.0)  # the measurement itself stays

    def test_an_incomplete_own_view_shows_no_figures(self):
        second = self.live_source(
            factories_point(self.zev, assigned_to=self.p1), participant=self.p1
        )
        self.wire(pv=-8000, flat1=1000)
        self.sample(second, 100, age=90)

        own = self.snap(self.user1)["own"]

        self.assertEqual((own["complete"], own["points"], own["points_fresh"]), (False, 2, 1))
        self.assertEqual((own["consumption_w"], own["local_w"]), (None, None))

    def test_no_own_block_for_a_participant_without_a_live_source(self):
        self.wire(pv=-8000, flat1=1000)

        self.assertIsNone(self.snap(self.quiet_user)["own"])

    def test_no_own_block_for_a_manager_who_is_no_participant(self):
        self.wire(pv=-8000, flat1=1000)

        self.assertIsNone(self.snap(self.manager)["own"])

    def test_a_community_mode_point_is_nobodys_own(self):
        MeteringPointAssignment.objects.filter(metering_point=self.flat1).update(
            allocation_mode=AllocationMode.COMMUNITY
        )
        self.wire(pv=-8000, flat1=1000)

        self.assertIsNone(self.snap(self.user1)["own"])

    def test_the_optional_gross_values_are_passed_on_when_every_point_has_them(self):
        self.sample(self.live_source(self.pv), -8000)
        self.sample(self.live_source(self.flat1, participant=self.p1), -500, production_w=2000, consumption_w=1500)

        own = self.snap(self.user1)["own"]

        self.assertEqual(own["gross"], {"production_w": 2000.0, "consumption_w": 1500.0})

    def test_gross_values_are_absent_when_the_device_does_not_report_them(self):
        self.wire(pv=-8000, flat1=1000)

        self.assertEqual(self.snap(self.user1)["own"]["gross"], {"production_w": None, "consumption_w": None})


def factories_point(zev, *, assigned_to):
    from testing import factories

    point = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
    factories.MeteringPointAssignmentFactory(metering_point=point, participant=assigned_to, valid_from=assigned_to.valid_from)
    return point


class ManagerPointsTests(SnapshotCase):
    def test_managers_get_a_row_per_active_point_with_states(self):
        self.wire(pv=-8000, flat1=1200)
        stale = self.live_source(self.flat2, participant=self.p2)
        self.sample(stale, 700, age=200)
        type(stale).objects.filter(pk=stale.pk).update(live_last_seen_at=self.now - timedelta(seconds=200))

        points = {row["meter_id"]: row for row in self.snap()["points"]}

        pv, flat1, flat2, flat3 = (points[p.meter_id] for p in (self.pv, self.flat1, self.flat2, self.flat3))
        self.assertEqual((pv["live_state"], pv["meter_power_w"], pv["held_by"], pv["participant_name"]),
                         ("fresh", -8000.0, "zev", None))
        self.assertEqual((flat1["live_state"], flat1["meter_power_w"], flat1["age_s"]), ("fresh", 1200.0, 5))
        self.assertEqual(flat1["participant_name"], self.p1.display_name)
        self.assertEqual((flat2["live_state"], flat2["meter_power_w"], flat2["age_s"]), ("stale", None, None))
        self.assertEqual((flat3["live_state"], flat3["source_id"], flat3["held_by"]), ("never", None, None))

    def test_the_connection_point_is_listed_when_it_exists(self):
        self.wire(pv=-8000, connection=-3000)

        rows = self.snap()["points"]

        connection = [row for row in rows if row["target"] == "connection_point"]
        self.assertEqual(len(connection), 1)
        self.assertEqual(
            (connection[0]["metering_point_id"], connection[0]["meter_power_w"], connection[0]["held_by"]),
            (None, -3000.0, "zev"),
        )

    def test_participants_get_no_points(self):
        self.wire(pv=-8000, flat1=1200)

        self.assertNotIn("points", self.snap(self.user1))

    def test_viewers_and_admins_get_points(self):
        self.wire(pv=-8000)

        self.assertIn("points", self.snap(self.viewer))
        self.assertIn("points", self.snap(self.admin))


class SnapshotVisibilityTests(LiveTestCase):
    def get(self, user, zev=None):
        return client_for(user).get(snapshot_url(zev or self.zev))

    def test_a_participant_never_sees_another_participants_value(self):
        self.wire(pv=-8000, flat1=1111.1, flat2=2222.2, flat3=3333.3)

        response = self.get(self.user1)

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("points", response.json())
        self.assertIn("1111.1", body)
        self.assertNotIn("2222.2", body)
        self.assertNotIn("3333.3", body)
        self.assertNotIn(self.p2.display_name, body)

    def test_managers_and_viewers_see_per_point_values(self):
        self.wire(pv=-8000, flat2=2222.2)

        for user in (self.manager, self.viewer, self.admin):
            with self.subTest(user=user.username):
                response = self.get(user)
                self.assertEqual(response.status_code, 200)
                self.assertIn("2222.2", response.content.decode())

    def test_an_outsider_gets_a_404(self):
        self.assertEqual(self.get(self.outsider).status_code, 404)

    def test_an_unknown_zev_gets_the_same_404(self):
        import uuid

        response = client_for(self.admin).get(f"/api/v1/metering/live/zevs/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, 404)

    def test_a_former_participant_is_refused(self):
        from zev.models import Participant

        Participant.objects.filter(pk=self.p1.pk).update(valid_to=timezone.localdate() - timedelta(days=1))

        self.assertEqual(self.get(self.user1).status_code, 404)

    def test_a_participant_of_another_zev_is_refused(self):
        from testing import factories

        other = factories.ZevFactory()
        factories.ParticipantFactory(zev=other, user=self.outsider, valid_from=self.p1.valid_from)

        self.assertEqual(self.get(self.outsider, zev=other).status_code, 200)  # their own ZEV
        self.assertEqual(self.get(self.outsider, zev=self.zev).status_code, 404)

    def test_the_anonymous_caller_is_refused(self):
        self.assertEqual(client_for(None).get(snapshot_url(self.zev)).status_code, 401)

    def test_a_disabled_zev_is_invisible_to_all_but_admins(self):
        Zev.objects.filter(pk=self.zev.pk).update(disabled_at=timezone.now())

        self.assertEqual(self.get(self.user1).status_code, 404)
        self.assertEqual(self.get(self.manager).status_code, 404)
        self.assertEqual(self.get(self.admin).status_code, 200)

    def test_the_flag_off_answers_404(self):
        from metering.live.testing import enable_live

        enable_live(False)

        self.assertEqual(self.get(self.manager).status_code, 404)

    def test_the_read_throttle_applies_per_user(self):
        from django.core.cache import cache
        from metering.live.permissions import LiveReadThrottle

        cache.clear()
        rates = dict(LiveReadThrottle.THROTTLE_RATES)
        LiveReadThrottle.THROTTLE_RATES = {**rates, "live_read": "2/hour"}
        try:
            statuses = [self.get(self.user1).status_code for _ in range(3)]
            other = self.get(self.user2).status_code
        finally:
            LiveReadThrottle.THROTTLE_RATES = rates

        self.assertEqual((statuses, other), ([200, 200, 429], 200))
