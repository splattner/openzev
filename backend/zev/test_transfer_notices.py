"""Known archive failures and normal warnings have optional UI metadata."""

import csv
import zipfile
from unittest.mock import Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from zev.transfer.importer import _Collector, _import_row_members, _import_supplementary_readings
from zev.transfer.schema import READINGS_DIR, SUPPLEMENTARY_READINGS_DIR


@pytest.mark.django_db
def test_invalid_archive_has_a_code_without_requiring_a_language_header(admin_client):
    response = admin_client.post("/api/v1/zev/zevs/inspect-archive/", {
        "file": SimpleUploadedFile("invalid.zip", b"invalid", content_type="application/zip"),
    }, format="multipart")
    assert response.status_code == 400
    assert response.json() == {
        "detail": "The uploaded file is not a valid ZIP archive.",
        "diagnostic": {"code": "archive_invalid_zip", "params": {}},
    }


@pytest.mark.parametrize("supplementary", [False, True])
@pytest.mark.parametrize("error,code", [
    (zipfile.BadZipFile("Bad CRC"), "archive_corrupt"),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"), "archive_csv_invalid"),
    (csv.Error("bad CSV"), "archive_csv_invalid"),
])
def test_archive_corruption_and_csv_failures_remain_distinct(error, code, supplementary):
    archive = Mock()
    directory = SUPPLEMENTARY_READINGS_DIR if supplementary else READINGS_DIR
    member = f"{directory}/meter.csv"
    archive.namelist.return_value = [member]
    archive.open.side_effect = error
    collector = _Collector()
    if supplementary:
        _import_supplementary_readings(archive, {}, collector)
    else:
        _import_row_members(archive, directory, None, {}, collector, batch_id=None, format_version=11)
    failure = collector.errors[0]
    assert failure["diagnostics"] == {"__all__": [{"code": code, "params": {"member": member}}]}
    assert str(error) in failure["errors"]["__all__"][0]
