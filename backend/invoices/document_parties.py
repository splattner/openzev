"""Who an invoice is from and to, copied onto the invoice (#761).

Amounts, prices and the VAT rate have always been copied onto ``Invoice`` /
``InvoiceItem`` when an invoice is generated. The issuer (name, address, IBAN,
VAT number) and the recipient's address were not: the PDF read them live, so
re-rendering a sent invoice showed whoever owned the ZEV *now*, their IBAN and
the participant's *current* address.

``Invoice.issuer`` and ``Invoice.recipient`` hold that copy. It is written when
the invoice is generated, refreshed on every render while the invoice is a
draft, written a last time on approval, and never touched again — so an
approved, sent, paid or cancelled invoice always renders the same document.
The PDF reads only the copy (``invoices.pdf``).

Schema (both plain JSON objects, every value a string unless noted):

``issuer``
    ``party`` (UUID or ``""``), ``kind``, ``organisation_name``,
    ``name_addition``, ``name``, ``name_lines`` (list of strings),
    ``address_line1``, ``address_line2``, ``postal_code``, ``city``, ``email``,
    ``phone``, ``iban``, ``bank_name``, ``vat_number``, ``zev_name``, and
    ``from_participant`` (bool: whether the issuer is a party on record,
    rather than the ZEV name alone).
``recipient``
    ``party``, ``kind``, ``organisation_name``, ``name_addition``, ``name``,
    ``name_lines``, ``title``, ``first_name``, ``last_name``,
    ``address_line1``, ``address_line2``, ``postal_code``, ``city``, ``email``.

A copy written before parties existed lacks the party keys; they read as empty.
"""

from __future__ import annotations

from django.db.models import Q

from .models import Invoice, InvoiceStatus


def _text(value) -> str:
    return (value or "").strip() if isinstance(value, str) else ("" if value is None else str(value))


def issuer_party(zev):
    """The party the issuer block is taken from: the ZEV owner's own.

    The party of the owner account's participation in the ZEV. The dated
    issuer role replaces this lookup (#761 phase 2).
    """
    from zev.models import Party

    if zev.owner_id is None:
        return None
    return Party.objects.filter(zev=zev, participations__user_id=zev.owner_id).first()


def _party_keys(party) -> dict:
    return {
        "party": str(party.pk) if party is not None else "",
        "kind": _text(getattr(party, "kind", "")),
        "organisation_name": _text(getattr(party, "organisation_name", "")),
        "name_addition": _text(getattr(party, "name_addition", "")),
    }


def build_issuer(zev) -> dict:
    """The issuer block for an invoice of ``zev``, from today's data."""
    party = issuer_party(zev)
    name = party.display_name if party else zev.name
    return {
        **_party_keys(party),
        "name": _text(name),
        "name_lines": [_text(line) for line in party.name_lines] if party else [_text(name)],
        "address_line1": _text(getattr(party, "address_line1", "")),
        "address_line2": _text(getattr(party, "address_line2", "")),
        "postal_code": _text(getattr(party, "postal_code", "")),
        "city": _text(getattr(party, "city", "")),
        "email": _text(getattr(party, "email", "")),
        "phone": _text(getattr(party, "phone", "")),
        "iban": _text(zev.bank_iban),
        "bank_name": _text(zev.bank_name),
        "vat_number": _text(zev.vat_number),
        "zev_name": _text(zev.name),
        "from_participant": party is not None,
    }


def build_recipient(participant) -> dict:
    """The recipient block for an invoice billed to ``participant``."""
    party = participant.party
    return {
        **_party_keys(party),
        "name": _text(party.display_name),
        "name_lines": [_text(line) for line in party.name_lines],
        "title": _text(participant.title),
        "first_name": _text(participant.first_name),
        "last_name": _text(participant.last_name),
        "address_line1": _text(participant.address_line1),
        "address_line2": _text(participant.address_line2),
        "postal_code": _text(participant.postal_code),
        "city": _text(participant.city),
        "email": _text(participant.email),
    }


def build_copy(invoice) -> dict:
    """``{"issuer": …, "recipient": …}`` for ``invoice``, from today's data."""
    return {
        "issuer": build_issuer(invoice.zev),
        "recipient": build_recipient(invoice.participant),
    }


def copy_for_render(invoice) -> tuple[dict, dict]:
    """The issuer and recipient to render ``invoice`` with.

    A draft gets a fresh copy, stored with a conditional ``UPDATE`` that only
    matches while the row is still a draft: an approval that lands while this
    render runs keeps its own copy, which is then read back. Any other status
    renders its stored copy as is; one that has none (an invoice from before
    the copy existed, or created without it) gets one built now and stored, the
    best that is still available.
    """
    stored_issuer, stored_recipient = invoice.issuer or {}, invoice.recipient or {}
    if invoice.status != InvoiceStatus.DRAFT and stored_issuer and stored_recipient:
        return stored_issuer, stored_recipient

    fresh = build_copy(invoice)
    if invoice.pk is None:
        invoice.issuer, invoice.recipient = fresh["issuer"], fresh["recipient"]
        return invoice.issuer, invoice.recipient

    rows = Invoice.objects.filter(pk=invoice.pk)
    if invoice.status == InvoiceStatus.DRAFT:
        updated = rows.filter(status=InvoiceStatus.DRAFT).update(**fresh)
    else:
        updated = rows.filter(Q(issuer={}) | Q(recipient={})).update(**fresh)
    if updated:
        invoice.issuer, invoice.recipient = fresh["issuer"], fresh["recipient"]
    else:
        current = rows.values("issuer", "recipient").first()
        if current and current["issuer"] and current["recipient"]:
            invoice.issuer, invoice.recipient = current["issuer"], current["recipient"]
        else:
            invoice.issuer, invoice.recipient = fresh["issuer"], fresh["recipient"]
    return invoice.issuer, invoice.recipient


class FrozenView:
    """A live object with some attributes answered from the copy instead.

    Templates written against the live models (``participant.address_line1``,
    ``zev.vat_number``, operators' custom PDF templates among them) keep
    working, but the fields the copy holds come from the copy. Anything else —
    a method, a related object — falls through to the live object.
    """

    def __init__(self, live, values: dict):
        self._live = live
        self._values = values

    def __getattr__(self, name):
        values = self.__dict__.get("_values", {})
        if name in values:
            return values[name]
        return getattr(self.__dict__["_live"], name)

    def __str__(self):
        return str(self._live)


class IssuerView:
    """The issuer copy shaped like the participant row it used to be read from,
    so ``owner_participant.full_name`` / ``.address_line1`` keep rendering."""

    def __init__(self, issuer: dict):
        self._issuer = issuer

    def __getattr__(self, name):
        issuer = self.__dict__["_issuer"]
        if name == "full_name":
            return issuer.get("name", "")
        if name in issuer:
            return issuer[name]
        raise AttributeError(name)

    def __str__(self):
        return self._issuer.get("name", "")


def template_parties(invoice, issuer: dict, recipient: dict) -> dict:
    """The template variables that come from the copy.

    ``issuer`` / ``recipient`` are the new names. ``owner_participant``,
    ``participant`` and ``zev`` keep their old meaning for existing templates,
    answered from the copy where it has the field.
    """
    return {
        "issuer": issuer,
        "recipient": recipient,
        "owner_participant": IssuerView(issuer) if issuer.get("from_participant") else None,
        "participant": FrozenView(invoice.participant, {
            "full_name": recipient.get("name", ""),
            "display_name": recipient.get("name", ""),
            **{key: recipient[key] for key in (
                "title", "first_name", "last_name", "address_line1", "address_line2",
                "postal_code", "city", "email", "kind", "organisation_name", "name_addition",
                "name_lines",
            ) if key in recipient},
        }),
        "zev": FrozenView(invoice.zev, {
            "name": issuer.get("zev_name", ""),
            "vat_number": issuer.get("vat_number", ""),
            "bank_iban": issuer.get("iban", ""),
            "bank_name": issuer.get("bank_name", ""),
        }),
    }
