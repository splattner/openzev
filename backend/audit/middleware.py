import uuid

from config.client_ip import client_ip

from .constants import REQUEST_ID_PATTERN


class AuditRequestContextMiddleware:
    """Attach request-level metadata used by the audit service."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw_request_id = request.headers.get("X-Request-ID")
        if raw_request_id and REQUEST_ID_PATTERN.fullmatch(raw_request_id):
            request.audit_request_id = raw_request_id
        else:
            request.audit_request_id = str(uuid.uuid4())
        request.audit_ip_address = client_ip(request)
        request.audit_user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:500]
        request.audit_source = "api"
        return self.get_response(request)
