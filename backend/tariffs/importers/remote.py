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

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from hashlib import sha256

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
    request is handled and never leaves the server. The user gets a sentence
    they can act on about the URL *they* supplied.
    """

    def __init__(self, message: str, *, log_detail: str = ""):
        super().__init__(message)
        self.log_detail = log_detail or message


def _check_public_host(url: str) -> None:
    """Refuse URLs that resolve into the deployment's own network.

    Without this, an authenticated user could aim the import at the metadata
    service or an internal admin port and read the response back through the
    preview. Resolution here and connection later is a small TOCTOU window —
    closing it fully means connecting to a pinned address with a Host header,
    which urllib does not make easy; the deployment's egress rules are the
    second layer.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise TariffFetchError(
            f"Only http and https URLs can be imported, not {parsed.scheme or 'a URL without a scheme'}."
        )
    host = parsed.hostname
    if not host:
        raise TariffFetchError("The URL has no host name.")

    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise TariffFetchError(
            f"The host {host} could not be resolved. Check the address for a typo.",
            log_detail=f"getaddrinfo({host!r}) failed: {exc}",
        ) from exc

    for family, _type, _proto, _canonname, sockaddr in addresses:
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global or address.is_multicast:
            # The resolved address stays out of the message on purpose: see
            # TariffFetchError. The host is repeated because the user typed it.
            raise TariffFetchError(
                f"{host} does not resolve to a public address. Tariff documents must be "
                "fetched from the operator's public website.",
                log_detail=f"{host!r} resolved to {address}, which is not globally routable.",
            )


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the address check on every hop.

    A public URL that 302s to ``http://169.254.169.254/`` would otherwise walk
    straight past the check on the original URL.
    """

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_tariff_document(url: str) -> tuple[dict, str]:
    """Download and decode the document at ``url``.

    Returns the decoded payload and a SHA-256 digest of the exact bytes, which
    lets the apply step verify it is writing the document the user previewed.
    """
    url = (url or "").strip()
    if not url:
        raise TariffFetchError("No URL was given.")
    _check_public_host(url)

    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*;q=0.5"}
    )
    opener = urllib.request.build_opener(_ValidatingRedirectHandler)

    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_DOCUMENT_BYTES:
                raise TariffFetchError(
                    f"The document is {int(declared) // 1024} KB, larger than the "
                    f"{MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit."
                )
            # One byte past the cap, so a document that lies about (or omits)
            # its length is still caught by what actually arrived.
            body = response.read(MAX_DOCUMENT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # The status code is the actionable part; the reason phrase comes from
        # a server the user pointed us at, so it is logged rather than echoed.
        raise TariffFetchError(
            f"The operator's server answered HTTP {exc.code}.",
            log_detail=f"HTTP {exc.code} {exc.reason} from {url}",
        ) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise TariffFetchError(
            "The document could not be downloaded. Check the address, and that the "
            "operator's site is reachable.",
            log_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    if len(body) > MAX_DOCUMENT_BYTES:
        raise TariffFetchError(
            f"The document is larger than the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit."
        )

    digest = sha256(body).hexdigest()
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TariffFetchError(
            "The document at this URL is not valid JSON. Check that the link points at "
            "the machine-readable tariff file and not at a web page.",
            log_detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    return payload, digest
