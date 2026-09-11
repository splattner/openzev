"""Readiness and attention endpoint tests.

Covers the contract in docs/specs/2026-03-invoice-lifecycle-and-communication.md
§5.6a:
the three readiness forms, cockpit-period resolution (most recent ENDED
period with open work), step statuses (ok|warn|todo|done — never `blocked`),
the first-run setup block, the awaiting-first-period and caught-up states,
attention item types, and RBAC/param validation.

Calendar discipline: every behaviour that depends on "today" passes an
explicit date into the pure functions (``resolve_cockpit_period`` /
``compute_attention`` take ``today``), and endpoint tests build their periods
relative to the real clock so they never assume a specific month length or
that enough periods have elapsed since a hard-coded start date.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import EmailLog, Invoice, InvoiceStatus
from invoices.readiness import (
    compute_attention,
    compute_period_list,
    compute_readiness,
    compute_readiness_many,
    period_end,
    period_starts,
    resolve_cockpit_period,
)
from invoices.test_helpers import make_participant, make_user, make_zev
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing.helpers import authenticate as auth
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

# A fixed "today" so tests do not depend on the wall clock or the calendar
# month the suite happens to run in.
FROZEN_TODAY = date(2026, 9, 15)


def _fill_readings(mp, start: date, end: date):
    day = start
    while day <= end:
        # Delete-then-insert keeps the unique constraint (point, timestamp,
        # direction) intact when a test fills overlapping windows twice.
        MeterReading.objects.filter(metering_point=mp, timestamp__date=day).delete()  # ADR 0007: fine in tests
        MeterReading.objects.create(
            metering_point=mp,
            timestamp=datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )
        day += timedelta(days=1)


def _energy_tariff(zev, valid_from=date(2026, 1, 1), valid_to=None, price="0.20000"):
    tariff = Tariff.objects.create(
        zev=zev,
        name="Energy",
        category=TariffCategory.ENERGY,
        billing_mode=BillingMode.ENERGY,
        energy_type=EnergyType.LOCAL,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    TariffPeriod.objects.create(
        tariff=tariff,
        period_type=PeriodType.FLAT,
        price_chf_per_kwh=Decimal(price),
    )
    return tariff


def _dynamic_tariff(
    zev, *, energy_type=EnergyType.GRID, category=TariffCategory.ENERGY,
    valid_from=date(2026, 1, 1), tariff_type="grid", label="Dynamic grid",
):
    # category=ENERGY, matching _energy_tariff() above: _load_energy_tariffs()
    # only considers that category (a pre-existing readiness limitation, not
    # something this dynamic-tariff work changes — grid_fees/levies tariffs
    # are priced by the engine but not coverage-checked by readiness today).
    source = DynamicTariffSource.objects.create(
        label=label, url=f"https://api.example.ch/{label.replace(' ', '-')}",
        adapter="vse_v1", tariff_type=tariff_type, tariff_name="",
    )
    tariff = Tariff.objects.create(
        zev=zev, name=label, category=category, billing_mode=BillingMode.ENERGY,
        energy_type=energy_type, valid_from=valid_from, dynamic_source=source,
    )
    return tariff, source


def _store_series(source, start: datetime, end: datetime, price="0.20000"):
    """One stored interval spanning ``[start, end)``.

    A single row is enough to prove day-level coverage: ``coverage_gaps``
    walks stored intervals, not a fixed resolution, so it does not care
    whether the span is represented by one row or a thousand quarter-hourly
    ones.
    """
    DynamicPricePoint.objects.create(
        source=source, valid_from=start, valid_to=end, price_chf_per_kwh=Decimal(price),
    )


class ReadinessTestCase(TestCase):
    """Shared fixture: one monthly ZEV with green master data."""

    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("rd_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("rd_other_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("rd_admin", UserRole.ADMIN)
        self.participant_user = make_user("rd_participant", UserRole.PARTICIPANT)

        self.zev = make_zev(self.owner, "Readiness ZEV")
        self.zev.start_date = date(2026, 1, 1)
        self.zev.billing_interval = "monthly"
        self.zev.save()

        self.participant = make_participant(self.zev, user=self.participant_user, first="Ready")
        self.mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-RD-1", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.mp, participant=self.participant, valid_from=date(2026, 1, 1)
        )
        self.tariff = _energy_tariff(self.zev)

    # -- helpers ----------------------------------------------------------


    def _cockpit(self, today=None):
        return resolve_cockpit_period(self.zev, today)

    def _readiness(self, **params):
        query = {"zev_id": str(self.zev.id), **params}
        return self.client.get("/api/v1/invoices/invoices/readiness/", query)

    def _steps_by_key(self, payload):
        return {step["key"]: step for step in payload["steps"]}

    def _add_billable_participant(self, first="Second", meter_id="CH-RD-2"):
        """A second billable participant (active + assigned, open windows)."""
        participant = make_participant(self.zev, first=first)
        mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id=meter_id, meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=date(2026, 1, 1)
        )
        return participant


class CockpitPeriodResolutionTests(ReadinessTestCase):
    def test_cockpit_is_most_recent_ended_period_without_invoices(self):
        start, end = self._cockpit(FROZEN_TODAY)
        # FROZEN_TODAY is 2026-09-15: September is still running, so the
        # most recent ended monthly period is exactly August 2026.
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_fully_sent_period_is_skipped_in_favour_of_older_pending(self):
        from invoices.test_helpers import make_invoice

        newest_start, newest_end = self._cockpit(FROZEN_TODAY)
        _fill_readings(self.mp, newest_start, newest_end)
        make_invoice(
            self.zev, self.participant, InvoiceStatus.SENT, period=(newest_start, newest_end)
        )
        # Older period keeps a draft → cockpit moves there.
        older_start = period_starts(self.zev.start_date, "monthly", today=FROZEN_TODAY)[2]
        older_end = period_end(older_start, "monthly")
        make_invoice(
            self.zev, self.participant, InvoiceStatus.DRAFT, period=(older_start, older_end)
        )
        start, end = self._cockpit(FROZEN_TODAY)
        self.assertEqual((start, end), (older_start, older_end))

    def test_paid_period_is_done_not_a_gate(self):
        from invoices.test_helpers import make_invoice

        start, end = self._cockpit(FROZEN_TODAY)
        _fill_readings(self.mp, start, end)
        make_invoice(
            self.zev, self.participant, InvoiceStatus.PAID, period=(start, end)
        )
        # Paid newest period, no draft anywhere → the older ungenerated
        # period still needs Generate, so the cockpit moves there. Paid must
        # not pin the cockpit: only draft/approved gate, sent/paid/cancelled
        # count as done.
        older_start = period_starts(self.zev.start_date, "monthly", today=FROZEN_TODAY)[2]
        older_end = period_end(older_start, "monthly")
        _fill_readings(self.mp, older_start, older_end)
        self.assertEqual(resolve_cockpit_period(self.zev, FROZEN_TODAY), (older_start, older_end))

    def test_partially_generated_period_stays_on_the_cockpit(self):
        """One of two billable participants invoiced (and sent) must not let
        cockpit resolution skip the period: the other invoice is still owed."""
        from invoices.test_helpers import make_invoice

        second = self._add_billable_participant()
        _fill_readings(self.mp, date(2026, 8, 1), date(2026, 8, 31))
        # Only the first participant got an invoice; it is already sent.
        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.SENT,
            period=(date(2026, 8, 1), date(2026, 8, 31)),
        )
        cockpit = self._cockpit(FROZEN_TODAY)
        self.assertEqual(cockpit, (date(2026, 8, 1), date(2026, 8, 31)))
        # Once the second invoice exists the period is done and the cockpit
        # moves on to the next older period that still lacks an invoice.
        make_invoice(
            self.zev,
            second,
            InvoiceStatus.SENT,
            period=(date(2026, 8, 1), date(2026, 8, 31)),
        )
        cockpit = self._cockpit(FROZEN_TODAY)
        self.assertIsNotNone(cockpit)
        self.assertNotEqual(cockpit, (date(2026, 8, 1), date(2026, 8, 31)))

    def test_empty_zev_has_no_cockpit_period(self):
        empty = make_zev(self.other_owner, "Empty ZEV")
        empty.start_date = date(2026, 1, 1)
        empty.save()
        self.assertIsNone(resolve_cockpit_period(empty, FROZEN_TODAY))

    def test_cancelled_only_period_stays_open(self):
        """A cancelled invoice is not work: the period still needs Generate."""
        from invoices.test_helpers import make_invoice

        newest_start, newest_end = self._cockpit(FROZEN_TODAY)
        make_invoice(
            self.zev, self.participant, InvoiceStatus.CANCELLED,
            period=(newest_start, newest_end),
        )
        # The cancelled invoice must not close the period.
        self.assertEqual(self._cockpit(FROZEN_TODAY), (newest_start, newest_end))
        payload = compute_readiness(self.zev, newest_start, newest_end)
        generated = self._steps_by_key(payload)["generated"]
        self.assertEqual(generated["status"], "todo")
        self.assertEqual(generated["detail_data"]["missing"], 1)

    def test_cancelled_invoice_does_not_suppress_bulk_generated_prompt(self):
        """Single and bulk paths agree: cancelled-only means todo, not done."""
        from invoices.test_helpers import make_invoice

        start, end = date(2026, 8, 1), date(2026, 8, 31)
        make_invoice(
            self.zev, self.participant, InvoiceStatus.CANCELLED,
            period=(start, end),
        )
        single = self._steps_by_key(compute_readiness(self.zev, start, end))["generated"]
        bulk = compute_readiness_many(self.zev, [start])
        bulk_generated = next(s for s in bulk[0]["steps"] if s["key"] == "generated")
        self.assertEqual(single["status"], "todo")
        self.assertEqual(bulk_generated["status"], "todo")

    def test_invoice_cover_only_its_exact_period_after_interval_change(self):
        """A sent January invoice must not cover the Jan–Mar quarter after the
        ZEV switches to quarterly billing: coverage matches both period dates,
        so the quarter still needs its own invoices."""
        from invoices.test_helpers import make_invoice

        self.zev.billing_interval = "quarterly"
        self.zev.save()
        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.SENT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        # Jan–Mar is the only ended quarterly period; its invoices are missing.
        self.assertEqual(
            resolve_cockpit_period(self.zev, date(2026, 4, 15)),
            (date(2026, 1, 1), date(2026, 3, 31)),
        )

    def test_cockpit_never_resolves_to_a_period_predating_the_community(self):
        """A ZEV created mid-quarter has no partial first period: once the
        first valid quarter is fully sent, no pre-start quarter resurfaces."""
        from invoices.test_helpers import make_invoice

        zev = make_zev(self.owner, "Feb Start ZEV")
        zev.start_date = date(2026, 2, 15)
        zev.billing_interval = "quarterly"
        zev.save()
        participant = make_participant(zev, first="Feb")
        participant.valid_from = date(2026, 2, 15)
        participant.save()
        mp = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-FEB", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=date(2026, 2, 15)
        )
        # First billable period Apr–Jun fully sent, Jul–Sep still running.
        make_invoice(
            zev, participant, InvoiceStatus.SENT, period=(date(2026, 4, 1), date(2026, 6, 30))
        )
        self.assertIsNone(resolve_cockpit_period(zev, date(2026, 9, 15)))


class ReadinessComputationTests(ReadinessTestCase):
    def test_all_green_period_yields_generate_next_action(self):
        start, end = self._cockpit(FROZEN_TODAY)
        _fill_readings(self.mp, start, end)
        payload = compute_readiness(self.zev, start, end)
        statuses = {s["key"]: s["status"] for s in payload["steps"]}
        self.assertEqual(statuses["metering"], "ok")
        self.assertEqual(statuses["assignments"], "ok")
        self.assertEqual(statuses["tariffs"], "ok")
        self.assertEqual(statuses["generated"], "todo")
        self.assertEqual(payload["next_action"], "generate")

    def test_never_blocked_from_data_quality(self):
        start, end = self._cockpit(FROZEN_TODAY)
        # No readings at all → gaps, but status must be warn/todo, not blocked.
        payload = compute_readiness(self.zev, start, end)
        for step in payload["steps"]:
            self.assertIn(step["status"], ("ok", "warn", "todo", "done"))

    def test_metering_gaps_count_points_and_days(self):
        start, end = self._cockpit(FROZEN_TODAY)
        period_days = (end - start).days + 1
        _fill_readings(self.mp, start, start + timedelta(days=10))  # 11 days
        payload = compute_readiness(self.zev, start, end)
        metering = self._steps_by_key(payload)["metering"]
        self.assertEqual(metering["status"], "warn")
        self.assertEqual(metering["count"], 1)
        self.assertEqual(metering["total"], 1)
        self.assertIn("missing", metering["detail"])
        self.assertEqual(metering["detail_data"]["missing_days"], period_days - 11)

    def test_unassigned_readings_flag_assignment_gaps(self):
        start, end = self._cockpit(FROZEN_TODAY)
        _fill_readings(self.mp, start, end)
        # Add a second, unassigned meter with readings.
        orphan = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-RD-ORPHAN", meter_type=MeteringPointType.CONSUMPTION
        )
        _fill_readings(orphan, start, start + timedelta(days=2))
        payload = compute_readiness(self.zev, start, end)
        assignments = self._steps_by_key(payload)["assignments"]
        self.assertEqual(assignments["status"], "warn")
        self.assertEqual(assignments["count"], 3)
        self.assertEqual(payload["next_action"], "fix_assignments")

    def test_tariff_gap_ranges_appear_in_detail(self):
        start, end = self._cockpit(FROZEN_TODAY)
        _fill_readings(self.mp, start, end)
        self.tariff.valid_to = start + timedelta(days=4)
        self.tariff.save()
        payload = compute_readiness(self.zev, start, end)
        tariffs = self._steps_by_key(payload)["tariffs"]
        self.assertEqual(tariffs["status"], "warn")
        self.assertIn("..", tariffs["detail"])
        self.assertEqual(payload["next_action"], "fix_tariffs")

    def test_missing_tariff_is_todo_and_linked(self):
        self.tariff.delete()
        start, end = self._cockpit(FROZEN_TODAY)
        payload = compute_readiness(self.zev, start, end)
        tariffs = self._steps_by_key(payload)["tariffs"]
        self.assertEqual(tariffs["status"], "todo")
        self.assertEqual(tariffs["link"], "/tariffs")

    def test_workflow_statuses_follow_invoice_state(self):
        from invoices.test_helpers import make_invoice

        start, end = self._cockpit(FROZEN_TODAY)
        _fill_readings(self.mp, start, end)
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        inv.period_start = start
        inv.period_end = end
        inv.save()
        payload = compute_readiness(self.zev, start, end)
        by_key = self._steps_by_key(payload)
        self.assertEqual(by_key["generated"]["status"], "done")
        self.assertEqual(by_key["approved"]["status"], "todo")
        self.assertEqual(by_key["approved"]["count"], 1)
        self.assertEqual(payload["next_action"], "approve")

        inv.status = InvoiceStatus.APPROVED
        inv.save()
        payload = compute_readiness(self.zev, start, end)
        self.assertEqual(self._steps_by_key(payload)["sent"]["status"], "todo")
        self.assertEqual(payload["next_action"], "send")

        inv.status = InvoiceStatus.SENT
        inv.save()
        payload = compute_readiness(self.zev, start, end)
        self.assertEqual(self._steps_by_key(payload)["paid"]["status"], "todo")
        self.assertEqual(payload["next_action"], "track_payments")

        inv.status = InvoiceStatus.PAID
        inv.save()
        payload = compute_readiness(self.zev, start, end)
        self.assertEqual(payload["next_action"], "none")

    # -- partial generation & payment completeness ------------------------

    def test_missing_invoice_keeps_generate_open(self):
        """A draft for one of two billable participants leaves generate todo —
        the count is against the eligible participants, not the invoices that
        happen to exist."""
        from invoices.test_helpers import make_invoice

        self._add_billable_participant()
        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.DRAFT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )
        generated = steps["generated"]
        self.assertEqual(generated["status"], "todo")
        self.assertEqual(generated["count"], 1)
        self.assertEqual(generated["total"], 2)
        self.assertEqual(generated["detail_data"]["missing"], 1)
        self.assertIsNotNone(generated["link"])
        # The eligible participant whose invoice is missing is named.
        self.assertEqual(generated["detail_data"]["missing_participants"], ["Second Doe"])

    def test_generate_todo_survives_invoice_sending(self):
        """A batch that invoiced only part of the period is still pending once
        the one existing invoice is sent (the sent step must not hide it)."""
        from invoices.test_helpers import make_invoice

        self._add_billable_participant()
        for mp in MeteringPoint.objects.filter(zev=self.zev):
            _fill_readings(mp, date(2026, 1, 1), date(2026, 1, 31))
        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.SENT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        payload = compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(payload["next_action"], "generate")
        self.assertEqual(self._steps_by_key(payload)["generated"]["status"], "todo")

    def test_generated_done_when_every_billable_has_an_invoice(self):
        from invoices.test_helpers import make_invoice

        second = self._add_billable_participant()
        for participant in (self.participant, second):
            make_invoice(
                self.zev,
                participant,
                InvoiceStatus.DRAFT,
                period=(date(2026, 1, 1), date(2026, 1, 31)),
            )
        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )
        generated = steps["generated"]
        self.assertEqual(generated["status"], "done")
        self.assertEqual(generated["count"], 2)
        self.assertEqual(generated["total"], 2)

    def test_payment_not_done_while_any_active_invoice_unpaid(self):
        from invoices.test_helpers import make_invoice

        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.PAID,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        second = self._add_billable_participant()
        make_invoice(
            self.zev,
            second,
            InvoiceStatus.DRAFT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )
        self.assertEqual(steps["paid"]["status"], "todo")
        self.assertEqual(steps["paid"]["detail_data"]["unpaid"], 1)

    def test_payment_done_when_all_active_invoices_paid(self):
        from invoices.test_helpers import make_invoice

        second = self._add_billable_participant()
        for participant in (self.participant, second):
            make_invoice(
                self.zev,
                participant,
                InvoiceStatus.PAID,
                period=(date(2026, 1, 1), date(2026, 1, 31)),
            )
        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )
        self.assertEqual(steps["paid"]["status"], "done")

    # -- email delivery resolution ----------------------------------------

    def test_failed_email_delivery_counts_on_sent_step(self):
        from invoices.test_helpers import make_invoice

        start, end = self._cockpit(FROZEN_TODAY)
        _fill_readings(self.mp, start, end)
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        inv.period_start = start
        inv.period_end = end
        inv.save()
        EmailLog.objects.create(
            invoice=inv,
            recipient="ready@example.com",
            subject="Invoice",
            status=EmailLog.Status.FAILED,
            error_message="bounced",
        )
        payload = compute_readiness(self.zev, start, end)
        sent = self._steps_by_key(payload)["sent"]
        self.assertEqual(sent["failed"], 1)
        self.assertEqual(sent["status"], "todo")

    def test_successful_delivery_clears_the_failure(self):
        """A failed attempt followed by a successful delivery resolves the
        alert — the sent step and the attention list both clear."""
        from invoices.test_helpers import make_invoice

        start, end = self._cockpit(FROZEN_TODAY)
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        inv.period_start = start
        inv.period_end = end
        inv.save()
        EmailLog.objects.create(
            invoice=inv,
            recipient="ready@example.com",
            subject="Invoice",
            status=EmailLog.Status.FAILED,
            error_message="bounced",
        )
        EmailLog.objects.create(
            invoice=inv,
            recipient="ready@example.com",
            subject="Invoice",
            status=EmailLog.Status.SENT,
        )
        payload = compute_readiness(self.zev, start, end)
        sent = self._steps_by_key(payload)["sent"]
        self.assertEqual(sent["status"], "done")
        self.assertIsNone(sent.get("failed"))
        self.assertFalse(
            [i for i in compute_attention(self.zev, FROZEN_TODAY) if i["type"] == "email_failed"]
        )

    def test_repeated_failures_count_one_unresolved_invoice(self):
        from invoices.test_helpers import make_invoice

        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        inv.period_start = date(2026, 8, 1)
        inv.period_end = date(2026, 8, 31)
        inv.save()
        for _ in range(3):
            EmailLog.objects.create(
                invoice=inv,
                recipient="ready@example.com",
                subject="Invoice",
                status=EmailLog.Status.FAILED,
                error_message="bounced",
            )
        payload = compute_readiness(self.zev, date(2026, 8, 1), date(2026, 8, 31))
        sent = self._steps_by_key(payload)["sent"]
        self.assertEqual(sent["failed"], 1)
        failed = [i for i in compute_attention(self.zev, FROZEN_TODAY) if i["type"] == "email_failed"]
        self.assertEqual(len(failed), 1)

    # -- metering eligibility and count semantics -------------------------

    def test_expired_participant_not_counted_as_missing(self):
        """An assignment held by a participant whose validity ended before the
        period must not produce a missing-data warning (period-overview §5.5
        eligibility)."""
        self.participant.valid_to = date(2026, 1, 31)
        self.participant.save()
        step = _metering_step_for(self.zev, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(step["status"], "ok")
        self.assertEqual(step["count"], 0)

    def test_handover_counts_the_meter_once(self):
        """A meter handed over mid-period is one metering point: missing data
        is judged over the union of its assignment windows."""
        second = make_participant(self.zev, first="Hand", last="Over")
        MeteringPointAssignment.objects.filter(metering_point=self.mp).update(
            valid_to=date(2026, 1, 15)
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.mp,
            participant=second,
            valid_from=date(2026, 1, 16),
            valid_to=date(2026, 1, 31),
        )
        # Only the first holder's half has readings.
        _fill_readings(self.mp, date(2026, 1, 1), date(2026, 1, 15))
        step = _metering_step_for(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(step["status"], "warn")
        self.assertEqual(step["count"], 1)
        self.assertEqual(step["total"], 1)
        self.assertEqual(step["detail_data"]["missing_days"], 16)
        # Fill the second half too → complete, still one point.
        _fill_readings(self.mp, date(2026, 1, 16), date(2026, 1, 31))
        step = _metering_step_for(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(step["status"], "ok")
        self.assertEqual(step["count"], 0)

    def test_handover_of_two_meters_both_eligible(self):
        self._add_billable_participant()
        step = _metering_step_for(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(step["total"], 2)
        self.assertEqual(step["count"], 2)
        _fill_readings(self.mp, date(2026, 1, 1), date(2026, 1, 31))
        step = _metering_step_for(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        # One meter still uncovered → one point with gaps.
        self.assertEqual(step["count"], 1)
        _fill_readings(
            MeteringPoint.objects.get(zev=self.zev, meter_id="CH-RD-2"),
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        step = _metering_step_for(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(step["status"], "ok")


def _metering_step_for(zev, start, end):
    """Compute readiness and return the metering step dict."""
    payload = compute_readiness(zev, start, end)
    return next(step for step in payload["steps"] if step["key"] == "metering")


class ReadinessEndpointTests(ReadinessTestCase):
    def test_owner_gets_cockpit_form(self):
        auth(self.client, self.owner)
        response = self._readiness()
        self.assertEqual(response.status_code, 200)
        self.assertIn("period", response.data)
        self.assertIn("steps", response.data)
        self.assertIn("next_action", response.data)

    def test_admin_gets_cockpit_form(self):
        auth(self.client, self.admin)
        response = self._readiness()
        self.assertEqual(response.status_code, 200)

    def test_parameterless_default_clock_keeps_old_interval_leftovers(self):
        """A leftover draft from an earlier interval must not crash the
        parameterless endpoint: ``today`` defaults to the real clock there
        (regression for the TypeError the None default caused). Periods are
        built from the real clock so the fixture is calendar-independent."""
        from invoices.test_helpers import make_invoice

        real_today = date.today()
        # The most recently completed quarter, computed from the real clock.
        month_index = real_today.year * 12 + real_today.month - 1
        quarter_index = month_index - (month_index % 3) - 3
        q_year, q_month = divmod(quarter_index, 12)
        quarter_start = date(q_year, q_month + 1, 1)
        quarter_end = period_end(quarter_start, "quarterly")

        zev = make_zev(self.owner, "Default Clock ZEV")
        zev.start_date = quarter_start
        zev.billing_interval = "quarterly"
        zev.save()
        participant = make_participant(zev, first="Clock")
        mp = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-CLOCK", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=quarter_start
        )
        # The quarter is fully sent; a monthly leftover inside it stays draft.
        make_invoice(zev, participant, InvoiceStatus.SENT, period=(quarter_start, quarter_end))
        m_year, m_month = divmod(quarter_index + 1, 12)
        month_start = date(m_year, m_month + 1, 1)
        month_end = period_end(month_start, "monthly")
        make_invoice(zev, participant, InvoiceStatus.DRAFT, period=(month_start, month_end))

        auth(self.client, self.owner)
        response = self.client.get(
            "/api/v1/invoices/invoices/readiness/", {"zev_id": str(zev.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["period"]["start"], month_start.isoformat())
        self.assertEqual(response.data["period"]["end"], month_end.isoformat())

    def test_missing_zev_id_is_rejected(self):
        auth(self.client, self.owner)
        response = self.client.get("/api/v1/invoices/invoices/readiness/")
        self.assertEqual(response.status_code, 400)

    def test_malformed_uuid_is_a_client_error_not_500(self):
        auth(self.client, self.owner)
        response = self._readiness(zev_id="bad-uuid")
        self.assertEqual(response.status_code, 400)

    def test_unknown_zev_is_404(self):
        auth(self.client, self.owner)
        response = self.client.get(
            "/api/v1/invoices/invoices/readiness/", {"zev_id": "00000000-0000-0000-0000-000000000000"}
        )
        self.assertEqual(response.status_code, 404)

    def test_other_owner_is_403(self):
        auth(self.client, self.other_owner)
        response = self._readiness()
        self.assertEqual(response.status_code, 403)

    def test_participant_is_rejected_by_permission_class(self):
        auth(self.client, self.participant_user)
        response = self._readiness()
        self.assertEqual(response.status_code, 403)

    def test_explicit_period_form(self):
        auth(self.client, self.owner)
        response = self._readiness(period_start="2026-03-01", period_end="2026-03-31")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["period"]["start"], "2026-03-01")
        self.assertEqual(response.data["period"]["end"], "2026-03-31")

    def test_period_params_must_come_together(self):
        auth(self.client, self.owner)
        response = self._readiness(period_start="2026-03-01")
        self.assertEqual(response.status_code, 400)

    def test_reversed_period_is_rejected(self):
        auth(self.client, self.owner)
        response = self._readiness(period_start="2026-03-31", period_end="2026-03-01")
        self.assertEqual(response.status_code, 400)

    def test_bad_date_format_is_rejected(self):
        auth(self.client, self.owner)
        response = self._readiness(period_start="03/2026", period_end="03/2026")
        self.assertEqual(response.status_code, 400)

    def test_unsupported_date_bounds_are_rejected(self):
        """A period ending on 9999-12-31 overflows the period helpers
        (+1 day / +1 month) — it must be a 400, never a 500."""
        auth(self.client, self.owner)
        response = self._readiness(period_start="9999-12-31", period_end="9999-12-31")
        self.assertEqual(response.status_code, 400)
        response = self._readiness(period_start="1800-01-01", period_end="1800-01-31")
        self.assertEqual(response.status_code, 400)

    def test_periods_all_returns_list_newest_first_with_metadata(self):
        auth(self.client, self.owner)
        response = self._readiness(periods="all")
        self.assertEqual(response.status_code, 200)
        periods = response.data["periods"]
        self.assertTrue(len(periods) >= 1)
        starts = [entry["period"]["start"] for entry in periods]
        self.assertEqual(starts, sorted(starts, reverse=True))
        # The list is the full bounded history, never a silent 24-period cap.
        self.assertEqual(response.data["total_periods"], len(periods))
        self.assertEqual(
            response.data["history_from"],
            max(self.zev.start_date, date(2020, 1, 1)).isoformat(),
        )
        self.assertIs(response.data["truncated"], False)

    def test_periods_all_reports_truncation_for_pre_floor_zevs(self):
        """A ZEV predating the 2020 history floor is explicitly flagged as
        truncated instead of silently dropping its earliest periods."""
        self.zev.start_date = date(2019, 1, 1)
        self.zev.billing_interval = "annual"
        self.zev.save()
        auth(self.client, self.owner)
        response = self._readiness(periods="all")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["history_from"], "2020-01-01")
        self.assertIs(response.data["truncated"], True)
        self.assertEqual(
            response.data["total_periods"],
            len(period_starts(date(2020, 1, 1), "annual")),
        )

    def test_first_run_returns_setup_block_and_null_period(self):
        empty = make_zev(self.other_owner, "First Run ZEV")
        empty.start_date = date.today()
        empty.save()
        auth(self.client, self.other_owner)
        response = self.client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": str(empty.id)})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["period"])
        self.assertIn("setup", response.data)
        setup = response.data["setup"]
        self.assertEqual(setup["participants"], 0)
        self.assertEqual(setup["metering_points"], 0)
        self.assertEqual(setup["tariffs"], 0)

    def _previous_aligned_period(self, interval="monthly"):
        """The aligned period that ended most recently (always ended)."""
        starts = period_starts(date(2020, 1, 1), interval)
        start = starts[1]
        return start, period_end(start, interval)

    def _seed_sent_period(self, zev, participant, start, end):
        from invoices.test_helpers import make_invoice

        mp = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-CAUGHT", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=start
        )
        make_invoice(zev, participant, InvoiceStatus.SENT, period=(start, end))
        _fill_readings(mp, start, end)

    def test_finished_zev_is_caught_up_not_first_run(self):
        """All ended periods fully sent must NOT look like an empty community
        (period null + incomplete setup) — the cockpit shows the last period
        with `caught_up` and a completed setup block, so the dashboard never
        says "set up your ZEV" again."""
        start, end = self._previous_aligned_period()
        zev = make_zev(self.other_owner, "Caught Up ZEV")
        zev.start_date = start
        zev.save()
        participant = make_participant(zev)
        participant.valid_from = start
        participant.save()
        self._seed_sent_period(zev, participant, start, end)
        auth(self.client, self.other_owner)
        response = self.client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": str(zev.id)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["setup"]["complete"])
        self.assertIs(response.data["caught_up"], True)
        self.assertIsNotNone(response.data["period"])
        self.assertEqual(
            (response.data["period"]["start"], response.data["period"]["end"]),
            (start.isoformat(), end.isoformat()),
        )

    def test_brand_new_zev_waits_for_first_period(self):
        """Master data present but nothing has ended yet: a distinct state,
        not the first-run checklist and not a fabricated period. Setup
        guidance still rides along so missing assignments stay visible."""
        zev = make_zev(self.other_owner, "Brand New ZEV")
        zev.start_date = date.today()
        zev.save()
        make_participant(zev)
        MeteringPoint.objects.create(
            zev=zev, meter_id="CH-NEW", meter_type=MeteringPointType.CONSUMPTION
        )
        auth(self.client, self.other_owner)
        response = self.client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": str(zev.id)})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["period"])
        self.assertTrue(response.data["awaiting_first_period"])
        self.assertIsNotNone(response.data["setup"])

    def test_waiting_first_period_keeps_incomplete_setup(self):
        """A new community with no assignment and a blank IBAN gets the
        waiting message *with* both setup warnings, not instead of them."""
        real_today = date.today()
        month_start = date(real_today.year, real_today.month, 1)
        zev = make_zev(self.other_owner, "Waiting ZEV")
        zev.start_date = month_start
        zev.billing_interval = "monthly"
        zev.bank_iban = ""
        zev.save()
        make_participant(zev, first="Waiting")
        mp = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-WAIT", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.filter(metering_point=mp).delete()
        auth(self.client, self.other_owner)
        response = self.client.get(
            "/api/v1/invoices/invoices/readiness/", {"zev_id": str(zev.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["awaiting_first_period"])
        setup = response.data["setup"]
        self.assertFalse(setup["complete"])
        self.assertEqual(setup["reason"], "no_billable_assignment")
        self.assertFalse(setup["billing_settings_complete"])
        self.assertIs(response.data["awaiting_first_period"], True)

    def test_setup_block_reports_real_settings_completeness(self):
        """settings_complete is real (phase 3): the blank-able IBAN drives it.

        No factory sets bank_iban, so a default ZEV reports False — and a ZEV
        with an IBAN reports True. Pinned here because phase 2 hard-coded True.
        """
        empty = make_zev(self.other_owner, "No IBAN ZEV")
        auth(self.client, self.other_owner)
        response = self.client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": str(empty.id)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["setup"]["settings_complete"])

        empty.bank_iban = "CH93 0076 2011 6238 5295 7"
        empty.save()
        response = self.client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": str(empty.id)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["setup"]["settings_complete"])


class AttentionTests(ReadinessTestCase):
    def test_period_scoped_gaps_stay_in_the_cockpit(self):
        """Tariff coverage, cockpit data gaps and setup state are readiness-
        step concerns; attention carries only the cross-period items."""
        self.tariff.periods.all().delete()  # tariffs step → warn
        items = compute_attention(self.zev, FROZEN_TODAY)
        self.assertFalse(
            [
                i
                for i in items
                if i["type"]
                in {"tariff_missing", "metering_gaps", "assignment_gaps", "setup_incomplete"}
            ]
        )

    def test_failed_email_becomes_attention_item_with_period_ref(self):
        from invoices.test_helpers import make_invoice

        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        EmailLog.objects.create(
            invoice=inv,
            recipient="ready@example.com",
            subject="Invoice",
            status=EmailLog.Status.FAILED,
            error_message="bounced",
        )
        items = compute_attention(self.zev, FROZEN_TODAY)
        failed = [item for item in items if item["type"] == "email_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["invoice_id"], str(inv.id))
        self.assertEqual(failed[0]["id"], f"email_failed:{inv.id}")
        self.assertIsNotNone(failed[0]["period"])
        # The retry action lives on the period page, not the detail route.
        self.assertEqual(
            failed[0]["link"],
            f"/billing/invoices?period_start={inv.period_start.isoformat()}"
            f"&period_end={inv.period_end.isoformat()}",
        )

    def test_overdue_sent_invoice(self):
        from invoices.test_helpers import make_invoice

        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        inv.due_date = date(2026, 8, 1)
        inv.save()
        items = compute_attention(self.zev, FROZEN_TODAY)
        overdue = [item for item in items if item["type"] == "invoice_overdue"]
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["id"], f"invoice_overdue:{inv.id}")
        # The mark-paid action lives on the period page, not the detail route.
        self.assertEqual(
            overdue[0]["link"],
            f"/billing/invoices?period_start={inv.period_start.isoformat()}"
            f"&period_end={inv.period_end.isoformat()}",
        )

    def test_attention_ids_never_collide(self):
        """The same invoice as both an overdue and an unresolved email item,
        plus repeated failures, must yield distinct stable ids."""
        from invoices.test_helpers import make_invoice

        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        inv.due_date = date(2026, 8, 1)
        inv.save()
        for _ in range(2):
            EmailLog.objects.create(
                invoice=inv,
                recipient="ready@example.com",
                subject="Invoice",
                status=EmailLog.Status.FAILED,
                error_message="bounced",
            )
        ids = [item["id"] for item in compute_attention(self.zev, FROZEN_TODAY)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_expiring_participant_validity(self):
        self.participant.valid_to = date(2026, 9, 30)
        self.participant.save()
        items = compute_attention(self.zev, FROZEN_TODAY)
        validity = [item for item in items if item["type"] == "participant_validity"]
        self.assertEqual(len(validity), 1)
        self.assertIn("field=valid_to", validity[0]["link"])
        self.assertIs(validity[0]["expired"], False)

    def test_ended_participant_with_open_assignments(self):
        self.participant.valid_to = date(2026, 8, 31)
        self.participant.save()
        items = compute_attention(self.zev, FROZEN_TODAY)
        validity = [
            item
            for item in items
            if item["type"] == "participant_validity" and "still holds" in item["label"]
        ]
        self.assertEqual(len(validity), 1)
        self.assertIs(validity[0]["expired"], True)

    def test_ended_participant_with_finite_live_assignment_is_warned(self):
        """An ended participant whose assignment merely *ends later* (not
        open-ended) is still holding that meter after their validity ended."""
        self.participant.valid_to = date(2026, 8, 31)
        self.participant.save()
        MeteringPointAssignment.objects.filter(metering_point=self.mp).update(
            valid_to=date(2026, 12, 31)
        )
        items = compute_attention(self.zev, FROZEN_TODAY)
        validity = [item for item in items if item["type"] == "participant_validity"]
        self.assertEqual(len(validity), 1)
        self.assertIs(validity[0]["expired"], True)

    def test_ended_participant_with_contained_assignment_is_not_warned(self):
        """An assignment ending with (or before) the participant's validity is
        not "held after the end" — no warning."""
        self.participant.valid_to = date(2026, 8, 31)
        self.participant.save()
        MeteringPointAssignment.objects.filter(metering_point=self.mp).update(
            valid_to=date(2026, 8, 31)
        )
        items = compute_attention(self.zev, FROZEN_TODAY)
        validity = [item for item in items if item["type"] == "participant_validity"]
        self.assertEqual(validity, [])

    def test_attention_endpoint_rbac_and_shape(self):
        auth(self.client, self.owner)
        response = self.client.get("/api/v1/invoices/invoices/attention/", {"zev_id": str(self.zev.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["zev_id"], str(self.zev.id))
        self.assertIn("items", response.data)
        for item in response.data["items"]:
            self.assertIn(item["type"], (
                "email_failed", "invoice_overdue", "participant_validity",
            ))
            self.assertIn("link", item)
            self.assertIn("id", item)

        auth(self.client, self.other_owner)
        response = self.client.get("/api/v1/invoices/invoices/attention/", {"zev_id": str(self.zev.id)})
        self.assertEqual(response.status_code, 403)

        auth(self.client, self.participant_user)
        response = self.client.get("/api/v1/invoices/invoices/attention/", {"zev_id": str(self.zev.id)})
        self.assertEqual(response.status_code, 403)


class PeriodArithmeticTests(TestCase):
    """Month lengths, year rollover and every billing interval (spec §7)."""

    def test_monthly_ends(self):
        self.assertEqual(period_end(date(2026, 1, 1), "monthly"), date(2026, 1, 31))
        self.assertEqual(period_end(date(2026, 2, 1), "monthly"), date(2026, 2, 28))
        self.assertEqual(period_end(date(2028, 2, 1), "monthly"), date(2028, 2, 29))  # leap
        self.assertEqual(period_end(date(2026, 4, 1), "monthly"), date(2026, 4, 30))
        self.assertEqual(period_end(date(2026, 12, 1), "monthly"), date(2026, 12, 31))

    def test_interval_ends(self):
        self.assertEqual(period_end(date(2026, 7, 1), "quarterly"), date(2026, 9, 30))
        self.assertEqual(period_end(date(2026, 7, 1), "semi_annual"), date(2026, 12, 31))
        self.assertEqual(period_end(date(2026, 1, 1), "annual"), date(2026, 12, 31))

    def test_walkback_crosses_year_boundary_newest_first(self):
        starts = period_starts(date(2025, 11, 1), "monthly", months=3, today=date(2026, 1, 10))
        self.assertEqual(starts, [date(2026, 1, 1), date(2025, 12, 1), date(2025, 11, 1)])

    def test_partial_first_period_is_skipped(self):
        """The walk starts at the first aligned boundary on/after the start
        date — a community created mid-period never gets a period that begins
        before it existed (the frontend rejects those)."""
        # Created mid-February, quarterly: the containing Jan 1 period is
        # dropped, the first billable quarter is Apr 1.
        starts = period_starts(date(2026, 2, 15), "quarterly", today=date(2026, 9, 15))
        self.assertEqual(starts, [date(2026, 7, 1), date(2026, 4, 1)])
        # Monthly: February (Feb 1) precedes the Feb 15 start and is skipped.
        starts = period_starts(date(2026, 2, 15), "monthly", today=date(2026, 9, 15))
        self.assertEqual(starts[0], date(2026, 9, 1))
        self.assertNotIn(date(2026, 2, 1), starts)
        self.assertIn(date(2026, 3, 1), starts)
        # An aligned start keeps its own containing period.
        starts = period_starts(date(2026, 2, 1), "monthly", today=date(2026, 9, 15))
        self.assertIn(date(2026, 2, 1), starts)


class TariffPricingCoverageTests(ReadinessTestCase):
    """A tariff needs a usable price band, per energy type (review finding)."""

    def test_energy_tariff_without_bands_is_a_warn(self):
        # Remove every price band: validity alone must not read as covered.
        self.tariff.periods.all().delete()
        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )
        tariffs = steps["tariffs"]
        self.assertEqual(tariffs["status"], "warn")
        self.assertEqual(tariffs["count"], 31)
        # Attention no longer repeats the gap — the tariffs step owns it.
        items = compute_attention(self.zev, FROZEN_TODAY)
        self.assertFalse(any(item["type"] == "tariff_missing" for item in items))

    def test_one_energy_type_does_not_mask_another(self):
        # A second energy type with a tariff but no price bands leaves that
        # type unpriced even though LOCAL is fully priced.
        Tariff.objects.create(
            zev=self.zev,
            name="Grid",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )
        self.assertEqual(steps["tariffs"]["status"], "warn")
        # Once the second type is priced the period is covered again.
        grid = Tariff.objects.get(zev=self.zev, energy_type=EnergyType.GRID)
        TariffPeriod.objects.create(
            tariff=grid,
            period_type=PeriodType.FLAT,
            price_chf_per_kwh=Decimal("0.30000"),
        )
        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )
        self.assertEqual(steps["tariffs"]["status"], "ok")


class DynamicTariffPricingCoverageTests(ReadinessTestCase):
    """A dynamic tariff needs its fetched series to cover the period, not
    just a price band — the presence of a band tells you nothing about
    whether the series behind it was ever fetched (#530 part 2)."""

    def test_a_fully_covered_dynamic_tariff_is_ok(self):
        tariff, source = _dynamic_tariff(self.zev)
        _store_series(
            source, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )

        self.assertEqual(steps["tariffs"]["status"], "ok")

    def test_a_source_that_was_never_fetched_leaves_the_whole_period_uncovered(self):
        # A dynamic tariff exists and validates, but nothing was ever fetched
        # for it — the exact state right after configuring one.
        _dynamic_tariff(self.zev)

        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )

        self.assertEqual(steps["tariffs"]["status"], "warn")
        self.assertEqual(steps["tariffs"]["count"], 31)

    def test_a_gap_in_the_middle_of_the_series_is_reported_not_the_whole_period(self):
        tariff, source = _dynamic_tariff(self.zev)
        _store_series(
            source, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        _store_series(
            source, datetime(2026, 1, 15, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )

        self.assertEqual(steps["tariffs"]["status"], "warn")
        # Jan 10 through Jan 14, inclusive: five uncovered days.
        self.assertEqual(steps["tariffs"]["count"], 5)

    def test_a_priced_band_free_dynamic_tariff_still_masks_only_its_own_type(self):
        # LOCAL is fully covered by the fixture tariff; GRID is dynamic and
        # unfetched. One must not hide the other, matching the static case
        # already covered by TariffPricingCoverageTests.
        _dynamic_tariff(self.zev, energy_type=EnergyType.GRID)

        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )

        self.assertEqual(steps["tariffs"]["status"], "warn")
        self.assertEqual(steps["tariffs"]["count"], 31)

    def test_a_percentage_tariff_on_a_dynamic_grid_rate_needs_the_series_covered(self):
        # Mirrors the static percentage-tariff rule: a % tariff prices its
        # own type through the grid rate, so an uncovered dynamic grid series
        # leaves the percentage tariff's type unpriced too.
        _dynamic_tariff(self.zev, energy_type=EnergyType.GRID)
        pct = Tariff.objects.create(
            zev=self.zev, name="Levy", category=TariffCategory.LEVIES,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        pct.percentage = Decimal("50")
        pct.save()

        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )

        self.assertEqual(steps["tariffs"]["status"], "warn")

    def test_daylight_saving_does_not_read_as_a_gap(self):
        # A quarter-hourly day is 92 intervals in spring and 100 in autumn —
        # coverage here must come from the stored interval, not from a count,
        # exactly like tariffs.dynamic.fetch.coverage_gaps.
        tariff, source = _dynamic_tariff(self.zev, valid_from=date(2026, 3, 1))
        _store_series(
            source, datetime(2026, 3, 1, tzinfo=timezone.utc), datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 3, 1), date(2026, 3, 31))
        )

        self.assertEqual(steps["tariffs"]["status"], "ok")

    def test_a_static_and_a_dynamic_tariff_of_the_same_type_coexist(self):
        # Two versions of one series, one before and one after the operator
        # switched to dynamic pricing — exactly ADR 0018's static->dynamic
        # scenario, this time from the readiness side. Only GRID (or FEED_IN)
        # can be dynamic at all (§3.3's tariff-type mapping), so this uses a
        # dedicated grid series rather than the fixture's LOCAL tariff.
        static_grid = Tariff.objects.create(
            zev=self.zev, name="Grid", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1), valid_to=date(2026, 1, 15),
        )
        TariffPeriod.objects.create(
            tariff=static_grid, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal("0.20000"),
        )
        _tariff, source = _dynamic_tariff(self.zev, valid_from=date(2026, 1, 16), label="Grid")
        _store_series(
            source, datetime(2026, 1, 16, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        steps = self._steps_by_key(
            compute_readiness(self.zev, date(2026, 1, 1), date(2026, 1, 31))
        )

        self.assertEqual(steps["tariffs"]["status"], "ok")


class IntervalChangeTests(ReadinessTestCase):
    """Historical invoices stay visible after a billing-interval change."""

    def test_old_interval_pending_invoice_keeps_the_cockpit(self):
        from invoices.test_helpers import make_invoice

        zev = make_zev(self.owner, "Interval Switch ZEV")
        zev.start_date = date(2026, 1, 1)
        zev.billing_interval = "monthly"
        zev.save()
        participant = make_participant(zev, first="Switch")
        mp = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-SWITCH", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=date(2026, 1, 1)
        )
        # A monthly January draft predates the switch to quarterly billing.
        make_invoice(
            zev, participant, InvoiceStatus.DRAFT, period=(date(2026, 1, 1), date(2026, 1, 31))
        )
        # The first quarterly period is fully sent; only the leftover draft
        # (not aligned to any quarterly period) is still open.
        make_invoice(
            zev, participant, InvoiceStatus.SENT, period=(date(2026, 1, 1), date(2026, 3, 31))
        )
        zev.billing_interval = "quarterly"
        zev.save()
        self.assertEqual(
            resolve_cockpit_period(zev, date(2026, 4, 15)),
            (date(2026, 1, 1), date(2026, 1, 31)),
        )

    def test_leftover_pending_outranks_an_older_ungenerated_quarter(self):
        """A newer leftover draft (May, monthly) must win over the older
        ungenerated Jan–Mar quarter: aligned and leftover candidates merge
        before the most recent one is chosen."""
        from invoices.test_helpers import make_invoice

        zev = make_zev(self.owner, "Priority ZEV")
        zev.start_date = date(2026, 1, 1)
        zev.billing_interval = "monthly"
        zev.save()
        participant = make_participant(zev, first="Priority")
        mp = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-PRIO", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=date(2026, 1, 1)
        )
        make_invoice(
            zev, participant, InvoiceStatus.DRAFT, period=(date(2026, 5, 1), date(2026, 5, 31))
        )
        zev.billing_interval = "quarterly"
        zev.save()
        # Jan–Mar was never generated; Apr–Jun is fully sent.
        make_invoice(
            zev, participant, InvoiceStatus.SENT, period=(date(2026, 4, 1), date(2026, 6, 30))
        )
        self.assertEqual(
            resolve_cockpit_period(zev, date(2026, 9, 15)),
            (date(2026, 5, 1), date(2026, 5, 31)),
        )

    def test_no_ended_period_under_the_new_interval_keeps_leftovers(self):
        """Switching to annual mid-year leaves the running annual period
        unended; the ended monthly leftover must still resolve instead of
        reporting no cockpit period at all."""
        from invoices.test_helpers import make_invoice

        zev = make_zev(self.owner, "Annual Switch ZEV")
        zev.start_date = date(2026, 1, 1)
        zev.billing_interval = "monthly"
        zev.save()
        participant = make_participant(zev, first="Annual")
        mp = MeteringPoint.objects.create(
            zev=zev, meter_id="CH-ANN", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=date(2026, 1, 1)
        )
        make_invoice(
            zev, participant, InvoiceStatus.DRAFT, period=(date(2026, 7, 1), date(2026, 7, 31))
        )
        zev.billing_interval = "annual"
        zev.save()
        self.assertEqual(
            resolve_cockpit_period(zev, date(2026, 9, 15)),
            (date(2026, 7, 1), date(2026, 7, 31)),
        )


class BulkReadinessTests(ReadinessTestCase):
    """`periods=all` must match the per-period path from one dataset."""

    def _seed_mixed_periods(self):
        from invoices.test_helpers import make_invoice

        july = (date(2026, 7, 1), date(2026, 7, 31))
        august = (date(2026, 8, 1), date(2026, 8, 31))
        _fill_readings(self.mp, *july)
        _fill_readings(self.mp, *august)
        # July: nothing generated → generate open.
        # August: a sent invoice with an unresolved email failure, plus an
        # orphan meter reading → sent/paid open and assignments warn.
        inv = make_invoice(self.zev, self.participant, InvoiceStatus.SENT, period=august)
        EmailLog.objects.create(
            invoice=inv,
            recipient="ready@example.com",
            subject="Invoice",
            status=EmailLog.Status.FAILED,
            error_message="bounced",
        )
        orphan = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-BULK", meter_type=MeteringPointType.CONSUMPTION
        )
        _fill_readings(orphan, date(2026, 8, 1), date(2026, 8, 2))
        # A second reading on the same day: assignment totals count readings,
        # not days, so bulk must report 3 orphan readings for Aug 1–2.
        MeterReading.objects.create(
            metering_point=orphan,
            timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )
        return july, august

    def test_bulk_matches_single_period_readiness(self):
        july, august = self._seed_mixed_periods()
        entries = compute_readiness_many(self.zev, [august[0], july[0]])
        self.assertEqual(len(entries), 2)
        # Three orphan readings on Aug 1–2 (two on the first day) count as
        # three in both paths — bulk must not collapse them into days.
        self.assertEqual(
            next(s for s in compute_readiness(self.zev, *august)["steps"] if s["key"] == "assignments")["count"],
            3,
        )
        self.assertEqual(entries[0], compute_readiness(self.zev, *august))
        self.assertEqual(entries[1], compute_readiness(self.zev, *july))

    def test_bulk_email_failures_match_single_for_every_invoice_status(self):
        from invoices.test_helpers import make_invoice

        period = (date(2026, 8, 1), date(2026, 8, 31))
        for status in InvoiceStatus.values:
            with self.subTest(status=status):
                invoice = make_invoice(self.zev, self.participant, status, period=period)
                EmailLog.objects.create(
                    invoice=invoice, recipient="ready@example.com", subject="Invoice",
                    status=EmailLog.Status.FAILED,
                )
                self.assertEqual(
                    compute_readiness_many(self.zev, [period[0]])[0],
                    compute_readiness(self.zev, *period),
                )
                invoice.delete()

    def test_bulk_keeps_failure_on_older_active_duplicate_invoice(self):
        from invoices.test_helpers import make_invoice

        period = (date(2026, 8, 1), date(2026, 8, 31))
        older = make_invoice(self.zev, self.participant, InvoiceStatus.SENT, period=period)
        EmailLog.objects.create(
            invoice=older, recipient="ready@example.com", subject="Invoice",
            status=EmailLog.Status.FAILED,
        )
        make_invoice(self.zev, self.participant, InvoiceStatus.SENT, period=period)
        single = compute_readiness(self.zev, *period)
        self.assertEqual(compute_readiness_many(self.zev, [period[0]])[0], single)
        self.assertEqual(next(s for s in single["steps"] if s["key"] == "sent")["failed"], 1)

    def test_bulk_query_count_is_constant(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._seed_mixed_periods()
        # All nine months the fixture community has lived through: a naive
        # per-period walk would issue ~7 queries a period (~60+ here).
        starts = period_starts(date(2026, 1, 1), "monthly", today=date(2026, 9, 15))
        self.assertEqual(len(starts), 9)
        with CaptureQueriesContext(connection) as captured:
            entries = compute_readiness_many(self.zev, starts)
        self.assertEqual(len(entries), 9)
        # One dataset for the whole run — a constant, not per-period, budget.
        self.assertLessEqual(len(captured), 15)


class EndpointParamValidationTests(ReadinessTestCase):
    """Strict date format and bounded explicit ranges (review finding)."""

    def setUp(self):
        super().setUp()
        auth(self.client, self.owner)

    def test_period_dates_must_be_strict_iso(self):
        response = self.client.get(
            "/api/v1/invoices/invoices/readiness/",
            {"zev_id": str(self.zev.id), "period_start": "20260801", "period_end": "20260831"},
        )
        self.assertEqual(response.status_code, 400)

    def test_explicit_range_may_not_span_decades(self):
        response = self.client.get(
            "/api/v1/invoices/invoices/readiness/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2020-01-01",
                "period_end": "2026-01-01",
            },
        )
        self.assertEqual(response.status_code, 400)


class TariffPercentageCoverageTests(ReadinessTestCase):
    """Percentage tariffs belong to the energy-type coverage semantics: an
    expired percentage tariff must leave its type uncovered, and a valid one
    prices it through the grid rate (review finding)."""

    def _grid_direct(self):
        grid = Tariff.objects.create(
            zev=self.zev,
            name="Grid",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=grid,
            period_type=PeriodType.FLAT,
            price_chf_per_kwh=Decimal("0.20000"),
        )
        return grid

    def _tariffs_step(self, period_start, period_end):
        return next(
            s
            for s in compute_readiness(self.zev, period_start, period_end)["steps"]
            if s["key"] == "tariffs"
        )

    def test_expired_percentage_tariff_leaves_its_energy_type_uncovered(self):
        self.tariff.energy_type = EnergyType.GRID
        self.tariff.save()
        Tariff.objects.create(
            zev=self.zev,
            name="Local percent (expired)",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.LOCAL,
            percentage=Decimal("80"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 7, 31),
        )
        step = self._tariffs_step(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(step["status"], "warn")
        self.assertEqual(step["count"], 31)
        # Bulk must agree, and the running August window must warn too.
        bulk = compute_readiness_many(self.zev, [date(2026, 8, 1)])[0]
        bulk_step = next(s for s in bulk["steps"] if s["key"] == "tariffs")
        self.assertEqual(bulk_step, step)
        attention = compute_attention(self.zev, today=date(2026, 8, 15))
        self.assertFalse(any(i["type"] == "tariff_missing" for i in attention))

    def test_valid_percentage_tariff_prices_its_type_through_the_grid(self):
        self.tariff.valid_to = date(2026, 7, 31)
        self.tariff.save()
        self._grid_direct()
        Tariff.objects.create(
            zev=self.zev,
            name="Local percent",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.LOCAL,
            percentage=Decimal("80"),
            valid_from=date(2026, 8, 1),
        )
        step = self._tariffs_step(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(step["status"], "ok")
        attention = compute_attention(self.zev, today=date(2026, 8, 15))
        self.assertFalse(any(i["type"] == "tariff_missing" for i in attention))


class IntervalSettledCoverageTests(ReadinessTestCase):
    """Interval changes must not mint regeneration work the engine refuses:
    sent/paid invoices from the previous interval settle the new period when
    they cover it day-for-day (review finding)."""

    def _pay_monthly(self, start_month, end_month):
        from invoices.test_helpers import make_invoice
        from calendar import monthrange

        for month in range(start_month, end_month + 1):
            end_day = monthrange(2026, month)[1]
            make_invoice(
                self.zev,
                self.participant,
                InvoiceStatus.PAID,
                period=(date(2026, month, 1), date(2026, month, end_day)),
            )

    def test_fully_settled_period_stays_closed_after_interval_change(self):
        self._pay_monthly(1, 6)
        self.zev.billing_interval = "quarterly"
        self.zev.save()
        self.assertIsNone(resolve_cockpit_period(self.zev, date(2026, 7, 15)))
        _fill_readings(self.mp, date(2026, 4, 1), date(2026, 6, 30))
        readiness = compute_readiness(self.zev, date(2026, 4, 1), date(2026, 6, 30))
        steps = {s["key"]: s["status"] for s in readiness["steps"]}
        self.assertEqual(steps["generated"], "done")
        self.assertNotEqual(readiness["next_action"], "generate")

    def test_partially_settled_period_is_a_conflict(self):
        # Only January and February are paid; March is not — Jan–Mar is not
        # settled day-for-day, and the engine refuses a quarterly regeneration
        # over the locked months, so the quarter is an explicit conflict (not
        # ordinary generation). The cockpit still resolves to the newest open
        # period (Apr–Jun, untouched).
        self._pay_monthly(1, 2)
        self.zev.billing_interval = "quarterly"
        self.zev.save()
        self.assertEqual(
            resolve_cockpit_period(self.zev, date(2026, 7, 15)),
            (date(2026, 4, 1), date(2026, 6, 30)),
        )
        _fill_readings(self.mp, date(2026, 1, 1), date(2026, 3, 31))
        readiness = compute_readiness(self.zev, date(2026, 1, 1), date(2026, 3, 31))
        steps = {s["key"]: s for s in readiness["steps"]}
        self.assertEqual(steps["generated"]["status"], "done")
        self.assertEqual(steps["generation_conflicts"]["status"], "warn")
        self.assertEqual(
            steps["generation_conflicts"]["detail_data"]["conflict_count"], 1
        )
        self.assertEqual(
            readiness["next_action"], "review_generation_conflicts"
        )

    def test_leftover_draft_is_never_settled_by_paid_subperiods(self):
        # A genuine monthly draft in April is still pending work even though
        # the Apr–Jun quarter looks settled under the new interval.
        from invoices.test_helpers import make_invoice

        self._pay_monthly(1, 6)
        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.DRAFT,
            period=(date(2026, 4, 1), date(2026, 4, 30)),
        )
        self.zev.billing_interval = "quarterly"
        self.zev.save()
        self.assertEqual(
            resolve_cockpit_period(self.zev, date(2026, 7, 15)),
            (date(2026, 4, 1), date(2026, 4, 30)),
        )


class InvoiceSelectionParityTests(ReadinessTestCase):
    """Single and bulk readiness select the same invoice when duplicates for
    one participant/period exist (newest wins, deterministically)."""

    def test_bulk_matches_single_for_duplicate_period_invoices(self):
        from invoices.test_helpers import make_invoice

        period = (date(2026, 8, 1), date(2026, 8, 31))
        make_invoice(self.zev, self.participant, InvoiceStatus.SENT, period=period)
        make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT, period=period)
        single = compute_readiness(self.zev, *period)
        bulk = compute_readiness_many(self.zev, [period[0]])[0]
        self.assertEqual(single, bulk)
        steps = {s["key"]: s for s in single["steps"]}
        # The newer draft governs: approval is pending, not silently done.
        self.assertEqual(steps["approved"]["status"], "todo")
        self.assertEqual(steps["approved"]["count"], 1)


class AttentionDestinationTests(ReadinessTestCase):
    """Invoice items must stay reachable after their assignment is removed:
    the period overview keeps rows for participants that hold invoices."""

    def test_overdue_invoice_keeps_its_row_without_an_assignment(self):
        from invoices.test_helpers import make_invoice
        from invoices.period_overview import compute_period_overview

        period = (date(2026, 8, 1), date(2026, 8, 31))
        invoice = make_invoice(self.zev, self.participant, InvoiceStatus.SENT, period=period)
        invoice.due_date = date(2026, 9, 1)
        invoice.save()
        MeteringPointAssignment.objects.all().delete()

        items = compute_attention(self.zev, today=date(2026, 9, 15))
        overdue = next(i for i in items if i["type"] == "invoice_overdue")
        rows = compute_period_overview(
            zev=self.zev, period_start=period[0], period_end=period[1], request=None
        )
        self.assertTrue(any(r["invoice"]["id"] == str(invoice.id) for r in rows))
        self.assertEqual(overdue["period"]["start"], period[0].isoformat())


class AttentionEmailLimitTests(ReadinessTestCase):
    """The 20-item cap on failed-email attention applies after sorting by
    recency — never to an arbitrary slice of invoices."""

    def test_failed_email_limit_is_by_recency_not_invoice_order(self):
        from invoices.test_helpers import make_invoice

        created_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        for index in range(25):
            invoice = make_invoice(
                self.zev, self.participant, InvoiceStatus.SENT,
                period=(date(2026, 8, 1), date(2026, 8, 31)),
            )
            invoice.due_date = date(2026, 9, 1)
            invoice.save()
            log = EmailLog.objects.create(
                invoice=invoice,
                recipient="mail@example.com",
                subject="Invoice",
                status=EmailLog.Status.FAILED,
                error_message="bounced",
            )
            # Stagger attempt times so recency is unambiguous.
            EmailLog.objects.filter(pk=log.pk).update(created_at=created_at)
            created_at += timedelta(minutes=1)

        items = compute_attention(self.zev, today=date(2026, 9, 15))
        failed = [i for i in items if i["type"] == "email_failed"]
        self.assertEqual(len(failed), 20)
        # Newest 20 by attempt time (the five earliest attempts fall off),
        # descending — not whichever invoices came first in id order.
        timestamps = [
            EmailLog.objects.get(invoice_id=i["invoice_id"]).created_at
            for i in failed
        ]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        self.assertEqual(
            timestamps[-1],
            datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc),
        )


class AttentionOverdueLimitTests(ReadinessTestCase):
    """Overdue items are capped at 20, most overdue due date first (spec §7)."""

    def test_overdue_items_capped_at_20_most_overdue_first(self):
        from invoices.test_helpers import make_invoice

        for index in range(25):
            invoice = make_invoice(
                self.zev, self.participant, InvoiceStatus.SENT,
                period=(date(2026, 8, 1), date(2026, 8, 31)),
            )
            invoice.due_date = date(2026, 8, 1) + timedelta(days=index)
            invoice.save()
        items = compute_attention(self.zev, today=date(2026, 9, 15))
        overdue = [i for i in items if i["type"] == "invoice_overdue"]
        self.assertEqual(len(overdue), 20)
        due_dates = [i["due_date"] for i in overdue]
        self.assertEqual(due_dates, sorted(due_dates))
        self.assertEqual(due_dates[0], "2026-08-01")
        self.assertNotIn("2026-08-25", due_dates)


class AttentionQueryBudgetTests(ReadinessTestCase):
    """Attention must not grow a query per invoice it reports (review finding:
    five overdue invoices caused five extra ZEV fetches)."""

    def test_overdue_invoices_do_not_reload_the_zev(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from invoices.test_helpers import make_invoice

        for _index in range(5):
            invoice = make_invoice(
                self.zev, self.participant, InvoiceStatus.SENT,
                period=(date(2026, 8, 1), date(2026, 8, 31)),
            )
            invoice.due_date = date(2026, 9, 1)
            invoice.save()
        with CaptureQueriesContext(connection) as captured:
            items = compute_attention(self.zev, today=date(2026, 9, 15))
        self.assertEqual(len([i for i in items if i["type"] == "invoice_overdue"]), 5)
        zev_fetches = [q for q in captured if 'FROM "zev_zev"' in q["sql"]]
        self.assertEqual(len(zev_fetches), 0)


class PeriodOverviewQueryBudgetTests(ReadinessTestCase):
    """The polled period overview serializes full invoices without a query per
    row or per email log (prefetch + last_email_status annotation)."""

    def test_overview_stays_constant_as_invoices_grow(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from invoices.period_overview import compute_period_overview
        from invoices.test_helpers import make_invoice

        for _index in range(3):
            invoice = make_invoice(
                self.zev, self.participant, InvoiceStatus.SENT,
                period=(date(2026, 8, 1), date(2026, 8, 31)),
            )
            EmailLog.objects.create(
                invoice=invoice,
                recipient="paid@example.com",
                subject="Invoice",
                status=EmailLog.Status.SENT,
            )
        period = (date(2026, 8, 1), date(2026, 8, 31))
        with CaptureQueriesContext(connection) as captured:
            rows = compute_period_overview(
                zev=self.zev, period_start=period[0], period_end=period[1], request=None
            )
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["invoice"])
        self.assertEqual(len(rows[0]["invoice"]["email_logs"]), 1)
        # Same participant serialised three times over: bounded queries, not
        # one extra lookup per invoice per poll.
        self.assertLessEqual(len(captured), 10)


class GenerationConflictTests(ReadinessTestCase):
    """A locked sub-period invoice must surface as a conflict, never as an
    ordinary executable generation recommendation."""

    def _quarter_with_paid_january(self):
        from invoices.test_helpers import make_invoice

        self.zev.billing_interval = "quarterly"
        self.zev.save()
        paid = make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.PAID,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        start, end = date(2026, 1, 1), date(2026, 3, 31)
        _fill_readings(self.mp, start, end)
        return paid, start, end

    def test_partial_paid_settlement_is_a_conflict_not_generate(self):
        paid, start, end = self._quarter_with_paid_january()
        payload = compute_readiness(self.zev, start, end)
        self.assertEqual(payload["next_action"], "review_generation_conflicts")
        step = self._steps_by_key(payload)["generation_conflicts"]
        self.assertEqual(step["status"], "warn")
        conflicts = step["detail_data"]["conflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["participant_id"], str(self.participant.id))
        self.assertEqual(
            [inv["number"] for inv in conflicts[0]["invoices"]],
            [paid.invoice_number],
        )
        self.assertEqual(conflicts[0]["invoices"][0]["status"], "paid")

    def test_generation_attempt_still_refuses_and_preserves_the_invoice(self):
        from invoices.engine import generate_invoice
        from invoices.models import InvoiceItem

        paid, start, end = self._quarter_with_paid_january()
        items_before = InvoiceItem.objects.filter(invoice=paid).count()
        with self.assertRaises(ValueError):
            generate_invoice(self.participant, start, end)
        paid.refresh_from_db()
        self.assertEqual(paid.status, InvoiceStatus.PAID)
        self.assertEqual(InvoiceItem.objects.filter(invoice=paid).count(), items_before)
        self.assertFalse(
            Invoice.objects.filter(
                zev=self.zev, participant=self.participant,
                period_start=start, period_end=end,
            ).exists()
        )

    def test_draft_overlap_keeps_ordinary_generation(self):
        from invoices.test_helpers import make_invoice

        self.zev.billing_interval = "quarterly"
        self.zev.save()
        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.DRAFT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        start, end = date(2026, 1, 1), date(2026, 3, 31)
        _fill_readings(self.mp, start, end)
        payload = compute_readiness(self.zev, start, end)
        self.assertEqual(payload["next_action"], "generate")
        self.assertEqual(
            self._steps_by_key(payload)["generation_conflicts"]["status"], "ok"
        )

    def test_mixed_participants_keep_valid_work_beside_the_conflict(self):
        paid, start, end = self._quarter_with_paid_january()
        second = self._add_billable_participant()
        _fill_readings(
            MeteringPoint.objects.get(zev=self.zev, meter_id="CH-RD-2"), start, end
        )
        payload = compute_readiness(self.zev, start, end)
        self.assertEqual(payload["next_action"], "review_generation_conflicts")
        generated = self._steps_by_key(payload)["generated"]
        self.assertEqual(generated["status"], "todo")
        self.assertEqual(
            generated["detail_data"]["missing_participants"], [second.full_name]
        )


class HistoricalPeriodListTests(ReadinessTestCase):
    """Interval changes must not hide exact historical invoice periods."""

    def test_list_marks_running_period_separately_from_ended_periods(self):
        entries = compute_period_list(self.zev, today=FROZEN_TODAY)
        by_dates = {
            (entry["period"]["start"], entry["period"]["end"]): entry["period"]
            for entry in entries
        }
        self.assertFalse(by_dates[("2026-09-01", "2026-09-30")]["ended"])
        self.assertTrue(by_dates[("2026-08-01", "2026-08-31")]["ended"])

    def test_monthly_invoice_period_survives_quarterly_switch(self):
        from invoices.test_helpers import make_invoice

        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.DRAFT,
            period=(date(2026, 2, 1), date(2026, 2, 28)),
        )
        self.zev.billing_interval = "quarterly"
        self.zev.save()
        auth(self.client, self.owner)
        response = self._readiness(periods="all")
        self.assertEqual(response.status_code, 200)
        entries = {
            (entry["period"]["start"], entry["period"]["end"]): entry
            for entry in response.data["periods"]
        }
        self.assertIn(("2026-02-01", "2026-02-28"), entries)
        historical = entries[("2026-02-01", "2026-02-28")]
        self.assertEqual(historical["period"]["source"], "invoice")
        explicit = compute_readiness(self.zev, date(2026, 2, 1), date(2026, 2, 28))
        self.assertEqual(historical["steps"], explicit["steps"])
        self.assertEqual(historical["next_action"], explicit["next_action"])

    def test_two_periods_sharing_a_start_coexist(self):
        from invoices.test_helpers import make_invoice

        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.SENT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        make_invoice(
            self.zev,
            self.participant,
            InvoiceStatus.SENT,
            period=(date(2026, 1, 1), date(2026, 3, 31)),
        )
        self.zev.billing_interval = "quarterly"
        self.zev.save()
        auth(self.client, self.owner)
        response = self._readiness(periods="all")
        periods = {
            (entry["period"]["start"], entry["period"]["end"])
            for entry in response.data["periods"]
        }
        self.assertIn(("2026-01-01", "2026-01-31"), periods)
        self.assertIn(("2026-01-01", "2026-03-31"), periods)

    def test_list_stays_newest_first_by_end_then_start(self):
        from invoices.test_helpers import make_invoice

        make_invoice(
            self.zev, self.participant, InvoiceStatus.DRAFT,
            period=(date(2026, 2, 1), date(2026, 2, 28)),
        )
        self.zev.billing_interval = "quarterly"
        self.zev.save()
        auth(self.client, self.owner)
        response = self._readiness(periods="all")
        keys = [
            (entry["period"]["end"], entry["period"]["start"])
            for entry in response.data["periods"]
        ]
        self.assertEqual(keys, sorted(keys, reverse=True))
        self.assertEqual(
            response.data["total_periods"], len(response.data["periods"])
        )

    def test_list_query_count_is_stable_as_history_grows(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from invoices.test_helpers import make_invoice

        make_invoice(
            self.zev, self.participant, InvoiceStatus.SENT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        auth(self.client, self.owner)
        with CaptureQueriesContext(connection) as first:
            self._readiness(periods="all")
        second = self._add_billable_participant()
        make_invoice(
            self.zev, second, InvoiceStatus.SENT,
            period=(date(2026, 2, 1), date(2026, 2, 28)),
        )
        make_invoice(
            self.zev, second, InvoiceStatus.DRAFT,
            period=(date(2026, 3, 1), date(2026, 3, 31)),
        )
        with CaptureQueriesContext(connection) as second_run:
            self._readiness(periods="all")
        self.assertLessEqual(len(second_run), len(first) + 2)


class InitialSetupGuidanceTests(ReadinessTestCase):
    """An unassigned setup must not report billing as fully completed."""

    def test_unassigned_setup_is_not_caught_up(self):
        MeteringPointAssignment.objects.filter(participant=self.participant).delete()
        auth(self.client, self.owner)
        response = self._readiness()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data.get("caught_up"))
        setup = response.data.get("setup")
        self.assertIsNotNone(setup)
        self.assertFalse(setup["complete"])
        self.assertEqual(setup["assignment_link"], "/metering/points")

    def test_blank_iban_stays_discoverable_with_normal_master_data(self):
        self.zev.bank_iban = ""
        self.zev.save()
        auth(self.client, self.owner)
        response = self._readiness()
        self.assertEqual(response.status_code, 200)
        setup = response.data.get("setup")
        self.assertIsNotNone(setup)
        self.assertFalse(setup["billing_settings_complete"])
        self.assertEqual(setup["billing_settings_link"], "/zev-settings/billing")

    def test_completed_setup_clears_the_guidance(self):
        MeteringPointAssignment.objects.filter(participant=self.participant).delete()
        auth(self.client, self.owner)
        self.assertFalse(self._readiness().data["setup"]["complete"])
        MeteringPointAssignment.objects.create(
            metering_point=self.mp, participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        self.zev.bank_iban = "CH9300762011623852957"
        self.zev.save()
        setup = self._readiness().data["setup"]
        self.assertTrue(setup["complete"])
        self.assertIsNone(setup["reason"])
        self.assertTrue(setup["billing_settings_complete"])

    def test_historical_zero_billable_period_is_not_a_setup_gap(self):
        # The participant joins in June; the ended January period has no
        # billable work and must not flag setup — explicit periods never
        # carry the guidance block.
        self.participant.valid_from = date(2026, 6, 1)
        self.participant.save()
        auth(self.client, self.owner)
        response = self._readiness(period_start="2026-01-01", period_end="2026-01-31")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("setup", response.data)
        steps = {step["key"]: step for step in response.data["steps"]}
        self.assertEqual(steps["generated"]["status"], "done")

    def test_other_owner_cannot_read_conflict_identities(self):
        from invoices.test_helpers import make_invoice

        self.zev.billing_interval = "quarterly"
        self.zev.save()
        make_invoice(
            self.zev, self.participant, InvoiceStatus.PAID,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        auth(self.client, self.other_owner)
        response = self._readiness(period_start="2026-01-01", period_end="2026-03-31")
        self.assertEqual(response.status_code, 403)
