import uuid

from config.client_ip import client_ip


class AuditRequestContextMiddleware:
    """Attach request-level metadata used by the audit service."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.audit_request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.audit_ip_address = client_ip(request)
        request.audit_user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:500]
        request.audit_source = "api"
        return self.get_response(request)
