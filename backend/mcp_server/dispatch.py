"""In-process GET sub-requests to existing REST views (ADR 0025 §2).

A tool never queries the ORM for data. It calls :func:`dispatch_get` (or
:func:`dispatch_get_all` for a paginated list) with the REST path it needs,
resolved the same way Django's URL dispatcher would resolve any other
request. The sub-request is authenticated as the MCP caller through DRF's
forced-authentication hook, so the resolved view runs its normal permission
classes, queryset scoping, serializers and audit hooks for that user — a
tool can never see data the same user could not fetch from the REST API
itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest, QueryDict
from django.urls import Resolver404, resolve

MAX_PAGES_DEFAULT = 10


class DispatchError(Exception):
    """Raised when a sub-request cannot be made at all (not an HTTP error
    from the resolved view — those come back as a normal ``SubResponse``).
    """


@dataclass
class SubResponse:
    status: int
    data: Any


def _build_request(outer_request, path: str, params: dict | None) -> HttpRequest:
    # ``outer_request`` may be a DRF ``Request`` (wrapping ``._request``) or
    # already the raw ``HttpRequest`` — accept either so callers (the view,
    # and tests) do not have to know which.
    outer = getattr(outer_request, "_request", outer_request)

    request = HttpRequest()
    request.method = "GET"
    request.path = path
    request.path_info = path
    query = QueryDict(mutable=True)
    for key, value in (params or {}).items():
        if value is None:
            continue
        query[key] = value
    request.GET = query
    request.POST = QueryDict()
    request.COOKIES = {}

    # Copy just enough META for downstream code (audit IP/user-agent
    # capture, absolute URL building) to behave the same as a real request,
    # without carrying over the outer request's body/content-type.
    for key in ("REMOTE_ADDR", "HTTP_USER_AGENT", "HTTP_X_REQUEST_ID", "SERVER_NAME", "SERVER_PORT", "wsgi.url_scheme"):
        value = outer.META.get(key)
        if value is not None:
            request.META[key] = value
    request.META.setdefault("SERVER_NAME", "localhost")
    request.META.setdefault("SERVER_PORT", "80")
    return request


def dispatch_get(
    outer_request,
    path: str,
    params: dict | None,
    *,
    allowed_url_names: frozenset[str],
    api_key,
    user,
    on_dispatch=None,
) -> SubResponse:
    """Issue one in-process ``GET`` sub-request.

    Raises :class:`DispatchError` if ``path`` does not resolve to a URL name
    in ``allowed_url_names`` — the allow-list is checked by *resolved URL
    name*, not by the literal path string, so this cannot be tricked by an
    equivalent path that resolves the same view under another route.
    """
    try:
        match = resolve(path)
    except Resolver404 as exc:
        raise DispatchError(f"No such endpoint: {path}") from exc

    if match.url_name not in allowed_url_names:
        raise DispatchError(f"Endpoint not allowed for this tool: {match.url_name}")

    request = _build_request(outer_request, path, params)
    request.resolver_match = match

    # Forced authentication (rest_framework.request.Request.__init__): the
    # sub-request runs as the same user/credential as the outer MCP call, so
    # the resolved view's own permission classes and queryset scoping decide
    # what it can see — no second copy of that logic lives here.
    request._force_auth_user = user
    request._force_auth_token = api_key

    from audit.models import AuditEventSource

    request.audit_source = AuditEventSource.MCP
    request.api_key = api_key
    request.mcp_subrequest = True

    outer_raw = getattr(outer_request, "_request", outer_request)
    request.audit_request_id = getattr(outer_raw, "audit_request_id", None)
    request.audit_ip_address = getattr(outer_raw, "audit_ip_address", None)
    request.audit_user_agent = getattr(outer_raw, "audit_user_agent", "")

    if on_dispatch is not None:
        on_dispatch()

    response = match.func(request, *match.args, **match.kwargs)
    # DRF Response objects carry ``.data`` pre-render; a plain HttpResponse
    # (none of the allow-listed views return one) would not, so this is a
    # deliberate assumption about what the allow-list may ever contain.
    data = getattr(response, "data", None)
    return SubResponse(status=response.status_code, data=data)


def dispatch_get_all(
    outer_request,
    path: str,
    params: dict | None,
    *,
    allowed_url_names: frozenset[str],
    api_key,
    user,
    max_pages: int = MAX_PAGES_DEFAULT,
    limit: int | None = None,
    on_dispatch=None,
) -> tuple[list, bool, int | None]:
    """Follow a ``{"count","next","results"}`` paginated list response.

    Returns ``(rows, truncated, total)``. ``truncated`` is ``True`` when
    ``max_pages`` or ``limit`` stopped the walk before the list actually
    ended. Stops as soon as ``limit`` rows have been collected (if given).
    A non-paginated (non-2xx, or unexpected shape) first response is
    returned as a single "page" of zero rows with the caller left to inspect
    ``status``/``data`` itself — callers that need the raw first response
    should use :func:`dispatch_get` directly instead.
    """
    rows: list = []
    total: int | None = None
    page = 1
    truncated = False
    params = dict(params or {})

    while page <= max_pages:
        page_params = dict(params)
        if page > 1:
            page_params["page"] = str(page)
        sub = dispatch_get(
            outer_request,
            path,
            page_params,
            allowed_url_names=allowed_url_names,
            api_key=api_key,
            user=user,
            on_dispatch=on_dispatch,
        )
        if sub.status != 200 or not isinstance(sub.data, dict) or "results" not in sub.data:
            # Not a paginated list (or an error) — hand back what we have.
            if page == 1:
                return [], False, None
            break

        total = sub.data.get("count", total)
        page_rows = sub.data.get("results") or []
        rows.extend(page_rows)

        if limit is not None and len(rows) >= limit:
            rows = rows[:limit]
            truncated = total is not None and total > len(rows)
            return rows, truncated, total

        if not sub.data.get("next"):
            return rows, False, total
        page += 1

    # Exhausted max_pages without reaching the end.
    truncated = True
    return rows, truncated, total
