"""Admin-only administration of the PDF and email templates.

These endpoints used to live as ``@action`` methods on ``InvoiceViewSet``, but
they are not invoice-domain code: they never touch the invoice queryset, and
they already record their audit events under ``AuditActionCategory.GOVERNANCE``
rather than ``INVOICE``. They sat on the viewset only because its router was a
convenient place to hang a URL.

Admin-ness is now enforced declaratively via ``IsAdmin`` instead of a
hand-written ``if not request.user.is_admin`` inside every handler, and the
DENIED audit event those hand-written checks used to write is recorded from
``permission_denied`` — so a new endpoint added to this module cannot silently
forget either one.

The URLs are unchanged; see ``invoices/urls.py``.
"""

import hashlib
import re

from django.conf import settings
from django.template import Context, Template
from django.template import engines
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event

from .models import EMAIL_TEMPLATE_DEFAULTS, EmailTemplate, PdfTemplate
from .template_context import (
    build_sample_annual_statement_context,
    build_sample_contract_context,
    build_sample_invoice_context,
)

# Template type → sample-context builder. The preview endpoint and PATCH
# validation share this mapping; ``template_type`` is supplied per URL.
SAMPLE_CONTEXTS = {
    "contract": build_sample_contract_context,
    "annual_statement": build_sample_annual_statement_context,
}

# Preview accepts exactly these template_type values. The PATCH save path
# keeps the helper's invoice fallback (its template_type arrives from fixed
# URL routes), but the preview reads template_type from the request body,
# where an unknown value must not silently render the invoice sample context.
PREVIEW_TEMPLATE_TYPES = frozenset(SAMPLE_CONTEXTS) | {"invoice"}


def _read_default_template(template_name: str) -> str:
    """Read the on-disk (default) content for a template."""
    path = settings.BASE_DIR / "templates" / template_name
    return path.read_text(encoding="utf-8")


INVALID_VAR_PATTERN = re.compile(r"__INVALID_TPL_VAR__:([A-Za-z0-9_.]+)")


def _render_with_sample_context(template_type: str, content: str, *, strict: bool = False) -> str:
    """Render a template body against its sample context.

    Used by the PATCH save path (``PdfTemplateView.patch``) so a broken
    template or a context-key drift is rejected at edit time instead of
    failing at document-render time. The preview endpoint validates
    ``template_type`` against ``PREVIEW_TEMPLATE_TYPES`` before calling this
    helper, so unknown types never reach here.

    In ``strict`` mode (save-time validation) the template renders through the
    ``strict-validation`` engine, whose ``string_if_invalid`` turns unknown
    *output* variables — including attribute typos like ``{{ participant.emali }}``,
    which the default engine would silently render as an empty string — into a
    sentinel; any sentinel in the output raises ``ValueError`` listing the
    offending variables. Preview stays non-strict so admins can type in
    progress.

    Two known limitations of save-time validation: variables consulted only
    inside control-flow tags (``{% if %}``/``{% for %}``) never resolve to a
    rendering position, so an unknown variable there passes strict validation;
    and only Django HTML rendering is exercised — WeasyPrint/CSS/PDF-render
    failures are not caught at save time. Both surfaces are handled by the
    preview endpoint and at document-render time instead.
    """
    build_context = SAMPLE_CONTEXTS.get(template_type, build_sample_invoice_context)
    if not strict:
        return Template(content).render(Context(build_context()))
    strict_engine = engines["strict-validation"]
    rendered = strict_engine.from_string(content).render(build_context())
    invalid_vars = sorted(set(m for m in INVALID_VAR_PATTERN.findall(rendered)))
    if invalid_vars:
        raise ValueError(f"Unknown template variables: {', '.join(invalid_vars)}")
    return rendered


def _default_digest(template_name: str) -> str:
    """sha256 of the on-disk default template content."""
    return hashlib.sha256(_read_default_template(template_name).encode("utf-8")).hexdigest()


def _is_stale(record, template_name: str) -> bool:
    """A stored override is stale when its saved digest no longer matches the
    current on-disk default (i.e. a release shipped a new default since the
    override was last saved). No row (default template) is never stale, and a
    blank digest (legacy row without provenance, migration `0009` backfills
    those) is never flagged — an unknown provenance must not alarm."""
    if record is None:
        return False
    if not record.default_digest:
        return False
    return record.default_digest != _default_digest(template_name)


class _AdminTemplateView(APIView):
    """Base class for the admin-only template endpoints.

    Subclasses that want a DENIED audit event when a non-admin is turned away
    override :meth:`denial_audit`; the event is then written for them, rather
    than by a hand-rolled permission check in each handler.
    """

    permission_classes = [IsAdmin]

    def denial_audit(self, request) -> dict | None:
        """Return ``record_audit_event`` kwargs for a denial, or ``None`` to skip."""
        return None

    def permission_denied(self, request, message=None, code=None):
        # Unauthenticated callers get a 401 and are deliberately not audited
        # here — only an authenticated user who lacks admin is a governance
        # event worth recording.
        if request.user.is_authenticated:
            details = self.denial_audit(request)
            if details:
                record_audit_event(
                    request=request,
                    action_category=AuditActionCategory.GOVERNANCE,
                    status=AuditEventStatus.DENIED,
                    **details,
                )
        super().permission_denied(request, message=message, code=code)


class PdfTemplateView(_AdminTemplateView):
    """Read, customise or reset one PDF HTML template.

    ``template_name`` and ``audit_action_prefix`` are supplied per-URL via
    ``as_view()``; the three PDF template endpoints differ only in those two.
    """

    template_name = ""
    audit_action_prefix = ""
    template_type = "invoice"

    def denial_audit(self, request) -> dict:
        return {
            "action_type": f"{self.audit_action_prefix}.update",
            "target_type": "invoices.PdfTemplate",
            "target_id": self.template_name,
            "target_display": self.template_name,
            "summary": f"Denied PDF template mutation by non-admin ({self.template_name}).",
        }

    def _record(self, request, *, action_suffix: str, summary: str) -> None:
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type=f"{self.audit_action_prefix}.{action_suffix}",
            target_type="invoices.PdfTemplate",
            target_id=self.template_name,
            target_display=self.template_name,
            summary=summary,
        )

    def get(self, request, *args, **kwargs):
        record = PdfTemplate.objects.filter(template_name=self.template_name).first()
        content = record.content if record else _read_default_template(self.template_name)
        return Response({
            "template_name": self.template_name,
            "content": content,
            "is_customized": record is not None,
            "is_stale": _is_stale(record, self.template_name),
        })

    def patch(self, request, *args, **kwargs):
        content = request.data.get("content")
        if not isinstance(content, str) or not content.strip():
            return Response({"error": "Template content is required."}, status=status.HTTP_400_BAD_REQUEST)
        # Validate before storing: a broken override or one that references
        # unknown context keys must never be persisted, or every document
        # render would fail later (in production, at email time). Strict mode
        # rejects unknown output variables (e.g. {{ participant.emali }}) that
        # the default engine would silently render as an empty string. Unknown
        # variables consulted only inside {% if %}/{% for %} control flow are
        # not output and therefore not caught here.
        try:
            _render_with_sample_context(self.template_type, content, strict=True)
        except Exception as exc:
            return Response(
                {"error": f"Template rendering error: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        PdfTemplate.objects.update_or_create(
            template_name=self.template_name,
            defaults={"content": content, "default_digest": _default_digest(self.template_name)},
        )
        self._record(request, action_suffix="update", summary=f"Updated PDF template {self.template_name}.")
        return Response({
            "template_name": self.template_name,
            "content": content,
            "is_customized": True,
            "is_stale": False,
            "detail": "PDF template updated successfully.",
        })

    def delete(self, request, *args, **kwargs):
        """Revert to the on-disk default."""
        PdfTemplate.objects.filter(template_name=self.template_name).delete()
        self._record(request, action_suffix="reset", summary=f"Reset PDF template {self.template_name} to default.")
        return Response({"template_name": self.template_name, "content": _read_default_template(self.template_name), "is_customized": False, "detail": "PDF template reset to default."})


class PdfTemplatePreviewView(_AdminTemplateView):
    """Render a PDF template with sample data and return the HTML preview.

    POST body: { "content": "<html>...", "template_type": "invoice" | "contract" | "annual_statement" }
    Returns: { "html": "<rendered html>" }
    """

    def post(self, request, *args, **kwargs):
        content = request.data.get("content")
        template_type = request.data.get("template_type", "invoice")

        if not isinstance(content, str) or not content.strip():
            return Response({"error": "Template content is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(template_type, str) or template_type not in PREVIEW_TEMPLATE_TYPES:
            return Response({"error": "Unsupported template type."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            rendered = _render_with_sample_context(template_type, content)
        except Exception as exc:
            return Response(
                {"error": f"Template rendering error: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"html": rendered})


class EmailTemplateListView(_AdminTemplateView):
    """List every email template with its current content (DB override or default)."""

    def get(self, request, *args, **kwargs):
        overrides = {et.template_key: et for et in EmailTemplate.objects.all()}
        result = []
        for key, defaults in EMAIL_TEMPLATE_DEFAULTS.items():
            override = overrides.get(key)
            result.append({
                "template_key": key,
                "subject": override.subject if override else defaults["subject"],
                "body": override.body if override else defaults["body"],
                "is_customized": override is not None,
            })
        return Response(result)


class EmailTemplateView(_AdminTemplateView):
    """Read, customise or reset a single email template.

    GET    — returns current subject+body (DB override if present, else hardcoded default).
    PATCH  — saves subject/body to the database.
    DELETE — removes the DB override, reverting to the hardcoded default.
    """

    def denial_audit(self, request) -> dict:
        template_key = str(self.kwargs.get("template_key") or "")
        return {
            "action_type": "template.email.update",
            "target_type": "invoices.EmailTemplate",
            "target_id": template_key,
            "target_display": template_key,
            "summary": "Denied email template mutation by non-admin.",
        }

    def _record(self, request, *, action_type: str, template_key: str, summary: str) -> None:
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type=action_type,
            target_type="invoices.EmailTemplate",
            target_id=template_key,
            target_display=template_key,
            summary=summary,
        )

    @staticmethod
    def _defaults_or_404(template_key):
        """Return ``(defaults, None)`` for a known key, else ``(None, 404 response)``."""
        defaults = EMAIL_TEMPLATE_DEFAULTS.get(template_key)
        if not defaults:
            return None, Response({"error": "Unknown template key."}, status=status.HTTP_404_NOT_FOUND)
        return defaults, None

    def get(self, request, template_key=None, *args, **kwargs):
        defaults, error = self._defaults_or_404(template_key)
        if error:
            return error
        record = EmailTemplate.objects.filter(template_key=template_key).first()
        return Response({
            "template_key": template_key,
            "subject": record.subject if record else defaults["subject"],
            "body": record.body if record else defaults["body"],
            "is_customized": record is not None,
        })

    def patch(self, request, template_key=None, *args, **kwargs):
        _defaults, error = self._defaults_or_404(template_key)
        if error:
            return error
        subject = request.data.get("subject")
        body = request.data.get("body")
        if not isinstance(subject, str) or not subject.strip():
            return Response({"error": "Subject is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(body, str) or not body.strip():
            return Response({"error": "Body is required."}, status=status.HTTP_400_BAD_REQUEST)
        EmailTemplate.objects.update_or_create(
            template_key=template_key,
            defaults={"subject": subject, "body": body},
        )
        self._record(
            request,
            action_type="template.email.update",
            template_key=template_key,
            summary=f"Updated email template {template_key}.",
        )
        return Response({
            "template_key": template_key,
            "subject": subject,
            "body": body,
            "is_customized": True,
            "detail": "Email template updated successfully.",
        })

    def delete(self, request, template_key=None, *args, **kwargs):
        """Revert to the hardcoded default."""
        defaults, error = self._defaults_or_404(template_key)
        if error:
            return error
        EmailTemplate.objects.filter(template_key=template_key).delete()
        self._record(
            request,
            action_type="template.email.reset",
            template_key=template_key,
            summary=f"Reset email template {template_key} to default.",
        )
        return Response({
            "template_key": template_key,
            "subject": defaults["subject"],
            "body": defaults["body"],
            "is_customized": False,
            "detail": "Email template reset to default.",
        })
