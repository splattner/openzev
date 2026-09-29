"""Shared tool infrastructure: :class:`ToolContext`, :class:`Tool`, and the
errors a tool raises to produce an MCP ``isError`` result rather than a
JSON-RPC protocol error (SPEC-2026-mcp-server §5.4 — "tool ran, sub-request
answered 4xx" is a *result*, not a transport failure, so the model can react
to it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..dispatch import DispatchError, dispatch_get, dispatch_get_all


class ToolError(Exception):
    """A tool ran but could not produce an answer — becomes ``isError: true``
    with ``message`` as the content text. Raised for a sub-request that came
    back 4xx (message taken from the view's own error body) or for a
    disallowed/failed dispatch.
    """

    def __init__(self, message: str, *, status: str = "failed"):
        super().__init__(message)
        self.message = message
        # Audit status this failure maps to: "failed" (default) or "denied"
        # for a sub-request 403, per SPEC-2026-mcp-server §8.
        self.status = status


def sub_error_message(sub) -> str:
    """Best-effort human-readable message from a non-2xx ``SubResponse``."""
    data = sub.data
    if isinstance(data, dict):
        for key in ("error", "detail"):
            if key in data and isinstance(data[key], str):
                return data[key]
        if data:
            return str(data)
    return f"Request failed with status {sub.status}."


@dataclass
class ToolContext:
    """What a tool needs to do its work: the authenticated caller, and a way
    to reach the allow-listed REST views in-process."""

    request: Any  # the outer DRF Request/HttpRequest for the MCP call
    user: Any
    api_key: Any
    subrequest_count: int = field(default=0, init=False)

    def _count(self) -> None:
        self.subrequest_count += 1

    def get(self, path: str, params: dict | None = None, *, allowed_url_names: frozenset[str]):
        """One GET sub-request. Raises :class:`ToolError` if the endpoint is
        not on the tool's allow-list; returns the raw ``SubResponse``
        otherwise (including non-2xx — callers decide whether that is fatal).
        """
        try:
            return dispatch_get(
                self.request,
                path,
                params,
                allowed_url_names=allowed_url_names,
                api_key=self.api_key,
                user=self.user,
                on_dispatch=self._count,
            )
        except DispatchError as exc:
            raise ToolError(str(exc)) from exc

    def get_or_raise(self, path: str, params: dict | None = None, *, allowed_url_names: frozenset[str]):
        """Like :meth:`get`, but a non-2xx response becomes a
        :class:`ToolError` using the view's own error message.
        """
        sub = self.get(path, params, allowed_url_names=allowed_url_names)
        if sub.status >= 300:
            raise ToolError(
                sub_error_message(sub),
                status="denied" if sub.status == 403 else "failed",
            )
        return sub

    def get_all(
        self,
        path: str,
        params: dict | None = None,
        *,
        allowed_url_names: frozenset[str],
        max_pages: int = 10,
        limit: int | None = None,
    ) -> tuple[list, bool, int | None]:
        try:
            return dispatch_get_all(
                self.request,
                path,
                params,
                allowed_url_names=allowed_url_names,
                api_key=self.api_key,
                user=self.user,
                max_pages=max_pages,
                limit=limit,
                on_dispatch=self._count,
            )
        except DispatchError as exc:
            raise ToolError(str(exc)) from exc


class Tool:
    """Base class every tool in :mod:`mcp_server.tools` subclasses.

    ``name``/``title``/``description``/``input_schema`` describe the tool for
    ``tools/list``; ``allowed_url_names`` is this tool's slice of the
    allow-list in SPEC-2026-mcp-server §6.9, passed to every
    ``ToolContext.get*`` call so a tool can never be tricked into resolving an
    endpoint outside its declared set.
    """

    name: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[dict]
    allowed_url_names: ClassVar[frozenset[str]]
    read_only: ClassVar[bool] = True

    def run(self, ctx: ToolContext, arguments: dict) -> dict:
        raise NotImplementedError

    def descriptor(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
