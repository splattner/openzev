"""Writing finished archives to a destination: a local directory or S3.

Kept free of model imports (destinations are passed in duck-typed) so
``models.py`` can use ``validate_local_path`` without a cycle.

Every failure that can reach an administrator is a ``DestinationError`` whose
message is written to be shown: it never contains a credential, a traceback or
a raw provider response.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

from django.conf import settings

from . import crypto

# boto3 uploads in parts above this size, in parallel; part size is what makes a
# multi-gigabyte archive practical against a service with a 5 GiB single-PUT cap.
_S3_MULTIPART_THRESHOLD = 64 * 1024 * 1024


class DestinationError(Exception):
    """Storing to, or probing, a destination failed; ``str(exc)`` is user-safe."""


# ── local ────────────────────────────────────────────────────────────────────

def validate_local_path(path: str) -> str | None:
    """Why ``path`` cannot be a local destination, or ``None`` if it can.

    An archive must never be written somewhere the web server serves: it holds
    every account hash and every invoice, and ``MEDIA_ROOT`` is reachable in
    several deployment shapes.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        return "The path must be absolute."
    resolved = candidate.resolve()
    media = Path(settings.MEDIA_ROOT).resolve()
    if resolved == media or media in resolved.parents:
        return "The path must not be inside MEDIA_ROOT: archives contain private data and must not be web-reachable."
    if resolved.exists() and not resolved.is_dir():
        return "The path exists and is not a directory."
    return None


def _store_local(destination, source: Path, archive_name: str) -> str:
    problem = validate_local_path(destination.path)
    if problem:
        raise DestinationError(problem)
    target_dir = Path(destination.path)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / archive_name
        # Copy to a name nothing will mistake for a finished backup, then rename
        # atomically: a crash mid-copy leaves a ``.partial``, never a truncated
        # archive that looks complete.
        partial = target_dir / f".{archive_name}.{uuid.uuid4().hex[:8]}.partial"
        try:
            shutil.copyfile(source, partial)
            os.chmod(partial, 0o600)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    except OSError as exc:
        raise DestinationError(f"Could not write to {destination.path}: {exc.strerror or 'I/O error'}.") from exc
    return str(target)


def _probe_local(destination) -> None:
    problem = validate_local_path(destination.path)
    if problem:
        raise DestinationError(problem)
    target_dir = Path(destination.path)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / f".openzev-probe-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"openzev")
        probe.unlink()
    except OSError as exc:
        raise DestinationError(f"Could not write to {destination.path}: {exc.strerror or 'I/O error'}.") from exc


# ── S3 ───────────────────────────────────────────────────────────────────────

# What a real S3 error code looks like (``AccessDenied``, ``SlowDown``,
# ``RequestTimeTooSkewed``). Anything else from the endpoint is not relayed.
_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")

_S3_MESSAGES = {
    "AccessDenied": "Access denied: these credentials cannot write to the bucket.",
    "NoSuchBucket": "The bucket does not exist.",
    "InvalidAccessKeyId": "The access key id is not recognised by the endpoint.",
    "SignatureDoesNotMatch": "The secret access key does not match the access key id.",
    "InvalidBucketName": "The bucket name is not valid.",
    "AuthorizationHeaderMalformed": "The region does not match the bucket's region.",
    "PermanentRedirect": "The bucket lives in a different region or endpoint.",
    "RequestTimeTooSkewed": "This server's clock is too far from the storage service's clock.",
}


def _explain_s3(exc: Exception) -> str:
    """A safe sentence for a boto error; never includes credentials or raw responses."""
    from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, NoCredentialsError

    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in _S3_MESSAGES:
            return _S3_MESSAGES[code]
        # An operator-configured endpoint is not trusted to be well-behaved, so
        # an unrecognised code is named only if it is shaped like one. It helps
        # diagnosis; arbitrary text from the far end has no business in a response.
        label = code if _ERROR_CODE.fullmatch(code) else "unknown error"
        return f"The storage service refused the request ({label})."
    if isinstance(exc, NoCredentialsError):
        return (
            "No credentials were found. Set an access key and secret, set "
            "BACKUP_S3_ACCESS_KEY_ID / BACKUP_S3_SECRET_ACCESS_KEY, or run with an instance role."
        )
    if isinstance(exc, (EndpointConnectionError, ConnectTimeoutError)):
        return "Could not reach the storage endpoint."
    return "Could not talk to the storage service."


def s3_client(destination):
    """A boto3 S3 client for ``destination``, honouring the credential precedence.

    Environment credentials beat stored ones beat boto3's default chain (an
    instance profile or IRSA), matching ``BackupDestination.credential_mode``.
    """
    import boto3
    from botocore.config import Config

    options: dict = {
        "retries": {"max_attempts": 5, "mode": "standard"},
        "signature_version": "s3v4",
    }
    if destination.endpoint_url:
        # Path-style addressing suits MinIO/Garage and most self-hosted stores.
        # boto3 1.36+ also adds an integrity checksum to every upload by default,
        # which many S3-compatible services reject; ask for one only when the
        # operation requires it.
        options["s3"] = {"addressing_style": "path"}
        options["request_checksum_calculation"] = "when_required"
        options["response_checksum_validation"] = "when_required"
    if destination.credential_mode == "environment":
        credentials = {
            "aws_access_key_id": settings.BACKUP_S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.BACKUP_S3_SECRET_ACCESS_KEY,
        }
    elif destination.credential_mode == "stored":
        try:
            credentials = {
                "aws_access_key_id": destination.access_key_id,
                "aws_secret_access_key": destination.secret_access_key,
            }
        except crypto.BackupCryptoError as exc:
            raise DestinationError(str(exc)) from exc
    else:
        credentials = {}
    return boto3.client(
        "s3",
        region_name=destination.region or None,
        endpoint_url=destination.endpoint_url or None,
        config=Config(**options),
        **credentials,
    )


def _s3_key(destination, name: str) -> str:
    prefix = destination.prefix.strip("/")
    return f"{prefix}/{name}" if prefix else name


def _s3_extra_args(destination) -> dict:
    return {"ServerSideEncryption": destination.server_side_encryption} if destination.server_side_encryption else {}


def _store_s3(destination, source: Path, archive_name: str) -> str:
    from boto3.s3.transfer import TransferConfig
    from botocore.exceptions import BotoCoreError, ClientError

    key = _s3_key(destination, archive_name)
    try:
        s3_client(destination).upload_file(
            str(source),
            destination.bucket,
            key,
            ExtraArgs=_s3_extra_args(destination),
            Config=TransferConfig(multipart_threshold=_S3_MULTIPART_THRESHOLD),
        )
    except (BotoCoreError, ClientError) as exc:
        raise DestinationError(_explain_s3(exc)) from exc
    return f"s3://{destination.bucket}/{key}"


def _probe_s3(destination) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    key = _s3_key(destination, f".openzev-probe-{uuid.uuid4().hex[:8]}")
    try:
        client = s3_client(destination)
        client.put_object(Bucket=destination.bucket, Key=key, Body=b"openzev", **_s3_extra_args(destination))
        client.delete_object(Bucket=destination.bucket, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise DestinationError(_explain_s3(exc)) from exc


# ── entry points ─────────────────────────────────────────────────────────────

def store_archive(destination, source: Path, archive_name: str) -> str:
    """Write ``source`` to ``destination`` as ``archive_name``; returns its location."""
    if destination.kind == "s3":
        return _store_s3(destination, source, archive_name)
    return _store_local(destination, source, archive_name)


def probe_destination(destination) -> None:
    """Prove the destination is writable by writing and deleting a small object."""
    if destination.kind == "s3":
        _probe_s3(destination)
    else:
        _probe_local(destination)
