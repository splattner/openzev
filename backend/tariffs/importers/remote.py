"""
Fetches a grid operator's published tariff document over HTTP.

There is no central registry of these documents — Art. 7b StromVV obliges each
operator to publish at "a single freely accessible internet address" of its own
choosing — so the URL is necessarily supplied by the user. That makes this a
server-side request to an attacker-influenceable address, so the host is
resolved and checked against private address space before the request is made,
and again on every redirect hop.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from hashlib import sha256

from config.net import PublicHostError, check_public_host

#: Published documents are tens of kilobytes; the largest imaginable is a
#: national operator listing every municipality it serves.
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20
MAX_REDIRECTS = 5

USER_AGENT = "OpenZEV/1.0 (tariff import; +https://github.com/splattner/openzev)"

# http is allowed alongside https: several operators still publish the document
# on a plain-http path, and refusing them would make the feature useless for
# their customers. The document is public, signed by nothing either way.
ALLOWED_SCHEMES = frozenset({"http", "https"})


class TariffFetchError(Exception):
    """The document could not be retrieved.

    The message is returned to the user, so it must never describe the
    deployment's own network. Echoing a resolved address back — "that name
    resolves to 10.0.0.5, which is refused" — leaves the request blocked but
    hands over the answer anyway: point the import at an internal hostname and
    read the map off the error. The same goes for raw socket and TLS errors,
    which carry paths and library detail.

    So anything of that kind goes in ``log_detail``, which is logged where the
    request is handled and never leaves the server.
    """

    def __init__(
        self, message: str, *, log_detail: str = "", status_code: int | None = None,
        code: str = "unknown", params: dict | None = None
    ):
        super().__init__(message)
        self.log_detail = log_detail or message
        self.status_code = status_code
        self.code = code
        self.params = params or {}


def _check_public_host(url: str) -> None:
    """Refuse URLs that resolve into the deployment's own network."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise TariffFetchError("The URL is invalid.", code="invalid_url", log_detail=str(exc)) from exc
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise TariffFetchError(
            f"Only http and https URLs can be imported, not {parsed.scheme or 'a URL without a scheme'}.",
            code="public_url",
        )
    try:
        check_public_host(url, allowed_schemes=ALLOWED_SCHEMES)
    except PublicHostError as exc:
        if exc.reason == "unresolved":
            raise TariffFetchError(
                f"The host {parsed.hostname} could not be resolved. Check the address for a typo.",
                code="host_unresolved",
                params=dict(host=parsed.hostname),
                log_detail=exc.log_detail,
            ) from exc
        if exc.reason == "invalid_url":
            raise TariffFetchError(
                str(exc), code="invalid_url", log_detail=exc.log_detail
            ) from exc
        host = parsed.hostname or "the host"
        raise TariffFetchError(
            f"{host} does not resolve to a public address. Tariff documents must be fetched from the operator's public website.",
            code="public_url",
            log_detail=exc.log_detail,
        ) from exc


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the address check on every hop.

    A public URL that 302s to ``http://169.254.169.254/`` would otherwise walk
    straight past the check on the original URL.
    """

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, *, accept: str) -> tuple[bytes, str]:
    """Download the bytes at ``url`` and a SHA-256 digest of them.

    Shared by every document shape this module can fetch: the SSRF guard and
    size limit must stay in exactly one place, since a second copy is a second
    place to forget them.
    """
    url = (url or "").strip()
    if not url:
        raise TariffFetchError("No URL was given.", code="import_url")
    _check_public_host(url)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    opener = urllib.request.build_opener(_ValidatingRedirectHandler)

    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_DOCUMENT_BYTES:
                raise TariffFetchError(
                    f"The document is {int(declared) // 1024} KB, larger than the "
                    f"{MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit.",
                    code="document_size",
                    params=dict(size=MAX_DOCUMENT_BYTES // (1024 * 1024)),
                )
            # One byte past the cap, so a document that lies about (or omits)
            # its length is still caught by what actually arrived.
            body = response.read(MAX_DOCUMENT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # The status code is the actionable part; the reason phrase comes from
        # a server the user pointed us at, so it is logged rather than echoed.
        raise TariffFetchError(
            f"The operator's server answered HTTP {exc.code}.",
            code="http_status",
            params=dict(status=exc.code),
            log_detail=f"HTTP {exc.code} {exc.reason} from {url}",
            status_code=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise TariffFetchError(
            "The document could not be downloaded. Check the address, and that the "
            "operator's site is reachable.",
            code="download_failed",
            log_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    if len(body) > MAX_DOCUMENT_BYTES:
        raise TariffFetchError(
            f"The document is larger than the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit.",
            code="document_size",
            params=dict(size=MAX_DOCUMENT_BYTES // (1024 * 1024)),
        )

    return body, sha256(body).hexdigest()


def fetch_tariff_document(url: str) -> tuple[dict, str]:
    """Download and JSON-decode the document at ``url``.

    Returns the decoded payload and a SHA-256 digest of the exact bytes, which
    lets the apply step verify it is writing the document the user previewed.
    """
    body, digest = _download(url, accept="application/json, */*;q=0.5")
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TariffFetchError(
            "The document at this URL is not valid JSON. Check that the link points at "
            "the machine-readable tariff file and not at a web page.", code="import_json",
            log_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    return payload, digest


def fetch_tariff_text(url: str) -> tuple[str, str]:
    """Download and decode the document at ``url`` as text (e.g. CSV).

    Returns the decoded text and a SHA-256 digest of the exact bytes.
    """
    body, digest = _download(url, accept="text/csv, text/plain, */*;q=0.5")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TariffFetchError(
            "The document at this URL is not valid UTF-8 text.",
            log_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    return text, digest
