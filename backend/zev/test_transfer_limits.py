"""ZIP-level hardening limits on the transfer archive import path.

``open_archive`` validates limits before returning the ``ZipFile``, so a
hostile archive is rejected before a single member is read. Member-count
and size caps are patched down to small values; the path-traversal and
compression-ratio checks run against their real limits with small
in-memory archives.
"""

from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from testing.zips import ZIP_BOMB_BYTES, zip_upload
from zev.transfer.importer import open_archive
from zev.transfer.schema import ArchiveError
from zev.transfer import importer as transfer_importer


class TransferArchiveLimitTests(TestCase):
    def test_member_with_traversal_path_is_rejected(self):
        with self.assertRaisesRegex(ArchiveError, "unsafe path"):
            open_archive(zip_upload("archive.zip", {"../evil.txt": b"x"}))

    def test_member_with_backslash_traversal_path_is_rejected(self):
        # A Windows-style separator must not smuggle a ".." past the check.
        with self.assertRaisesRegex(ArchiveError, "unsafe path"):
            open_archive(zip_upload("archive.zip", {"..\\evil.txt": b"x"}))

    def test_member_with_drive_letter_path_is_rejected(self):
        # ``C:\evil`` is neither absolute nor a traversal, but is just as able
        # to escape a directory if a member is ever written to disk.
        with self.assertRaisesRegex(ArchiveError, "unsafe path"):
            open_archive(zip_upload("archive.zip", {"C:\\evil.txt": b"x"}))

    def test_member_with_absolute_path_is_rejected(self):
        with self.assertRaisesRegex(ArchiveError, "unsafe path"):
            open_archive(zip_upload("archive.zip", {"/etc/passwd": b"x"}))

    def test_archive_with_too_many_members_is_rejected(self):
        members = {f"readings/{i}.csv": b"meter_id,timestamp,energy_kwh\n" for i in range(6)}
        with mock.patch.object(transfer_importer, "MAX_TRANSFER_MEMBERS", 5):
            with self.assertRaisesRegex(ArchiveError, "too many members"):
                open_archive(zip_upload("archive.zip", members))

    def test_archive_over_decompressed_cap_is_rejected(self):
        with mock.patch.object(transfer_importer, "MAX_TRANSFER_DECOMPRESSED_BYTES", 100):
            with self.assertRaisesRegex(ArchiveError, "too large when decompressed"):
                open_archive(zip_upload("archive.zip", {"readings/0.csv": b"x" * 200}))

    def test_archive_over_compressed_cap_is_rejected(self):
        with mock.patch.object(transfer_importer, "MAX_TRANSFER_COMPRESSED_BYTES", 10):
            with self.assertRaisesRegex(ArchiveError, "too large"):
                open_archive(zip_upload("archive.zip", {"readings/0.csv": b"x" * 200}))

    def test_archive_with_a_high_ratio_member_is_rejected(self):
        with self.assertRaisesRegex(ArchiveError, "suspicious compression ratio"):
            open_archive(zip_upload("archive.zip", {"readings/bomb.csv": ZIP_BOMB_BYTES}))

    def test_archive_that_is_not_a_zip_is_rejected(self):
        with self.assertRaisesRegex(ArchiveError, "not a valid ZIP"):
            open_archive(SimpleUploadedFile("archive.zip", b"not a zip", content_type="application/zip"))

    def test_decompressed_cap_covers_the_documented_2m_row_scale(self):
        # One readings row is ~75 bytes of CSV and the transfer spec
        # contemplates archives at the 2M-row scale; an export that large
        # must round-trip instead of being refused at import.
        self.assertGreaterEqual(
            transfer_importer.MAX_TRANSFER_DECOMPRESSED_BYTES,
            2_000_000 * 75,
        )
