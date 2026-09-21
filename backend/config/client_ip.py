"""Client IP selected through NUM_PROXIES trusted hops.

Same hop selection as DRF's ``SimpleRateThrottle.get_ident()``, reading the
same effective setting (``REST_FRAMEWORK["NUM_PROXIES"]``, wired from the
``NUM_PROXIES`` env var in ``config/settings.py``). Unlike DRF,
syntactically invalid addresses (forged headers) become ``None`` instead of a
throttle-bucket string, keeping the value safe for an inet column. This is for
persisted audit IPs; throttling remains DRF's native ``get_ident()`` behavior.

A missing setting (``None``) falls back to ``REMOTE_ADDR``. This differs from
DRF's legacy ``None`` branch, which trusts the full header; failing closed to
the direct peer is the safe choice for persisted audit data. Normal startup
always sets an integer (see ``config/settings.py``), so this only triggers if
the ``REST_FRAMEWORK`` key is removed.
"""

import ipaddress

from rest_framework.settings import api_settings


def client_ip(request) -> str | None:
    remote_addr = request.META.get("REMOTE_ADDR")
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    num_proxies = api_settings.NUM_PROXIES

    if not num_proxies or xff is None:
        candidate = (remote_addr or "").strip()
    else:
        addrs = [part.strip() for part in xff.split(",")]
        candidate = addrs[-min(num_proxies, len(addrs))]

    if not candidate:
        return None
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if getattr(addr, "scope_id", None):
        # Scoped IPv6 (fe80::1%eth0) parses but PostgreSQL inet rejects it.
        return None
    return candidate
