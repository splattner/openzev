"""Supplementary energy data in backups (ADR 0031, SPEC-2026-supplementary-energy-data §6.6)."""

from django.test import SimpleTestCase, TestCase, override_settings

from backups import crypto, restore
from backups.fixtures import SUPPLEMENTARY_KEY, SUPPLEMENTARY_SECRET, build_world
from backups.test_archive import all_text, build, read_jsonl
from metering.models import SupplementaryReading, SupplementarySource

OTHER_KEY = "O" * 44


class SupplementaryArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[SUPPLEMENTARY_KEY])
    def test_sources_and_readings_are_in_their_own_section_sources_first(self):
        raw, manifest = build()
        rows = read_jsonl(raw, f"zevs/{self.world.alpha.pk}/supplementary.jsonl")
        models = [row["model"] for row in rows]
        self.assertEqual(models, ["metering.supplementarysource"] + ["metering.supplementaryreading"] * 2)
        self.assertEqual(
            manifest["counts"][f"zevs/{self.world.alpha.pk}/supplementary"],
            SupplementarySource.objects.count() + SupplementaryReading.objects.count(),
        )
        # Beta has none: an empty section is still written.
        self.assertEqual(read_jsonl(raw, f"zevs/{self.world.beta.pk}/supplementary.jsonl"), [])

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[SUPPLEMENTARY_KEY])
    def test_the_credential_travels_as_ciphertext_and_the_key_never_does(self):
        raw, _ = build()
        text = all_text(raw)
        self.assertNotIn(SUPPLEMENTARY_SECRET, text)
        self.assertNotIn(SUPPLEMENTARY_KEY, text)
        source_row = read_jsonl(raw, f"zevs/{self.world.alpha.pk}/supplementary.jsonl")[0]
        self.assertTrue(source_row["fields"]["credential_encrypted"])

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[SUPPLEMENTARY_KEY, OTHER_KEY])
    def test_the_manifest_records_integration_key_fingerprints_only(self):
        _, manifest = build()
        fingerprints = manifest["secret_fingerprints"]["integration_encryption_keys"]
        self.assertEqual(fingerprints, [crypto.key_fingerprint(SUPPLEMENTARY_KEY), crypto.key_fingerprint(OTHER_KEY)])
        self.assertNotIn(SUPPLEMENTARY_KEY, str(manifest))


class IntegrationKeyWarningTests(SimpleTestCase):
    @staticmethod
    def manifest(fingerprints, sources=2):
        return {
            "members": {
                "instance/accounts.jsonl": {"models": {}},
                "zevs/abc/supplementary.jsonl": {"models": {"metering.SupplementarySource": sources}},
            },
            "secret_fingerprints": {"integration_encryption_keys": fingerprints},
        }

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[OTHER_KEY])
    def test_other_keys_warn_and_name_the_fingerprint(self):
        warnings = restore.key_warnings(self.manifest(["9f8e7d6c5b4a3928"]))
        self.assertEqual(len(warnings), 1)
        self.assertIn("9f8e7d6c5b4a3928", warnings[0])
        self.assertIn("2 energy data source", warnings[0])

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[])
    def test_no_key_at_all_also_warns(self):
        self.assertEqual(len(restore.key_warnings(self.manifest(["9f8e7d6c5b4a3928"]))), 1)

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[OTHER_KEY])
    def test_a_matching_key_is_silent(self):
        self.assertEqual(restore.key_warnings(self.manifest([crypto.key_fingerprint(OTHER_KEY)])), [])

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[OTHER_KEY])
    def test_no_sources_means_nothing_to_warn_about(self):
        self.assertEqual(restore.key_warnings(self.manifest(["9f8e7d6c5b4a3928"], sources=0)), [])

    @override_settings(INTEGRATION_ENCRYPTION_KEYS=[OTHER_KEY])
    def test_an_older_manifest_without_fingerprints_is_silent(self):
        manifest = self.manifest([])
        del manifest["secret_fingerprints"]["integration_encryption_keys"]
        self.assertEqual(restore.key_warnings(manifest), [])
