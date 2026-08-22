"""ZIP-building helpers for upload-limit tests.

``test_import_limits`` and ``test_transfer_limits`` each carried a copy of
this before it was consolidated here.
"""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile


# 2 MB of zeros deflates to ~2 KB: ~1000:1, far past the 500:1 ratio caps.
ZIP_BOMB_BYTES = b"\0" * (2 * 1024 * 1024)


def zip_bytes(members, *, compress=zipfile.ZIP_DEFLATED):
    """Raw bytes of a ZIP holding the given ``{name: payload}`` members."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compress) as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)
    return buffer.getvalue()


def zip_upload(name, members, **kwargs):
    """A SimpleUploadedFile ZIP for POSTing as multipart."""
    return SimpleUploadedFile(name, zip_bytes(members, **kwargs), content_type="application/zip")
