# ADR 0028: Every person or organisation of a ZEV is a party; issuer, representative and landowner are dated roles

- Status: Accepted (amended 2026-10-02: decision 8 — the issuer and the representative manage the ZEV)
- Date: 2026-10-02
- Related: ADR 0027 (accounts layer), ADR 0001 (dated validity windows)

## Context

ADR 0027 separated **accounts** (logins, per-ZEV grants) from the **parties** of a ZEV, and
decided the account side. The party side is still fused with accounts and with participants
([#761](https://github.com/splattner/openzev/issues/761), phase 2):

- The invoice issuer — the creditor on the QR bill, the sender on invoices, the counterparty
  on participation contracts — is found through a *login*: "the participant whose `user` is
  `Zev.owner`" (`invoices/document_parties.py`, `contract_pdf.py`, `annual_statement.py`,
  `views_reports.py`). The legal owner has no record of its own, and a ZEV whose owner never
  logs in cannot have a correct issuer.
- Nothing is dated. A sale of the property or a new property manager changes the issuer and the
  representative toward the grid operator (VNB) on a given day, and documents for periods
  before that day must keep the previous one.
- A vZEV is formed by the *landowners* (EnG Art. 17), often several. `Zev.owner` allows one.
- The representative toward the VNB is often an outside party (a Verwaltung) that consumes
  nothing in the ZEV. There is nowhere to record it.
- A participant is always a person with a first and last name. A company tenant or a household
  in which two people should appear on the invoice has nowhere to go.

Invoices already keep a copy of their issuer and recipient (#875), so the party model decides
what the copy is taken *from*; it does not have to guard issued documents itself.

## Decision

**1. Everything is a party.** A new `zev.Party` holds every person or organisation of a ZEV:
kind (`person` | `organisation`), names (`organisation_name`; `title`, `first_name`,
`last_name` — for an organisation, its contact person), a free `name_addition` line (a second
household member, "c/o …"), contact data and the postal address. Parties are scoped to one ZEV:
the same Verwaltung in two ZEVs is two party rows. That keeps every party under the ZEV's
existing scoping and transfer/backup boundaries; a cross-ZEV address book is not needed for any
document.

**2. A participant is a billing relationship of a party.** `Participant` keeps what is about
being billed in the ZEV — `valid_from`/`valid_to`, `allocation_weight`, `notes`, meter
assignments, invoices, the onboarding tokens and the account link `user` (ADR 0027 builds
scoping on it) — and gains `party` (required, `PROTECT`). The name, contact and address fields
move to the party. Several participant rows may share one party (someone moving within a ZEV, a
flat plus a business unit); editing the party changes them all, because it is the same person.

**3. Participant keeps a read-through facade during the transition.** `Participant.first_name`,
`last_name`, `title`, `email`, `phone`, the address fields and `full_name` become properties
that read the party, with setters that stage a value and a `save()` that creates or updates the
party in the same transaction. About 180 read sites and several hundred test fixtures keep
working unchanged; only ORM lookups (`ordering`, `order_by`, `filter`) move to `party__…`. The
API keeps the flat participant shape and writes through. The facade is a compatibility layer,
not the model: new code reads `participant.party`.

**4. Issuer, representative and landowner are dated roles a party holds.** A new
`zev.ZevPartyRole` (`zev`, `party`, `role`, `valid_from`, `valid_to` inclusive, as in ADR 0001):

- `issuer` — signs participation contracts and issues invoices. At most one on any day.
- `representative` — designated representative toward the VNB. At most one on any day.
- `landowner` — a member of the community in the EnG sense. Any number.

A change of issuer ends the previous role the day before the new one starts, so history is
kept. ~~Holding a role grants nothing in OpenZEV: access stays on grants (ADR 0027)~~ —
superseded by decision 8 for the issuer and the representative. A party without a login is
still the normal case.

**5. Which issuer a document names is fixed by a date in the document.** An invoice names the
issuer on its `period_end`; a contract the issuer on its `rendered_on`; an annual statement the
issuer on 31 December of its year. Without an issuer on that day, the document falls back to the
ZEV name alone, as today when the owner has no participant row.

**6. IBAN, bank name and VAT number stay on the ZEV.** They are settings of the community's
billing, not of a party; a change of issuer that changes them is an edit of the ZEV's
Billing & payment settings. Invoices copy them, so the change never alters an issued invoice.

**7. `Zev.owner` is removed.** Its two remaining jobs are replaced: the issuer by the `issuer`
role (decision 4), and "whoever owns the ZEV can manage it" by an explicit manager grant made
where a ZEV is created (wizard, self-setup, admin create, transfer import). Template variables
`owner_participant.*` and `zev.owner.*` stay as deprecated aliases of the new `issuer.*`.

**8. The issuer and the representative manage the ZEV (amendment).** Whoever issues a ZEV's
documents or represents it toward the grid operator is, in practice, who runs it — the owner of
a simple ZEV, or the property manager of a larger one — and keeping that in step by hand (a
role change in the Parties tab *and* a grant change in Zugang) was the friction the first
version of this ADR left. So:

- An account manages a ZEV while a party it belongs to holds the `issuer` or `representative`
  role there (`MANAGING_ROLES`). A party's accounts are its own (`Party.user`, new, for a party
  that is not a participant) and those of its participations (`Participant.user`).
- The access is **derived from the role row**, not copied into a grant: it starts and ends on
  the role's dates with no job and no second list to keep in step, and a grant given by hand is
  never touched by a role change. `zev.access` adds the role-holding ZEVs to an account's managed
  and viewable sets (one more query per request, memoised like the grants).
- A `landowner` gets nothing by its role (a landowner seeing every participant's consumption is a
  data-protection question, not a default). A contact gets nothing either; Zugang can give any
  party access, and invites a party without a login at its own email address.
- A role change that would leave a managed ZEV without any manager is refused, as revoking the
  last manager grant already is; the last-manager check counts role managers too.
- Zugang lists the role-derived managers read-only ("as issuer"), and the Parties tab says which
  login gets manager access before applying an issuer or representative change. The audit event
  of a role assignment names those logins.

Considered and rejected for this amendment: copying the role into grant rows (needs a daily job
for future-dated roles and must tell its own grants from hand-made ones) and giving the
representative viewer rights only (it is usually the operator; a party that only deals with the
grid operator can be entered as a contact with a viewer grant instead).

## Consequences

- A ZEV can be modelled as it is legally: several landowners, an issuer who never logs in, an
  outside representative, and changes on a date — without any account being involved.
- The simple ZEV stays one step: the wizard and self-setup create one person party that is
  participant, issuer and landowner at once.
- `Participant` stops being where names live. Reports, exports and templates that only read
  through the facade keep working; ordering and search change to `party__last_name`. The
  transfer archive gains `parties` and `party_roles` sections (format version 5); older
  archives import with one party per participant and no issuer role.
- Every document's issuer becomes a function of a date, which makes issuer changes safe but
  means a period invoice generated after a sale names the issuer of that period, not the one of
  the generation day.
- The facade is technical debt with a known exit: once nothing outside the participant
  serializer and the transfer code relies on it, it can be removed.

## Alternatives considered

- **Dated roles pointing at a participant or a separate contact record.** Smaller migration, but
  it keeps two kinds of "person" and a role that can point at either, and it cannot give a
  company or household participant a proper name without duplicating the contact record's
  fields on `Participant`. Rejected in favour of one party entity.
- **Global parties shared across ZEVs.** Would let a Verwaltung be one record for many ZEVs, but
  pulls parties out of every per-ZEV boundary (scoping, transfer, backups, deletion) for a
  benefit no document needs.
- **IBAN and VAT number on the issuer role.** More exact for a sale (payment details switch with
  the issuer by date), but moves community billing settings into a party editor and needs
  per-date validation; the invoice copy already protects issued documents. Can be revisited.
- **Keeping `Zev.owner` as a "billing owner".** Rejected in #761: it keeps the account/party
  fusion this change exists to remove.

## Notes

- Spec: `docs/specs/2026-10-zev-parties.md`.
- Issue: [#761](https://github.com/splattner/openzev/issues/761) phase 2. Buildings (phase 3)
  are independent of this decision.
