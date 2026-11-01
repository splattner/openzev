"""The Solar Manager client and provider of SPEC §6.2, against a local stand-in for the vendor."""

import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.models import FeatureFlag
from allocation.validity import period_start_dt
from metering import tasks
from metering.models import SupplementarySource
from metering.supplementary import crypto, solar_manager
from metering.supplementary.providers import ProviderAuthError, ProviderError, ProviderRateLimited
from metering.supplementary.solar_manager import SolarManagerClient, SolarManagerProvider, civil_days, map_points
from metering.supplementary.testing import (
    INTEGRATION_KEY,
    SOURCES_URL,
    StubSolarManager,
    SupplementaryApiTestCase,
    client_for,
    vendor_row,
)
from testing import factories
from zev.models import MeteringPointAssignment, MeteringPointType

UTC = dt_timezone.utc
START = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)


class StubbedTestCase(TestCase):
    def setUp(self):
        self.vendor = StubSolarManager().start()
        self.addCleanup(self.vendor.stop)
        override = override_settings(SOLAR_MANAGER_BASE_URL=self.vendor.url, INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
        override.enable()
        self.addCleanup(override.disable)
        self.client_ = SolarManagerClient()


class ClientTests(StubbedTestCase):
    def test_refresh_sends_the_grant_and_returns_the_rotated_token(self):
        access, keep = self.client_.refresh("key-1")
        self.assertEqual(access, "access-1")
        self.assertEqual(keep, "key-2")
        self.assertEqual(self.vendor.refresh_requests, [{"grant_type": "refresh_token", "refresh_token": "key-1"}])

    def test_refresh_keeps_the_old_token_when_the_vendor_does_not_rotate(self):
        self.vendor.rotate = False
        self.assertEqual(self.client_.refresh("key-1")[1], "key-1")

    def test_a_rejected_key_is_an_auth_error_that_does_not_echo_the_key(self):
        with self.assertRaises(ProviderAuthError) as caught:
            self.client_.refresh("not-the-key")
        self.assertNotIn("not-the-key", str(caught.exception))

    def test_a_400_from_refresh_means_the_key_is_malformed(self):
        self.vendor.refresh_status = 400
        with self.assertRaises(ProviderAuthError):
            self.client_.refresh("key-1")

    def test_range_asks_for_900_seconds_with_the_bearer_token(self):
        access, _ = self.client_.refresh("key-1")
        self.client_.range(access, "ABC123", START, START + timedelta(hours=1))
        request = self.vendor.range_requests[0]
        self.assertEqual(request["path"], "/v3/users/ABC123/data/range")
        self.assertEqual(request["query"]["interval"], "900")
        self.assertEqual(request["query"]["from"], "2026-07-01T00:00:00.000Z")
        self.assertEqual(request["query"]["to"], "2026-07-01T01:00:00.000Z")
        self.assertEqual(request["bearer"], access)

    def test_range_maps_watt_hours_to_kwh_and_keeps_the_interval_start(self):
        access, _ = self.client_.refresh("key-1")
        points = self.client_.range(access, "ABC123", START, START + timedelta(hours=1))
        self.assertEqual(len(points), 4)  # the vendor also sent the boundary interval; it is not ours
        row = vendor_row(START)
        first = points[0]
        self.assertEqual(first.timestamp, START)
        self.assertEqual(first.consumption_kwh, Decimal(row["cWh"]) / 1000)
        self.assertEqual(first.production_kwh, Decimal(row["pWh"]) / 1000)
        self.assertEqual(first.import_kwh, Decimal(row["iWh"]) / 1000)
        self.assertEqual(first.export_kwh, Decimal(row["eWh"]) / 1000)
        self.assertEqual(points[-1].timestamp, START + timedelta(minutes=45))

    def test_a_malformed_sm_id_never_reaches_the_network(self):
        for bad in ("", "ab", "a/b", "../x", "x" * 25, "ab cd", "ab?x=1"):
            with self.assertRaises(ProviderAuthError):
                self.client_.range("token", bad, START, START + timedelta(hours=1))
        self.assertEqual(self.vendor.range_requests, [])

    def test_a_429_carries_the_retry_after_the_vendor_sent(self):
        access, _ = self.client_.refresh("key-1")
        self.vendor.range_response = lambda n: (429, {"Retry-After": "120"}, b"{}")
        with self.assertRaises(ProviderRateLimited) as caught:
            self.client_.range(access, "ABC123", START, START + timedelta(hours=1))
        self.assertEqual(caught.exception.retry_after, 120)

    def test_a_429_without_or_with_a_silly_retry_after_is_bounded(self):
        access, _ = self.client_.refresh("key-1")
        for header, expected in ((None, 0), ("soon", 0), ("999999", 3600)):
            self.vendor.range_response = lambda n, h=header: (429, {"Retry-After": h} if h else {}, b"{}")
            with self.assertRaises(ProviderRateLimited) as caught:
                self.client_.range(access, "ABC123", START, START + timedelta(hours=1))
            self.assertEqual(caught.exception.retry_after, expected, header)

    def test_server_errors_are_transient_not_auth(self):
        access, _ = self.client_.refresh("key-1")
        self.vendor.range_response = lambda n: (503, {}, b"down")
        with self.assertRaises(ProviderError) as caught:
            self.client_.range(access, "ABC123", START, START + timedelta(hours=1))
        self.assertNotIsInstance(caught.exception, ProviderAuthError)
        self.assertNotIn("down", str(caught.exception))

    def test_an_installation_that_is_denied_or_unknown_is_an_auth_error(self):
        access, _ = self.client_.refresh("key-1")
        for status in (403, 404):
            self.vendor.range_response = lambda n, s=status: (s, {}, b"{}")
            with self.assertRaises(ProviderAuthError):
                self.client_.range(access, "ABC123", START, START + timedelta(hours=1))

    def test_a_redirect_is_refused_not_followed(self):
        access, _ = self.client_.refresh("key-1")
        self.vendor.range_response = lambda n: (302, {"Location": "http://127.0.0.1:1/elsewhere"}, b"")
        with self.assertRaises(ProviderError):
            self.client_.range(access, "ABC123", START, START + timedelta(hours=1))

    def test_an_oversized_response_is_refused(self):
        access, _ = self.client_.refresh("key-1")
        body = json.dumps({"data": [], "pad": "x" * (solar_manager.MAX_RESPONSE_BYTES + 10)}).encode()
        self.vendor.range_response = lambda n: (200, {}, body)
        with self.assertRaises(ProviderError):
            self.client_.range(access, "ABC123", START, START + timedelta(hours=1))

    def test_garbage_is_a_provider_error_not_a_crash(self):
        access, _ = self.client_.refresh("key-1")
        for body in (b"<html>", b"[1,2]", b'"text"', b"\xff\xfe"):
            self.vendor.range_response = lambda n, b=body: (200, {}, b)
            with self.assertRaises(ProviderError):
                self.client_.range(access, "ABC123", START, START + timedelta(hours=1))

    def test_an_unreachable_vendor_is_a_safe_provider_error(self):
        client = SolarManagerClient(base_url="http://127.0.0.1:1")
        with self.assertRaises(ProviderError) as caught:
            client.refresh("key-1")
        self.assertNotIn("127.0.0.1", str(caught.exception))


class MapPointsTests(TestCase):
    def window(self):
        return START, START + timedelta(hours=1)

    def test_a_row_missing_a_flow_is_a_gap_not_a_zero(self):
        row = vendor_row(START)
        del row["iWh"]
        points = map_points([row, vendor_row(START + timedelta(minutes=15))], *self.window())
        self.assertEqual([p.timestamp for p in points], [START + timedelta(minutes=15)])

    def test_null_and_non_numeric_values_are_skipped(self):
        bad_null = {**vendor_row(START), "pWh": None}
        bad_text = {**vendor_row(START + timedelta(minutes=15)), "cWh": "n/a"}
        self.assertEqual(map_points([bad_null, bad_text], *self.window()), [])

    def test_tiny_negative_noise_reads_as_zero_but_a_real_negative_is_kept_for_validation(self):
        noise = {**vendor_row(START), "pWh": -2}
        wrong = {**vendor_row(START + timedelta(minutes=15)), "pWh": -500}
        first, second = map_points([noise, wrong], *self.window())
        self.assertEqual(first.production_kwh, Decimal("0.0000"))
        self.assertEqual(second.production_kwh, Decimal("-0.5000"))

    def test_points_outside_the_window_and_junk_rows_are_ignored(self):
        rows = [
            vendor_row(START - timedelta(minutes=15)),
            vendor_row(START + timedelta(hours=1)),
            "junk", None, {"cWh": 1}, {"t": 5}, {"t": "not a date", "cWh": 1}, {"t": "2026-07-01T00:00:00"},
        ]
        self.assertEqual(map_points(rows, *self.window()), [])

    def test_a_response_without_a_data_list_is_empty(self):
        for data in (None, {}, "x", 5):
            self.assertEqual(map_points(data, *self.window()), [])

    def test_a_duplicate_interval_keeps_one_point_in_order(self):
        rows = [vendor_row(START + timedelta(minutes=30)), vendor_row(START), vendor_row(START)]
        points = map_points(rows, *self.window())
        self.assertEqual([p.timestamp for p in points], [START, START + timedelta(minutes=30)])

    def test_the_timestamp_convention_is_the_interval_start_with_no_shift(self):
        self.assertEqual(solar_manager.T_MARKS_INTERVAL, "start")
        self.assertEqual(map_points([vendor_row(START)], *self.window())[0].timestamp, START)

    def test_offsets_are_normalised_to_utc(self):
        row = {**vendor_row(START), "t": "2026-07-01T02:00:00+02:00"}
        self.assertEqual(map_points([row], *self.window())[0].timestamp, START)


class CivilDaysTests(TestCase):
    def test_days_are_cut_at_swiss_midnight(self):
        start, end = period_start_dt(date(2026, 7, 1)), period_start_dt(date(2026, 7, 4))
        chunks = list(civil_days(start, end))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0][0], start)
        self.assertTrue(all(lo == prev_hi for (_, prev_hi), (lo, _) in zip(chunks, chunks[1:])))
        self.assertEqual(chunks[-1][1], end)

    def test_a_dst_day_is_92_or_100_intervals_not_96(self):
        spring = list(civil_days(period_start_dt(date(2026, 3, 29)), period_start_dt(date(2026, 3, 30))))
        autumn = list(civil_days(period_start_dt(date(2026, 10, 25)), period_start_dt(date(2026, 10, 26))))
        self.assertEqual((spring[0][1] - spring[0][0]) // timedelta(minutes=15), 92)
        self.assertEqual((autumn[0][1] - autumn[0][0]) // timedelta(minutes=15), 100)

    def test_a_partial_window_is_clipped_not_extended(self):
        start = datetime(2026, 7, 1, 10, 15, tzinfo=UTC)
        end = datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
        self.assertEqual(list(civil_days(start, end)), [(start, end)])

    def test_an_empty_window_yields_nothing(self):
        self.assertEqual(list(civil_days(START, START)), [])


class ProviderTests(StubbedTestCase, SupplementaryApiTestCase):
    def setUp(self):
        StubbedTestCase.setUp(self)
        SupplementaryApiTestCase.setUp(self)
        self.provider = SolarManagerProvider(pause=0)
        patcher = mock.patch.object(solar_manager, "PAUSE_BETWEEN_REQUESTS_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = SupplementarySource(
            metering_point=self.point, participant=self.holder, provider="solar_manager", external_id="ABC123"
        )
        self.source.set_credential("key-1")
        self.source.save()

    def stored_key(self):
        return SupplementarySource.objects.get(pk=self.source.pk).credential

    def test_verify_exchanges_the_key_reads_an_hour_and_returns_the_rotated_key(self):
        keep = self.provider.verify("ABC123", "key-1")
        self.assertEqual(keep, "key-2")
        self.assertEqual(len(self.vendor.range_requests), 1)

    def test_verify_with_a_wrong_key_fails_before_any_data_is_requested(self):
        with self.assertRaises(ProviderAuthError):
            self.provider.verify("ABC123", "wrong")
        self.assertEqual(self.vendor.range_requests, [])

    def test_verify_with_a_wrong_installation_is_refused(self):
        self.vendor.range_response = lambda n: (404, {}, b"{}")
        with self.assertRaises(ProviderAuthError):
            self.provider.verify("NOPE999", "key-1")

    def test_fetch_persists_the_rotated_key_before_it_asks_for_data(self):
        seen = []
        original = self.provider.client.range

        def range_(access, sm_id, start, end):
            seen.append(self.stored_key())
            return original(access, sm_id, start, end)

        with mock.patch.object(self.provider.client, "range", side_effect=range_):
            list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))
        self.assertEqual(seen, ["key-2"])

    def test_the_next_fetch_spends_the_new_key_and_the_old_one_is_dead(self):
        list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))
        list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))
        self.assertEqual([r["refresh_token"] for r in self.vendor.refresh_requests], ["key-1", "key-2"])
        self.assertEqual(self.stored_key(), "key-3")

    def test_the_in_memory_source_carries_the_new_credential_too(self):
        list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))
        self.assertEqual(self.source.credential, "key-2")

    def test_a_refresh_that_cannot_be_saved_is_a_failed_refresh(self):
        with mock.patch.object(SupplementarySource, "set_credential", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))
        self.assertEqual(self.vendor.range_requests, [])  # the bearer token was never used
        self.assertEqual(self.stored_key(), "key-1")

    def test_a_vendor_that_does_not_rotate_leaves_the_stored_key_alone(self):
        self.vendor.rotate = False
        before = bytes(SupplementarySource.objects.get(pk=self.source.pk).credential_encrypted)
        list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))
        self.assertEqual(bytes(SupplementarySource.objects.get(pk=self.source.pk).credential_encrypted), before)

    def test_fetch_asks_for_one_civil_day_per_request_oldest_first(self):
        start, end = period_start_dt(date(2026, 7, 1)), period_start_dt(date(2026, 7, 4))
        chunks = list(self.provider.fetch(self.source, start, end))
        self.assertEqual(len(chunks), 3)
        self.assertEqual([len(chunk) for chunk in chunks], [96, 96, 96])
        asked = [request["query"]["from"] for request in self.vendor.range_requests]
        self.assertEqual(asked, sorted(asked))
        self.assertEqual(chunks[0][0].timestamp, start)

    def test_chunks_are_handed_over_one_at_a_time(self):
        start, end = period_start_dt(date(2026, 7, 1)), period_start_dt(date(2026, 7, 4))
        stream = self.provider.fetch(self.source, start, end)
        next(stream)
        self.assertEqual(len(self.vendor.range_requests), 1)  # the rest has not been requested yet

    def test_a_long_run_renews_the_access_token_before_it_expires(self):
        start, end = period_start_dt(date(2026, 7, 1)), period_start_dt(date(2026, 7, 4))
        with mock.patch.object(solar_manager, "ACCESS_TOKEN_MAX_AGE", timedelta(seconds=-1)):
            list(self.provider.fetch(self.source, start, end))
        # One exchange to start, then one before each chunk, because every token counts as expired.
        self.assertEqual(self.vendor.exchanges, 4)
        self.assertEqual(self.stored_key(), "key-5")
        self.assertTrue(all(r["bearer"] in self.vendor.access_tokens for r in self.vendor.range_requests))

    def test_a_credential_no_key_can_open_asks_the_participant_to_reconnect(self):
        with override_settings(INTEGRATION_ENCRYPTION_KEYS=[crypto.Fernet.generate_key().decode()]):
            with self.assertRaises(ProviderAuthError) as caught:
                list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))
        self.assertIn("Enter the API key again", str(caught.exception))
        self.assertEqual(self.vendor.refresh_requests, [])

    def test_a_disconnected_source_has_no_credential_to_spend(self):
        self.source.disconnect()
        self.source.save()
        with self.assertRaises(ProviderAuthError):
            list(self.provider.fetch(self.source, START, START + timedelta(hours=1)))

    def test_check_reads_an_hour_and_rotates(self):
        self.provider.check(self.source)
        self.assertEqual(self.stored_key(), "key-2")
        self.assertEqual(len(self.vendor.range_requests), 1)

    def test_the_provider_is_registered_for_solar_manager(self):
        from metering.supplementary.providers import PROVIDERS

        self.assertIsInstance(PROVIDERS["solar_manager"], SolarManagerProvider)


# ---- live: the stream (SPEC-2026-live-energy-data §6.1) -----------------------------------------


class MapStreamTests(TestCase):
    NOW = datetime(2026, 10, 30, 12, 0, 30, tzinfo=UTC)

    def map(self, payload, now=None):
        return solar_manager.map_stream(payload, "src-1", now or self.NOW)

    def test_the_meter_power_is_import_minus_export_and_the_gross_figures_are_kept(self):
        sample = self.map({"t": "2026-10-30T12:00:20.000Z", "iW": 350.4, "eW": 100, "pW": 900.04, "cW": 1150})

        self.assertEqual(sample.source_id, "src-1")
        self.assertEqual(sample.meter_power_w, Decimal("250.4"))
        self.assertEqual((sample.production_w, sample.consumption_w), (Decimal("900.0"), Decimal("1150.0")))
        self.assertEqual(sample.timestamp, datetime(2026, 10, 30, 12, 0, 20, tzinfo=UTC))
        self.assertEqual(sample.received_at, self.NOW)

    def test_feeding_in_is_a_negative_meter_power(self):
        self.assertEqual(self.map({"iW": 0, "eW": 4200}).meter_power_w, Decimal("-4200.0"))

    def test_production_and_consumption_are_optional(self):
        sample = self.map({"iW": 10, "eW": 0})
        self.assertEqual((sample.production_w, sample.consumption_w), (None, None))
        sample = self.map({"iW": 10, "eW": 0, "pW": None, "cW": "n/a"})
        self.assertEqual((sample.production_w, sample.consumption_w), (None, None))

    def test_a_negative_gross_figure_is_left_out_not_clamped(self):
        sample = self.map({"iW": 10, "eW": 0, "pW": -3, "cW": -1})
        self.assertEqual((sample.production_w, sample.consumption_w), (None, None))

    def test_battery_and_device_fields_are_ignored(self):
        sample = self.map({"iW": 100, "eW": 0, "bW": -5000, "soc": 80, "devices": [{"cW": 1}], "cPvW": 7})
        self.assertEqual(sample.meter_power_w, Decimal("100.0"))

    def test_a_missing_or_unreadable_import_or_export_is_no_sample(self):
        for payload in (
            {"eW": 5}, {"iW": 5}, {}, {"iW": None, "eW": 0}, {"iW": "x", "eW": 0}, {"iW": True, "eW": 0},
            {"iW": [1], "eW": 0}, {"iW": 1, "eW": {}},
        ):
            with self.assertRaises(ProviderError, msg=payload):
                self.map(payload)

    def test_a_payload_that_is_not_an_object_is_no_sample(self):
        for payload in (None, [], "x", 5):
            with self.assertRaises(ProviderError):
                self.map(payload)

    def test_abnormal_values_are_rejected(self):
        cap = solar_manager.settings.LIVE_MAX_ABS_POWER_W
        for payload in (
            {"iW": "NaN", "eW": 0}, {"iW": "Infinity", "eW": 0}, {"iW": 0, "eW": float("inf")},
            {"iW": cap + 1, "eW": 0}, {"iW": 0, "eW": cap + 1},
            {"iW": 0, "eW": 0, "pW": cap + 1}, {"iW": 0, "eW": 0, "cW": "1e12"},
        ):
            with self.assertRaises(ProviderError, msg=payload):
                self.map(payload)

    def test_the_cap_itself_is_still_plausible(self):
        cap = solar_manager.settings.LIVE_MAX_ABS_POWER_W
        self.assertEqual(self.map({"iW": 0, "eW": cap}).meter_power_w, Decimal(-cap))

    def test_a_missing_naive_or_unreadable_timestamp_is_now(self):
        for t in (None, "yesterday", "2026-10-30T11:00:00", 12345, ""):
            payload = {"iW": 1, "eW": 0}
            if t is not None:
                payload["t"] = t
            self.assertEqual(self.map(payload).timestamp, self.NOW, t)

    def test_a_timestamp_in_the_future_is_held_at_now_and_offsets_become_utc(self):
        self.assertEqual(self.map({"iW": 1, "eW": 0, "t": "2026-10-30T14:00:00+02:00"}).timestamp,
                         datetime(2026, 10, 30, 12, 0, tzinfo=UTC))
        self.assertEqual(self.map({"iW": 1, "eW": 0, "t": "2026-10-30T12:59:00Z"}).timestamp, self.NOW)


class ClientStreamTests(StubbedTestCase):
    def setUp(self):
        super().setUp()
        self.access, _ = self.client_.refresh("key-1")

    def test_stream_calls_the_stream_endpoint_with_the_bearer_token(self):
        payload = self.client_.stream(self.access, "ABC123")

        request = self.vendor.stream_requests[0]
        self.assertEqual((request["path"], request["query"], request["bearer"]),
                         ("/v3/users/ABC123/data/stream", {}, self.access))
        self.assertEqual(payload["iW"], 400)
        self.assertEqual(self.vendor.range_requests, [])

    def test_a_malformed_sm_id_never_reaches_the_network(self):
        for bad in ("", "ab", "a/b", "../x", "x" * 25, "ab?x=1"):
            with self.assertRaises(ProviderAuthError):
                self.client_.stream(self.access, bad)
        self.assertEqual(self.vendor.stream_requests, [])

    def test_the_same_error_mapping_applies(self):
        cases = (
            (429, {"Retry-After": "90"}, b"{}", ProviderRateLimited), (503, {}, b"down", ProviderError),
            (302, {"Location": "http://127.0.0.1:1/x"}, b"", ProviderError), (403, {}, b"{}", ProviderAuthError),
            (200, {}, b"<html>", ProviderError),
            (200, {}, json.dumps({"pad": "x" * (solar_manager.MAX_RESPONSE_BYTES + 10)}).encode(), ProviderError),
        )
        for status, headers, body, expected in cases:
            self.vendor.stream_response = lambda n, c=(status, headers, body): c
            with self.assertRaises(expected, msg=status):
                self.client_.stream(self.access, "ABC123")

    def test_an_unknown_bearer_token_is_an_auth_error(self):
        with self.assertRaises(ProviderAuthError):
            self.client_.stream("stale", "ABC123")


class SolarManagerLiveTests(StubbedTestCase, SupplementaryApiTestCase):
    def setUp(self):
        StubbedTestCase.setUp(self)
        SupplementaryApiTestCase.setUp(self)
        cache.clear()
        self.provider = SolarManagerProvider(pause=0)
        self.source = SupplementarySource(
            zev=self.zev, metering_point=self.point, participant=self.holder, provider="solar_manager",
            external_id="ABC123", provides_history=False, provides_live=True,
        )
        self.source.set_credential("key-1")
        self.source.save()

    def stored_key(self):
        return SupplementarySource.objects.get(pk=self.source.pk).credential

    def test_a_sample_is_read_from_the_stream(self):
        self.vendor.stream_payload = {"iW": 100, "eW": 700, "pW": 900, "cW": 300}

        sample = self.provider.fetch_live(self.source)

        self.assertEqual(sample.source_id, str(self.source.pk))
        self.assertEqual((sample.meter_power_w, sample.production_w, sample.consumption_w),
                         (Decimal("-600.0"), Decimal("900.0"), Decimal("300.0")))
        self.assertEqual(len(self.vendor.stream_requests), 1)
        self.assertEqual(self.vendor.range_requests, [])

    def test_a_payload_without_iw_is_no_sample(self):
        self.vendor.stream_payload = {"eW": 700, "pW": 900}
        with self.assertRaises(ProviderError):
            self.provider.fetch_live(self.source)

    def test_the_bearer_token_is_cached_so_a_poll_does_not_spend_the_key_every_time(self):
        for _ in range(5):
            self.provider.fetch_live(self.source)

        self.assertEqual(self.vendor.exchanges, 1)
        self.assertEqual(len(self.vendor.stream_requests), 5)
        self.assertEqual({r["bearer"] for r in self.vendor.stream_requests}, {"access-1"})

    def test_the_cache_survives_with_rotation_on_and_the_stored_key_is_rotated_once(self):
        self.assertTrue(self.vendor.rotate)

        self.provider.fetch_live(self.source)
        self.provider.fetch_live(SupplementarySource.objects.get(pk=self.source.pk))

        self.assertEqual([r["refresh_token"] for r in self.vendor.refresh_requests], ["key-1"])
        self.assertEqual(self.stored_key(), "key-2")

    def test_the_cached_token_is_encrypted_and_lives_fifty_minutes(self):
        with mock.patch.object(solar_manager.store, "set_sm_access", wraps=solar_manager.store.set_sm_access) as put:
            self.provider.fetch_live(self.source)

        raw = solar_manager.store.get_sm_access(self.source.pk)
        self.assertNotIn("access-1", raw)
        self.assertEqual(crypto.decrypt_secret(raw.encode()), "access-1")
        self.assertEqual(put.call_args.args[2], 50 * 60)
        self.assertEqual(solar_manager.store._sm_access_key(self.source.pk), f"live:v1:sm-access:{self.source.pk}")

    def test_an_unreadable_cache_entry_is_dropped_and_exchanged_again(self):
        solar_manager.store.set_sm_access(self.source.pk, "not-a-fernet-token", 60)

        self.provider.fetch_live(self.source)

        self.assertEqual(self.vendor.exchanges, 1)
        self.assertEqual(crypto.decrypt_secret(solar_manager.store.get_sm_access(self.source.pk).encode()), "access-1")

    def test_a_stale_cached_token_costs_one_fresh_exchange_and_the_poll_succeeds(self):
        self.provider.fetch_live(self.source)
        self.vendor.access_tokens.clear()  # the vendor expired it early

        sample = self.provider.fetch_live(self.source)

        self.assertIsNotNone(sample)
        self.assertEqual(self.vendor.exchanges, 2)
        self.assertEqual([r["bearer"] for r in self.vendor.stream_requests], ["access-1", "access-1", "access-2"])
        self.provider.fetch_live(self.source)  # and the new token is cached in turn
        self.assertEqual(self.vendor.exchanges, 2)

    def test_a_fresh_token_the_vendor_still_refuses_is_an_auth_failure_after_one_retry(self):
        self.provider.fetch_live(self.source)
        self.vendor.stream_response = lambda n: (403, {}, b"{}")

        with self.assertRaises(ProviderAuthError):
            self.provider.fetch_live(self.source)

        self.assertEqual(self.vendor.exchanges, 2)  # one for the first poll, one retry, not a loop
        self.assertEqual(len(self.vendor.stream_requests), 3)

    def test_an_uncached_auth_failure_is_not_retried(self):
        self.vendor.stream_response = lambda n: (403, {}, b"{}")

        with self.assertRaises(ProviderAuthError):
            self.provider.fetch_live(self.source)

        self.assertEqual((self.vendor.exchanges, len(self.vendor.stream_requests)), (1, 1))

    def test_a_rejected_key_is_an_auth_error_and_caches_nothing(self):
        self.vendor.current_token = "someone-else"

        with self.assertRaises(ProviderAuthError):
            self.provider.fetch_live(self.source)

        self.assertIsNone(solar_manager.store.get_sm_access(self.source.pk))

    def test_a_malformed_sm_id_never_spends_the_key(self):
        self.source.external_id = "a/b"
        with self.assertRaises(ProviderAuthError):
            self.provider.fetch_live(self.source)
        self.assertEqual(self.vendor.refresh_requests, [])

    def test_verify_live_reads_one_stream_sample_not_a_history_hour(self):
        keep = self.provider.verify_live("ABC123", "key-1")

        self.assertEqual(keep, "key-2")
        self.assertEqual(len(self.vendor.stream_requests), 1)
        self.assertEqual(self.vendor.range_requests, [])

    def test_verify_live_refuses_a_wrong_key_an_unknown_installation_and_an_unusable_stream(self):
        with self.assertRaises(ProviderAuthError):
            self.provider.verify_live("ABC123", "wrong")
        self.vendor.stream_response = lambda n: (404, {}, b"{}")
        with self.assertRaises(ProviderAuthError):
            self.provider.verify_live("NOPE999", "key-1")
        self.vendor.stream_response = None
        self.vendor.stream_payload = {"pW": 3}
        with self.assertRaises(ProviderError):
            self.provider.verify_live("ABC123", self.vendor.current_token)

    def test_check_live_reads_a_sample_with_the_stored_key_through_the_cache(self):
        self.provider.check_live(self.source)
        self.provider.check_live(self.source)

        self.assertEqual((self.vendor.exchanges, len(self.vendor.stream_requests)), (1, 2))

    def test_the_provider_is_the_one_registered_for_solar_manager(self):
        from metering.supplementary.providers import PROVIDERS

        self.assertTrue(callable(PROVIDERS["solar_manager"].fetch_live))


class SolarManagerLiveSourceApiTests(StubbedTestCase, SupplementaryApiTestCase):
    """The connect, test and disconnect flows with the real provider against the stand-in."""

    def setUp(self):
        StubbedTestCase.setUp(self)
        SupplementaryApiTestCase.setUp(self)
        cache.clear()
        FeatureFlag.objects.update_or_create(name=FeatureFlag.LIVE_ENERGY_DATA_ENABLED, defaults={"enabled": True})
        self.plain = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        factories.MeteringPointAssignmentFactory(
            metering_point=self.plain, participant=self.holder, valid_from=date(2025, 1, 1)
        )

    def create(self, point=None, **extra):
        payload = {
            "metering_point": str((point or self.plain).pk), "provider": "solar_manager", "external_id": "ABC123",
            "api_key": "key-1", "consent": True, **extra,
        }
        return client_for(self.holder_user).post(SOURCES_URL, payload, format="json")

    def make_live_source(self):
        source = SupplementarySource(
            zev=self.zev, metering_point=self.plain, participant=self.holder, provider="solar_manager",
            external_id="ABC123", provides_history=False, provides_live=True,
        )
        source.set_credential("key-1")
        source.save()
        return source

    def test_a_live_only_source_is_verified_with_the_stream_and_syncs_nothing(self):
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay:
            response = self.create(provides_history=False, provides_live=True)

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["provides_history"], body["provides_live"], body["has_credential"]), (False, True, True))
        self.assertEqual(body["live_state"], "never")
        self.assertNotIn("push_token", body)
        self.assertEqual((len(self.vendor.stream_requests), len(self.vendor.range_requests)), (1, 0))
        self.assertEqual(SupplementarySource.objects.get().credential, "key-2")
        delay.assert_not_called()

    def test_a_source_with_both_is_verified_with_history_and_queues_a_sync(self):
        point = self.point  # behind the meter, so history is possible
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay, self.captureOnCommitCallbacks(execute=True):
            response = self.create(point, provides_history=True, provides_live=True)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((len(self.vendor.range_requests), len(self.vendor.stream_requests)), (1, 0))
        delay.assert_called_once()

    def test_a_wrong_key_for_a_live_only_source_is_a_field_error_and_stores_nothing(self):
        response = self.create(provides_history=False, provides_live=True, api_key="wrong")

        self.assertEqual(response.status_code, 400)
        self.assertIn("api_key", response.json())
        self.assertEqual(SupplementarySource.objects.count(), 0)

    def test_live_still_needs_the_live_flag(self):
        FeatureFlag.objects.filter(name=FeatureFlag.LIVE_ENERGY_DATA_ENABLED).update(enabled=False)

        response = self.create(provides_history=False, provides_live=True)

        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_live", response.json())
        self.assertEqual(self.vendor.refresh_requests, [])

    def test_a_forecast_needs_a_producing_meter(self):
        response = self.create(provides_history=False, provides_live=True, provides_forecast=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("metering_point", response.json())

    def test_live_is_added_to_a_history_source_with_the_stored_key_and_the_holders_consent(self):
        created = self.create(self.point, provides_history=True).json()
        url = f"{SOURCES_URL}{created['id']}/"
        exchanges = self.vendor.exchanges

        refused = client_for(self.holder_user).patch(url, {"provides_live": True}, format="json")
        accepted = client_for(self.holder_user).patch(url, {"provides_live": True, "consent": True}, format="json")

        self.assertEqual(refused.status_code, 400)
        self.assertIn("consent", refused.json())
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertTrue(accepted.json()["provides_live"] and accepted.json()["provides_history"])
        self.assertEqual(self.vendor.exchanges, exchanges)  # no new key, no new exchange

    def test_live_cannot_be_added_to_a_disconnected_source_without_a_key(self):
        created = self.create(self.point, provides_history=True).json()
        source = SupplementarySource.objects.get(pk=created["id"])
        source.disconnect()
        source.save()

        response = client_for(self.holder_user).patch(
            f"{SOURCES_URL}{source.pk}/", {"provides_live": True, "consent": True}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("provides_live", response.json())

    def test_history_added_to_a_live_only_source_starts_a_sync(self):
        source = self.make_live_source()
        # The plain meter has no generation behind it, so history is refused there.
        refused = client_for(self.holder_user).patch(
            f"{SOURCES_URL}{source.pk}/", {"provides_history": True, "consent": True}, format="json"
        )
        self.assertEqual(refused.status_code, 400)
        self.assertIn("provides_history", refused.json())

        SupplementarySource.objects.filter(pk=source.pk).update(metering_point=self.point)
        with mock.patch.object(tasks.sync_supplementary_source, "delay") as delay, self.captureOnCommitCallbacks(execute=True):
            accepted = client_for(self.holder_user).patch(
                f"{SOURCES_URL}{source.pk}/", {"provides_history": True, "consent": True}, format="json"
            )
        self.assertEqual(accepted.status_code, 200, accepted.content)
        delay.assert_called_once()

    def test_replacing_the_key_of_a_live_only_source_verifies_with_the_stream_and_drops_the_cached_token(self):
        source = self.make_live_source()
        SolarManagerProvider().fetch_live(source)  # caches a bearer token
        self.assertIsNotNone(solar_manager.store.get_sm_access(source.pk))
        self.vendor.current_token = "key-9"

        response = client_for(self.holder_user).patch(f"{SOURCES_URL}{source.pk}/", {"api_key": "key-9"}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(self.vendor.range_requests), 0)
        self.assertEqual(SupplementarySource.objects.get(pk=source.pk).credential, "key-3")
        self.assertIsNone(solar_manager.store.get_sm_access(source.pk))

    def test_disconnecting_wipes_the_cached_token_with_the_credential(self):
        source = self.make_live_source()
        SolarManagerProvider().fetch_live(source)

        response = client_for(self.holder_user).post(f"{SOURCES_URL}{source.pk}/disconnect/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(solar_manager.store.get_sm_access(source.pk))
        self.assertFalse(SupplementarySource.objects.get(pk=source.pk).has_credential)

    def test_deleting_a_source_wipes_the_cached_token(self):
        source = self.make_live_source()
        SolarManagerProvider().fetch_live(source)

        self.assertEqual(client_for(self.holder_user).delete(f"{SOURCES_URL}{source.pk}/").status_code, 204)

        self.assertIsNone(solar_manager.store.get_sm_access(source.pk))

    def test_the_orphan_sweep_wipes_the_cached_token_too(self):
        source = self.make_live_source()
        SolarManagerProvider().fetch_live(source)
        MeteringPointAssignment.objects.filter(participant=self.holder).update(valid_to=date(2025, 6, 1))

        tasks.disable_orphaned_supplementary_sources()

        self.assertIsNone(solar_manager.store.get_sm_access(source.pk))

    def test_the_test_action_fetches_one_stream_sample_for_a_live_only_source(self):
        source = self.make_live_source()

        response = client_for(self.holder_user).post(f"{SOURCES_URL}{source.pk}/test/")

        self.assertEqual((response.status_code, response.json()), (200, {"ok": True}))
        self.assertEqual((len(self.vendor.stream_requests), len(self.vendor.range_requests)), (1, 0))

    def test_the_test_action_checks_both_for_a_source_with_history_and_live(self):
        created = self.create(self.point, provides_history=True, provides_live=True).json()

        response = client_for(self.holder_user).post(f"{SOURCES_URL}{created['id']}/test/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((len(self.vendor.stream_requests), len(self.vendor.range_requests)), (1, 2))  # verify + check

    def test_the_test_action_of_a_history_source_is_unchanged(self):
        created = self.create(self.point, provides_history=True).json()

        self.assertEqual(client_for(self.holder_user).post(f"{SOURCES_URL}{created['id']}/test/").status_code, 200)
        self.assertEqual(self.vendor.stream_requests, [])

    def test_a_failing_live_test_reports_the_safe_text_and_a_rejected_key_needs_reconnecting(self):
        source = self.make_live_source()
        self.vendor.current_token = "someone-else"

        response = client_for(self.holder_user).post(f"{SOURCES_URL}{source.pk}/test/")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("key-1", response.content.decode())
        source.refresh_from_db()
        self.assertEqual(source.status, "reconnect_required")

    def test_a_push_source_without_history_still_cannot_be_tested(self):
        source = SupplementarySource.objects.create(
            zev=self.zev, metering_point=self.plain, participant=self.holder, provider="push",
            provides_history=False, provides_live=True,
        )

        response = client_for(self.holder_user).post(f"{SOURCES_URL}{source.pk}/test/")

        self.assertEqual((response.status_code, response.json()), (400, {"detail": "This source does not provide history."}))

    def test_sync_still_needs_history(self):
        source = self.make_live_source()
        response = client_for(self.holder_user).post(f"{SOURCES_URL}{source.pk}/sync/")
        self.assertEqual((response.status_code, response.json()), (400, {"detail": "This source does not provide history."}))
