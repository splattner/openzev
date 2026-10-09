"""The Solar Manager client and provider of SPEC §6.2, against a local stand-in for the vendor."""

import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from allocation.validity import period_start_dt
from metering.models import SupplementarySource
from metering.supplementary import crypto, solar_manager
from metering.supplementary.providers import ProviderAuthError, ProviderError, ProviderRateLimited
from metering.supplementary.solar_manager import SolarManagerClient, SolarManagerProvider, civil_days, map_points
from metering.supplementary.testing import INTEGRATION_KEY, StubSolarManager, SupplementaryApiTestCase, vendor_row

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
