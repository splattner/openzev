"""Shared request helpers for the metering import tests.

The CSV upload and preview endpoints were duplicated verbatim across
``test_import_csv`` and ``test_import_csv_characterization`` before being
consolidated here.
"""

from django.core.files.uploadedfile import SimpleUploadedFile


def upload_csv(client, name, content, **fields):
    """POST a CSV file to the import endpoint, returning the response."""
    upload = SimpleUploadedFile(name, content, content_type="text/csv")
    return client.post(
        "/api/v1/metering/import/csv/", {"file": upload, **fields}, format="multipart"
    )


def preview_csv(client, name, content, **fields):
    """POST a CSV file to the preview endpoint, returning the response."""
    upload = SimpleUploadedFile(name, content, content_type="text/csv")
    return client.post(
        "/api/v1/metering/import/preview-csv/", {"file": upload, **fields}, format="multipart"
    )
