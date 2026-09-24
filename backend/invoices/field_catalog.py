"""Resolve curated template fields and examples from preview sample contexts."""

from .email_context import (
    build_invoice_email_context,
    build_magic_link_email_context,
    build_onboarding_email_context,
    build_verification_email_context,
)
from .field_catalog_data import (
    _ANNUAL_STATEMENT_FIELDS,
    _CONTRACT_FIELDS,
    _EMAIL_FIELDS,
    _INVOICE_FIELDS,
)
from .template_context import (
    build_sample_annual_statement_context,
    build_sample_contract_context,
    build_sample_invoice_context,
)

PDF_SAMPLE_CONTEXTS = {
    "invoice": build_sample_invoice_context,
    "contract": build_sample_contract_context,
    "annual_statement": build_sample_annual_statement_context,
}


# These sample factories delegate to the same pure builders used by the send
# paths, so sample and send paths use the same format keys.


def build_sample_invoice_email_context() -> dict:
    return build_invoice_email_context(
        invoice_number="INV-2026-001",
        zev_name="Solar Community Example",
        participant_name="Hans Beispiel",
        period_start="01.01.2026",
        period_end="31.01.2026",
        due_date="14.02.2026",
        total_chf="486.45",
    )


def build_sample_onboarding_email_context() -> dict:
    return build_onboarding_email_context(
        participant_name="Hans Beispiel",
        inviter_name="Maria Muster",
        zev_name="Solar Community Example",
        link_url="https://app.example.com/onboarding?token=7c1a9e4f2b6d8a3c5e0f1b2a3c4d5e6f",
        expiry_date="30.09.2026",
    )


def build_sample_verification_email_context() -> dict:
    return build_verification_email_context(
        verify_url="https://app.example.com/verify-email?token=7c1a9e4f2b6d8a3c5e0f1b2a3c4d5e6f",
    )


def build_sample_magic_link_email_context() -> dict:
    return build_magic_link_email_context(
        participant_name="Hans Beispiel",
        zev_name="Solar Community Example",
        link_url="https://app.example.com/signin/7c1a9e4f2b6d8a3c5e0f1b2a3c4d5e6f",
        valid_minutes=15,
    )


EMAIL_SAMPLE_CONTEXTS = {
    "invoice_email": build_sample_invoice_email_context,
    "participant_onboarding": build_sample_onboarding_email_context,
    "email_verification": build_sample_verification_email_context,
    "participant_magic_link": build_sample_magic_link_email_context,
}


PDF_FIELD_CATALOGS = {
    "invoice": _INVOICE_FIELDS,
    "contract": _CONTRACT_FIELDS,
    "annual_statement": _ANNUAL_STATEMENT_FIELDS,
}

EMAIL_FIELD_CATALOGS = _EMAIL_FIELDS


def _resolve_sample_path(sample_path: str, context) -> object:
    """Resolve a dotted path through dicts, objects, lists, or callables."""
    node = context
    for part in sample_path.split("."):
        if isinstance(node, (list, tuple)):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node[part]
        else:
            node = getattr(node, part)
    if callable(node):
        node = node()
    return node


def _entry_example(entry: dict, context) -> str | None:
    variable = entry.get("variable", "")
    sample_path = entry.get("sample_path", "")
    if "|safe" in variable or sample_path.startswith("tr."):
        return None
    try:
        value = _resolve_sample_path(sample_path, context)
    except (KeyError, IndexError, AttributeError, TypeError, ValueError):
        return None
    if value is None:
        return None
    text = str(value)
    if "<" in text and ">" in text:
        return None
    if len(text) > 200:
        return None
    return text


def _build_catalog(groups: list[dict], context: dict) -> list[dict]:
    return [
        {
            "group_key": group["group_key"],
            "group_title_key": group.get("group_title_key"),
            "fields": [
                {
                    "variable": entry["variable"],
                    "description_key": entry["description_key"],
                    "example": _entry_example(entry, context),
                }
                for entry in group["fields"]
            ],
        }
        for group in groups
    ]


def pdf_field_catalog(template_type: str) -> list[dict]:
    """Return a PDF field catalog with sample values."""
    groups = PDF_FIELD_CATALOGS.get(template_type)
    builder = PDF_SAMPLE_CONTEXTS.get(template_type)
    if groups is None or builder is None:
        return []
    return _build_catalog(groups, builder())


def email_field_catalog(template_key: str) -> list[dict]:
    """Return an email field catalog with sample values."""
    groups = EMAIL_FIELD_CATALOGS.get(template_key)
    builder = EMAIL_SAMPLE_CONTEXTS.get(template_key)
    if groups is None or builder is None:
        return []
    return _build_catalog(groups, builder())
