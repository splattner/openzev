"""Shared upload-hardening limits and ZIP validation.

Importers that accept uploads (CSV/Excel, SDAT-CH, transfer archives) enforce
the same shape of caps before doing expensive work. Rationale and tuning
guidance live in docs/specs/2026-03-metering-import-and-quality.md §4.4.
"""

import re

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_REPORTED_ERRORS = 50

# The ratio check ignores members under 1 MB decompressed: legitimate small
# members (sparse sheets, repeated CSV headers) compress far beyond the cap.
ZIP_RATIO_FLOOR_BYTES = 1_000_000

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def mb(num_bytes):
    return f"{num_bytes / (1024 * 1024):.0f} MB"


def add_error(errors: list, payload: dict):
    """Append to errors, capping at MAX_REPORTED_ERRORS with a truncation note."""
    if len(errors) < MAX_REPORTED_ERRORS:
        errors.append(payload)
    elif len(errors) == MAX_REPORTED_ERRORS:
        errors.append(
            {
                "row": None,
                "error": f"Too many errors — showing first {MAX_REPORTED_ERRORS}; further errors truncated.",
            }
        )


def validate_zip(zf, *, label, max_members, max_total_bytes, max_ratio, error_cls):
    """Reject a ZIP structured to exhaust memory or CPU when inflated.

    Checks member count, the declared decompressed total, and per-member
    compression ratio. Sizes come from the central directory, so these are
    trust bounds paired with the proxy body-size cap rather than a meter of
    actual inflation; row caps bound what is really read. Returns
    ``zf.infolist()`` for callers that need the members.
    """
    infos = zf.infolist()
    if len(infos) > max_members:
        raise error_cls(f"{label} has too many members ({len(infos)} > {max_members}).")
    total = sum(info.file_size for info in infos)
    if total > max_total_bytes:
        raise error_cls(
            f"{label} too large when decompressed ({mb(total)} > {mb(max_total_bytes)})."
        )
    for info in infos:
        if info.file_size and info.compress_size:
            ratio = info.file_size / info.compress_size
            if ratio > max_ratio and info.file_size > ZIP_RATIO_FLOOR_BYTES:
                raise error_cls(
                    f"{label} member {info.filename!r} has suspicious compression ratio ({ratio:.1f}:1)."
                )
    return infos


def reject_unsafe_member_path(name, *, error_cls, label="Archive"):
    """Reject member names that could escape a directory if ever extracted.

    Members are only ever streamed today, never written to disk; this guards
    the day that changes. Windows drive letters are included — a path check
    that lets ``C:\\evil`` through is half a guard.
    """
    if (
        name.startswith(("/", "\\"))
        or ".." in name.replace("\\", "/").split("/")
        or _WINDOWS_DRIVE.match(name)
    ):
        raise error_cls(f"{label} member has unsafe path: {name!r}.")
