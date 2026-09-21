"""Destination validation, credentials, and the storage backends."""

import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from backups import crypto, storage
from backups.models import BackupDestination, BackupDestinationKind, CredentialMode

KEY = "D" * 40


def local(path, **kwargs):
    return BackupDestination(name="local", kind=BackupDestinationKind.LOCAL, path=str(path), **kwargs)


def s3(**kwargs):
    defaults = {"name": "bucket", "kind": BackupDestinationKind.S3, "bucket": "openzev-backups"}
    return BackupDestination(**{**defaults, **kwargs})


class LocalDestinationValidationTests(SimpleTestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)

    def test_a_local_destination_needs_a_path(self):
        with self.assertRaises(ValidationError) as raised:
            BackupDestination(name="x", kind="local").clean()
        self.assertIn("path", raised.exception.message_dict)

    def test_a_relative_path_is_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            local("relative/dir").clean()
        self.assertIn("absolute", raised.exception.message_dict["path"][0])

    def test_a_path_inside_media_root_is_rejected_because_media_is_web_reachable(self):
        for path in (Path(settings.MEDIA_ROOT), Path(settings.MEDIA_ROOT) / "backups"):
            with self.subTest(path=str(path)), self.assertRaises(ValidationError) as raised:
                local(path).clean()
            self.assertIn("MEDIA_ROOT", raised.exception.message_dict["path"][0])

    def test_a_path_that_reaches_media_root_through_dotdot_is_rejected(self):
        """The path is resolved before it is compared, so ``..`` cannot smuggle it in."""
        inside = Path(settings.MEDIA_ROOT) / "x" / ".." / "y"
        with self.assertRaises(ValidationError):
            local(inside).clean()

    def test_an_existing_file_is_not_a_directory(self):
        file_path = Path(self.work.name) / "a-file"
        file_path.write_text("x")
        with self.assertRaises(ValidationError) as raised:
            local(file_path).clean()
        self.assertIn("not a directory", raised.exception.message_dict["path"][0])

    def test_a_directory_that_does_not_exist_yet_is_accepted(self):
        local(Path(self.work.name) / "will-be-created").clean()

    def test_s3_fields_on_a_local_destination_are_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            local(self.work.name, bucket="b", region="r").clean()
        self.assertEqual({"bucket", "region"} & set(raised.exception.message_dict), {"bucket", "region"})


class S3DestinationValidationTests(SimpleTestCase):
    def test_an_s3_destination_needs_a_bucket(self):
        with self.assertRaises(ValidationError) as raised:
            BackupDestination(name="x", kind="s3").clean()
        self.assertIn("bucket", raised.exception.message_dict)

    def test_a_local_path_on_an_s3_destination_is_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            s3(path="/tmp/x").clean()
        self.assertIn("path", raised.exception.message_dict)

    def test_a_prefix_may_not_start_with_a_slash(self):
        with self.assertRaises(ValidationError) as raised:
            s3(prefix="/leading").clean()
        self.assertIn("prefix", raised.exception.message_dict)

    def test_half_a_credential_pair_is_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            s3(access_key_id="AKIA").clean()
        self.assertIn("access_key_id", raised.exception.message_dict)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_both_halves_together_are_accepted(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("secret")
        destination.clean()

    def test_no_credentials_at_all_is_accepted_it_means_an_instance_role(self):
        s3().clean()


class DestinationCredentialTests(SimpleTestCase):
    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_a_stored_secret_round_trips_and_the_column_holds_ciphertext(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("very-secret")
        self.assertNotIn(b"very-secret", bytes(destination.secret_access_key_encrypted))
        self.assertEqual(destination.secret_access_key, "very-secret")
        self.assertTrue(destination.has_stored_secret)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[])
    def test_a_secret_cannot_be_stored_without_an_encryption_key(self):
        with self.assertRaises(ValidationError) as raised:
            s3().set_secret_access_key("very-secret")
        self.assertIn("BACKUP_ENCRYPTION_KEYS", raised.exception.message_dict["secret_access_key"][0])

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_an_empty_value_clears_the_secret(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("very-secret")
        destination.set_secret_access_key("")
        self.assertFalse(destination.has_stored_secret)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY], BACKUP_S3_ACCESS_KEY_ID="ENVKEY", BACKUP_S3_SECRET_ACCESS_KEY="envsecret")
    def test_environment_credentials_take_precedence_over_stored_ones(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("stored")
        self.assertEqual(destination.credential_mode, CredentialMode.ENVIRONMENT)

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_stored_credentials_when_there_is_no_environment_override(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("stored")
        self.assertEqual(destination.credential_mode, CredentialMode.STORED)

    def test_an_instance_role_when_there_are_no_credentials_anywhere(self):
        self.assertEqual(s3().credential_mode, CredentialMode.INSTANCE_ROLE)

    @override_settings(BACKUP_S3_ACCESS_KEY_ID="ENVKEY", BACKUP_S3_SECRET_ACCESS_KEY="")
    def test_half_an_environment_pair_is_not_used(self):
        self.assertEqual(s3().credential_mode, CredentialMode.INSTANCE_ROLE)


class S3ClientConstructionTests(SimpleTestCase):
    """How ``s3_client`` turns a destination into a boto3 client."""

    def build(self, destination):
        with mock.patch("boto3.client") as client:
            storage.s3_client(destination)
        return client.call_args.kwargs

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_stored_credentials_are_decrypted_and_passed(self):
        destination = s3(access_key_id="AKIA", region="eu-central-1")
        destination.set_secret_access_key("decrypted-secret")
        kwargs = self.build(destination)
        self.assertEqual(kwargs["aws_access_key_id"], "AKIA")
        self.assertEqual(kwargs["aws_secret_access_key"], "decrypted-secret")
        self.assertEqual(kwargs["region_name"], "eu-central-1")

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY], BACKUP_S3_ACCESS_KEY_ID="ENVKEY", BACKUP_S3_SECRET_ACCESS_KEY="envsecret")
    def test_environment_credentials_win(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("stored")
        kwargs = self.build(destination)
        self.assertEqual(kwargs["aws_access_key_id"], "ENVKEY")
        self.assertEqual(kwargs["aws_secret_access_key"], "envsecret")

    def test_an_instance_role_passes_no_credentials_so_boto_uses_its_default_chain(self):
        kwargs = self.build(s3())
        self.assertNotIn("aws_access_key_id", kwargs)
        self.assertNotIn("aws_secret_access_key", kwargs)

    def test_a_custom_endpoint_uses_path_style_and_relaxes_integrity_checksums(self):
        """boto3 1.36+ adds a checksum to every upload; many S3-compatible stores reject it."""
        kwargs = self.build(s3(endpoint_url="https://minio.internal:9000"))
        config = kwargs["config"]
        self.assertEqual(kwargs["endpoint_url"], "https://minio.internal:9000")
        self.assertEqual(config.s3["addressing_style"], "path")
        self.assertEqual(config.request_checksum_calculation, "when_required")
        self.assertEqual(config.response_checksum_validation, "when_required")

    def test_plain_aws_keeps_boto_defaults(self):
        kwargs = self.build(s3())
        self.assertIsNone(kwargs["endpoint_url"])
        self.assertIsNone(kwargs["config"].s3)

    @override_settings(BACKUP_ENCRYPTION_KEYS=["Y" * 40])
    def test_a_stored_secret_that_cannot_be_decrypted_is_reported_not_leaked(self):
        destination = s3(access_key_id="AKIA")
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY]):
            destination.set_secret_access_key("XYZZY-distinctive-secret")
        with self.assertRaises(storage.DestinationError) as raised:
            self.build(destination)
        self.assertNotIn("XYZZY", str(raised.exception))


class LocalStorageTests(SimpleTestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.target = Path(self.work.name) / "backups"
        self.source = Path(self.work.name) / "source.zip"
        self.source.write_bytes(b"archive bytes")

    def test_the_archive_lands_in_the_directory_created_on_demand(self):
        location = storage.store_archive(local(self.target), self.source, "a.zip")
        self.assertEqual(location, str(self.target / "a.zip"))
        self.assertEqual((self.target / "a.zip").read_bytes(), b"archive bytes")

    def test_the_stored_file_is_readable_by_its_owner_only(self):
        storage.store_archive(local(self.target), self.source, "a.zip")
        mode = stat.S_IMODE(os.stat(self.target / "a.zip").st_mode)
        self.assertEqual(mode, 0o600)

    def test_no_partial_file_is_left_behind(self):
        storage.store_archive(local(self.target), self.source, "a.zip")
        self.assertEqual([p.name for p in self.target.iterdir()], ["a.zip"])

    def test_a_failed_copy_leaves_neither_a_partial_nor_a_finished_looking_file(self):
        with mock.patch("backups.storage.shutil.copyfile", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(storage.DestinationError) as raised:
                storage.store_archive(local(self.target), self.source, "a.zip")
        self.assertIn("No space left", str(raised.exception))
        self.assertEqual(list(self.target.iterdir()), [])

    def test_a_location_inside_media_root_is_refused_at_write_time_too(self):
        with self.assertRaises(storage.DestinationError):
            storage.store_archive(local(Path(settings.MEDIA_ROOT) / "b"), self.source, "a.zip")

    def test_probe_writes_and_removes_its_file(self):
        storage.probe_destination(local(self.target))
        self.assertEqual(list(self.target.iterdir()), [])

    def test_probe_reports_an_unwritable_directory(self):
        blocker = Path(self.work.name) / "blocker"
        blocker.write_text("x")
        with self.assertRaises(storage.DestinationError):
            storage.probe_destination(local(blocker / "child"))


class FakeS3:
    def __init__(self):
        self.uploads = []
        self.puts = []
        self.deletes = []

    def upload_file(self, filename, bucket, key, **kwargs):
        self.uploads.append({"bytes": Path(filename).read_bytes(), "bucket": bucket, "key": key, **kwargs})

    def put_object(self, **kwargs):
        self.puts.append(kwargs)

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)


class S3StorageTests(SimpleTestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.source = Path(self.work.name) / "source.zip"
        self.source.write_bytes(b"archive bytes")
        self.fake = FakeS3()
        patcher = mock.patch("backups.storage.s3_client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_archive_is_uploaded_under_the_prefix_with_server_side_encryption(self):
        destination = s3(prefix="prod/nightly/", server_side_encryption="aws:kms")
        location = storage.store_archive(destination, self.source, "a.zip.enc")
        self.assertEqual(location, "s3://openzev-backups/prod/nightly/a.zip.enc")
        upload = self.fake.uploads[0]
        self.assertEqual((upload["bucket"], upload["key"]), ("openzev-backups", "prod/nightly/a.zip.enc"))
        self.assertEqual(upload["bytes"], b"archive bytes")
        self.assertEqual(upload["ExtraArgs"], {"ServerSideEncryption": "aws:kms"})

    def test_no_prefix_means_the_bucket_root(self):
        location = storage.store_archive(s3(), self.source, "a.zip")
        self.assertEqual(location, "s3://openzev-backups/a.zip")

    def test_server_side_encryption_can_be_switched_off_for_stores_that_lack_it(self):
        storage.store_archive(s3(server_side_encryption=""), self.source, "a.zip")
        self.assertEqual(self.fake.uploads[0]["ExtraArgs"], {})

    def test_probe_puts_then_deletes_the_same_key(self):
        storage.probe_destination(s3(prefix="p"))
        self.assertEqual(len(self.fake.puts), 1)
        self.assertEqual(self.fake.puts[0]["Key"], self.fake.deletes[0]["Key"])
        self.assertTrue(self.fake.puts[0]["Key"].startswith("p/.openzev-probe-"))

    def test_provider_errors_become_safe_messages_that_never_echo_the_response(self):
        cases = {
            "AccessDenied": "Access denied",
            "NoSuchBucket": "bucket does not exist",
            "InvalidAccessKeyId": "not recognised",
            "SignatureDoesNotMatch": "does not match",
            "SomethingNew": "SomethingNew",
        }
        for code, expected in cases.items():
            error = ClientError({"Error": {"Code": code, "Message": "LEAK-akia-secret-token"}}, "PutObject")
            self.fake.upload_file = mock.Mock(side_effect=error)
            with self.subTest(code=code), self.assertRaises(storage.DestinationError) as raised:
                storage.store_archive(s3(), self.source, "a.zip")
            self.assertIn(expected, str(raised.exception))
            self.assertNotIn("LEAK", str(raised.exception))

    def test_missing_credentials_and_unreachable_endpoints_are_explained(self):
        for error, expected in (
            (NoCredentialsError(), "No credentials"),
            (EndpointConnectionError(endpoint_url="https://x.internal"), "Could not reach"),
        ):
            self.fake.upload_file = mock.Mock(side_effect=error)
            with self.subTest(error=type(error).__name__), self.assertRaises(storage.DestinationError) as raised:
                storage.store_archive(s3(), self.source, "a.zip")
            self.assertIn(expected, str(raised.exception))


class DestinationPersistenceTests(TestCase):
    def test_names_are_unique(self):
        from django.db import IntegrityError, transaction

        BackupDestination.objects.create(name="dup", kind="local", path="/x")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BackupDestination.objects.create(name="dup", kind="local", path="/y")

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_the_secret_survives_a_database_round_trip(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("persisted")
        destination.save()
        self.assertEqual(BackupDestination.objects.get(pk=destination.pk).secret_access_key, "persisted")

    @override_settings(BACKUP_ENCRYPTION_KEYS=[KEY])
    def test_the_plaintext_secret_is_not_in_the_row(self):
        destination = s3(access_key_id="AKIA")
        destination.set_secret_access_key("persisted-plaintext")
        destination.save()
        raw = bytes(BackupDestination.objects.get(pk=destination.pk).secret_access_key_encrypted)
        self.assertNotIn(b"persisted-plaintext", raw)
        self.assertTrue(crypto.decrypt_secret(raw) == "persisted-plaintext")


class ProviderErrorCodeTests(SimpleTestCase):
    """The provider's error ``Code`` reaches the message only if it looks like one.

    An S3-compatible endpoint is operator-configured but not trusted to be
    well-behaved: nothing it returns may be relayed to the browser verbatim.
    """

    def explain(self, code):
        error = ClientError({"Error": {"Code": code, "Message": "ignored"}}, "PutObject")
        return storage._explain_s3(error)

    def test_an_ordinary_unrecognised_code_is_named_because_it_helps_diagnosis(self):
        self.assertIn("SlowDown", self.explain("SlowDown"))

    def test_a_code_that_is_not_shaped_like_a_code_is_never_relayed(self):
        for hostile in (
            "<script>alert(1)</script>",
            "Line one\nLine two",
            "x" * 500,
            "Traceback (most recent call last): password=hunter2",
            "has spaces",
        ):
            with self.subTest(code=hostile[:30]):
                message = self.explain(hostile)
                self.assertNotIn(hostile[:20], message)
                self.assertIn("unknown error", message)
                self.assertLess(len(message), 120)

    def test_a_missing_code_is_reported_as_unknown(self):
        self.assertIn("unknown error", self.explain(""))
