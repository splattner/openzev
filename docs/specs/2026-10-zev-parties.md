# Feature Spec: Parties of a ZEV and dated issuer, representative and landowner roles (#761 phase 2)

- Spec ID: SPEC-2026-10-zev-parties
- Status: Approved
- Scope: Major
- Type: Change
- Owners: Sebastian Plattner
- Created: 2026-10-02
- Target Release: next minor
- Related Issues: [#761](https://github.com/splattner/openzev/issues/761) (phase 2)
- Related ADRs: [ADR 0028](../adr/0028-zev-parties-and-dated-roles.md), [ADR 0027](../adr/0027-per-zev-access-grants.md) (accounts layer), [ADR 0001](../adr/0001-assignment-only-validity.md) (dated windows)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

The invoice issuer is found through a login ("the participant whose `user` is `Zev.owner`"),
nothing about who issues, represents or owns is dated, a vZEV with several landowners or an
outside representative cannot be recorded, and a participant can only be a person with a first
and last name (ADR 0028, Context).

**Outcome:**

- Every person or organisation of a ZEV is a `Party`; a participant is a party's billing
  relationship.
- Issuer, representative toward the VNB and landowner are dated roles of a party.
- Invoices, contracts and annual statements name the issuer valid on a date in the document.
- A participant can be an organisation, and carry a second name line.
- `Zev.owner` is gone; access comes from grants only (ADR 0027), the issuer from the role.

The invoice copy of issuer and recipient
([SPEC invoice-lifecycle §3.1a](2026-03-invoice-lifecycle-and-communication.md), #875) shipped
first and is a prerequisite.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Model | `zev.Party`; `Participant.party` + read-through facade; `zev.ZevPartyRole`; drop `Zev.owner` |
| Documents | Issuer from the dated role in the invoice copy, contracts, annual statements, the reports default participant; organisation and `name_addition` in names and QR bill |
| Templates | New `issuer.*`, `representative.*`, `participant.display_name` / `name_lines` / `organisation_name`; `owner_participant.*` / `zev.owner.*` as deprecated aliases |
| API | Parties and party-role endpoints; participant fields `party`, `kind`, `organisation_name`, `name_addition`, `display_name` |
| Creation flows | Wizard, self-setup, admin create and transfer import create the party, roles and an explicit manager grant |
| Transfer / backups | Archive format 5 (`parties`, `party_roles`); backups registry |
| Frontend | ZEV settings → Parties tab; participant form (kind, organisation, name addition, existing party); role badges; owner reads replaced |
| Docs | User guide (ZEV setup, participants), baseline specs |

### Out of scope

- Buildings and metering-point locations (#761 phase 3).
- IBAN / VAT number per issuer (stay on the ZEV, ADR 0028 decision 6).
- Parties shared across ZEVs; organisations of accounts.
- Using the representative in any generated document (recorded and exposed as template
  variables only).
- LEG (#515).

## 3. Actors, permissions, and ZEV scope

| Actor | Parties and roles of a ZEV |
|---|---|
| admin | Read and write in every ZEV |
| manager (grant) | Read and write in its ZEVs |
| viewer (grant) | Read in its ZEVs |
| participant | Its own participant rows' party fields through the existing participant endpoints (read); no party/role endpoints |
| no relation | Nothing |

Backend: the party and party-role viewsets use `ZevScopedQuerySetMixin` with
`zev_lookup = "zev"`, no participant path, and `BaseZevScopedPermission`
(`allow_participant_safe_methods = False`). Unsafe methods require `can_manage`; a disabled ZEV
is read-only for non-admins (unchanged rule). Frontend: the Parties tab sits in ZEV settings
(`ZEV_SCOPE`); write controls follow `useCommunityAccess().canManage`.

## 4. Data model

### 4.1 Party

**Model:** `zev.models.Party`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` PK | `uuid4` | |
| `zev` | FK → `Zev` | — | `CASCADE`, `related_name="parties"` |
| `kind` | `CharField(20)` choices `PartyKind` | `person` | `person`, `organisation` |
| `title` | `CharField(10)` choices `Participant.Title` (moved as `PartyTitle`) | `""` | blank |
| `first_name` | `CharField(100)` | `""` | blank |
| `last_name` | `CharField(100)` | `""` | blank |
| `organisation_name` | `CharField(200)` | `""` | blank |
| `name_addition` | `CharField(200)` | `""` | blank; second name line ("and Max Muster", "c/o …") |
| `email` | `EmailField` | `""` | blank |
| `phone` | `CharField(30)` | `""` | blank |
| `address_line1` | `CharField(200)` | `""` | blank |
| `address_line2` | `CharField(200)` | `""` | blank |
| `postal_code` | `CharField(10)` | `""` | blank |
| `city` | `CharField(100)` | `""` | blank |
| `notes` | `TextField` | `""` | blank |
| `created_at`, `updated_at` | `DateTimeField` | auto | |

`Meta.ordering = ["organisation_name", "last_name", "first_name", "id"]`.

**`clean()`:** a `person` needs `last_name` (`"A person needs a last name."`); an
`organisation` needs `organisation_name` (`"An organisation needs a name."`).

**Properties:**

- `person_name` — `"{title display} {first_name} {last_name}"`, stripped (today's
  `Participant.full_name`).
- `display_name` — `organisation_name` for an organisation, else `person_name`.
- `name_lines` — `[display_name]`, then `name_addition` when set; for an organisation with a
  contact person, the contact person is **not** a name line (it goes on documents only where a
  template asks for it).
- `qr_name` — `display_name`, then `" " + name_addition` when set, cut at 70 characters (the
  QR-bill name limit).

**Signals:** the geocode cache warm-up (`zev.tasks.trigger_geocode_if_address_present`) moves
from participant saves to party saves (`transaction.on_commit`, unchanged rule: address line 1
and city present).

### 4.2 Participant

**Model:** `zev.models.Participant` — kept fields: `id`, `zev`, `user`, `valid_from`,
`valid_to`, `notes`, `allocation_weight`, `created_at`, `updated_at`.

| Change | Detail |
|---|---|
| `party` | New FK → `Party`, `PROTECT`, `related_name="participations"`; must be in the same ZEV (`clean()`: `"The party belongs to another ZEV."`) |
| `title`, `first_name`, `last_name`, `email`, `phone`, `address_line1`, `address_line2`, `postal_code`, `city` | Columns removed; become facade properties (§4.3) |
| `full_name` | Property → `party.display_name` (an organisation participant shows its organisation name everywhere `full_name` is read) |
| `Meta.ordering` | `["party__organisation_name", "party__last_name", "party__first_name", "id"]` |

`Participant.Title` stays as an alias of `PartyTitle` so `Participant.Title.MS` keeps working.

### 4.3 Participant facade

For each moved field `f`:

- **getter:** `self._pending[f]` if staged, else `getattr(self.party, f)` when a party is set,
  else `""`.
- **setter:** stores the value in `self._pending[f]`.

`Participant(..., first_name="A")` works because Django's `Model.__init__` accepts property
names. `save()` (in one `transaction.atomic()`):

1. No `party`: create one in the participant's ZEV from the staged values (`kind="person"`
   unless `kind` was staged), `full_clean()` it.
2. A party and staged values: write them to the party, `full_clean()`, save it.
3. Clear `_pending`, save the participant.

`kind`, `organisation_name` and `name_addition` are staged the same way. `refresh_from_db()`
clears `_pending`. ORM lookups do not go through the facade: every `filter`, `order_by`,
`values` and `select_related` on the moved fields uses `party__<field>`
(`invoices/period_overview.py`, `invoices/annual_statement_export.py`, `zev/transfer/export.py`,
participant search in `zev/views.py`, `Meta.ordering`), and querysets that read names add
`select_related("party")`.

### 4.4 ZevPartyRole

**Model:** `zev.models.ZevPartyRole`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` PK | `uuid4` | |
| `zev` | FK → `Zev` | — | `CASCADE`, `related_name="party_roles"` |
| `party` | FK → `Party` | — | `CASCADE`, `related_name="roles"`; same ZEV (`clean()`) |
| `role` | `CharField(20)` choices `PartyRole` | — | `issuer`, `representative`, `landowner` |
| `valid_from` | `DateField` | — | |
| `valid_to` | `DateField` | `null` | inclusive end; `null` = open |
| `created_at`, `updated_at` | `DateTimeField` | auto | |

**Constraints:**

- `CheckConstraint(valid_to IS NULL OR valid_to >= valid_from)`, name
  `party_role_window_order`.
- `UniqueConstraint(fields=["zev", "role"], condition=Q(valid_to__isnull=True,
  role__in=["issuer", "representative"]), name="one_open_single_holder_role")`.
- `UniqueConstraint(fields=["zev", "party", "role"], condition=Q(valid_to__isnull=True),
  name="one_open_role_per_party")`.

**Overlap rule** (service, §4.5): for `issuer` and `representative`, no two rows of one ZEV may
share a day.

`Meta.ordering = ["role", "-valid_from", "id"]`.

### 4.5 Service `zev/parties.py`

| Function | Behaviour |
|---|---|
| `holders_on(zev, role, day) -> QuerySet[Party]` | Parties with that role active on `day` (`allocation.validity.active_on`) |
| `holder_on(zev, role, day) -> Party \| None` | First of `holders_on` for single-holder roles |
| `issuer_on(zev, day)` | `holder_on(zev, "issuer", day)` |
| `assign_role(zev, party, role, valid_from, *, valid_to=None)` | Single-holder roles: the role active on `valid_from` (if any) is ended `valid_from - 1 day`; a role starting after `valid_from` → `ValidationError` ("A later holder exists; end it first."). A role row whose window would become empty is deleted. Landowner: refuses a second open row for the same party. Atomic, `select_for_update` on the ZEV's rows of that role |
| `end_role(role_row, last_day)` | Sets `valid_to = last_day`; a row with `last_day < valid_from` is deleted |
| `ensure_initial_roles(zev, party, valid_from)` | Issuer + landowner from `valid_from` unless the ZEV already has an issuer; used by creation flows (§6) |

### 4.6 Zev

`owner` (and the `owned_zevs` reverse relation) is removed. `Zev.save()` no longer calls
`zev.access.sync_owner_grant`; `sync_owner_grant` and `ensure_a_manager` are deleted. The
`_loaded_owner_id` bookkeeping goes.

## 5. API contracts

### 5.1 Participants (`/api/v1/zev/participants/`)

`ParticipantSerializer` keeps every current field and adds:

| Field | Read / write | Notes |
|---|---|---|
| `party` | write-once on create, read | UUID of an existing party of the same ZEV to attach to (a second participation); absent → a new party from the name fields |
| `kind` | read/write | `person` \| `organisation` |
| `organisation_name` | read/write | |
| `name_addition` | read/write | |
| `display_name` | read-only | `party.display_name` |
| `roles` | read-only | `[{role, valid_from, valid_to}]` of the party, active today or later |

Name/contact/address fields write through to the party (shared by every participation of it).
Validation: a person needs `last_name`, an organisation `organisation_name`; attaching to a party
of another ZEV → 400 `{"party": ["The party belongs to another ZEV."]}`. The existing
`has_its_own_login` edit guard is unchanged. `full_name` stays (= `display_name`).

### 5.2 Parties (`/api/v1/zev/parties/`, new; `PartyViewSet`)

| Method | Path | Behaviour |
|---|---|---|
| GET | `/zev/parties/?zev_id=` | Parties of the ZEV, each with `participations: [{id, valid_from, valid_to}]` and `roles: [...]` |
| POST | `/zev/parties/` | Create a non-participant party (`zev`, kind, names, contact, address) |
| GET / PATCH | `/zev/parties/{id}/` | Read / edit; edits show on every participation |
| DELETE | `/zev/parties/{id}/` | Only without participations and roles → else 400 `"This party is still a participant or holds a role."` |

Serializer `PartySerializer`: `id`, `zev`, `kind`, `title`, `first_name`, `last_name`,
`organisation_name`, `name_addition`, `email`, `phone`, `address_line1`, `address_line2`,
`postal_code`, `city`, `notes`, `display_name` (ro), `participations` (ro), `roles` (ro),
`created_at` (ro), `updated_at` (ro).

### 5.3 Party roles (`/api/v1/zev/party-roles/`, new; `ZevPartyRoleViewSet`)

| Method | Path | Behaviour |
|---|---|---|
| GET | `/zev/party-roles/?zev_id=&include_ended=` | Active and future roles; `include_ended=true` adds history |
| POST | `/zev/party-roles/` | `{zev, party, role, valid_from, valid_to?}` → `assign_role` (201); conflicts → 400 with the service message |
| POST | `/zev/party-roles/{id}/end/` | `{last_day}` → `end_role` (200, or 204 when the row was deleted) |

No PATCH/DELETE: history is changed by assigning or ending. Audit events (§10):
`party.create`, `party.update`, `party.delete`, `party_role.assign`, `party_role.end`, scoped to
the ZEV.

### 5.4 ZEVs

`ZevSerializer` drops `owner`. `ZevSerializer` gains read-only `issuer`
(`{party, display_name}` of today's issuer or `null`) for the switcher and the ZEV list.
`ZevViewSet.create` (admin) and self-setup grant the creator a manager role explicitly (§6).
The admin "change owner" (`PATCH zev.owner`) is gone.

## 6. Creation flows

| Flow | Creates |
|---|---|
| Wizard `create_zev_with_owner_setup` | Account (`role=user`, temporary password), ZEV, a **person party** from the owner data, the owner **participant** of that party (`valid_from = start_date`), **issuer + landowner** roles from `start_date`, a **manager grant** for the account, the metering points and their assignments |
| Self-setup `create_zev_for_existing_owner` | ZEV, the caller's party and participant, issuer + landowner, a manager grant for the caller |
| Admin `ZevViewSet.create` | The ZEV only (admins need no grant); parties, roles and access are added afterwards in ZEV settings |
| Transfer import | Parties and roles from the archive (§9); a manager grant for the importing account (unchanged behaviour of the old owner invariant) |

## 7. Documents and templates

### 7.1 Issuer by document

| Document | Issuer | Where |
|---|---|---|
| Invoice | `issuer_on(zev, invoice.period_end)` | `invoices/document_parties.build_issuer(zev, day)` — the copy (§3.1a of the invoice spec) |
| Contract | `issuer_on(zev, rendered_on)` | `invoices/contract_pdf.py` |
| Annual statement | `issuer_on(zev, date(year, 12, 31))` | `invoices/annual_statement.py` |
| Reports default participant (`views_reports.py`) | the caller's own row, else the issuer's participation in the ZEV | |

Without an issuer on that day: name = ZEV name, no address (`from_participant` → renamed
`from_party: false`), as today without an owner row.

### 7.2 Issuer copy schema change

`Invoice.issuer` gains `party` (UUID string), `kind`, `organisation_name`, `name_addition`, and
`name_lines` from `Party.name_lines`; `Invoice.recipient` the same from the participant's party.
`from_participant` is kept as an alias key of `from_party`. Old copies stay valid (missing keys
read as empty).

### 7.3 Template variables

| Variable | Meaning |
|---|---|
| `issuer.name`, `.name_lines`, `.kind`, `.organisation_name`, `.name_addition`, `.address_line1`, `.address_line2`, `.postal_code`, `.city`, `.email`, `.phone`, `.iban`, `.bank_name`, `.vat_number` | Issuer (invoice: from the copy; contract/statement: live on the document's date) |
| `representative.*` | Same name/contact/address keys for the representative on the document's date, or `None` |
| `participant.display_name`, `.name_lines`, `.organisation_name`, `.name_addition`, `.kind` | Recipient |
| `owner_participant.*` | Deprecated alias of `issuer` (`full_name` → `issuer.name`) |
| `zev.owner.get_full_name`, `zev.owner.email` | Deprecated alias → `issuer.name`, `issuer.email`; `zev.owner.username` → `""` |

`field_catalog_data.py` lists the new groups (`issuer`, `representative`) and drops the
`ownerParticipant` / owner-account entries; the deprecated aliases keep rendering. The built-in
templates (`templates/invoices/invoice_pdf.html`, `annual_statement_pdf.html`,
`templates/contracts/participant_contract_pdf.html`) use `issuer.*` and render
`issuer.name_lines` / `participant.name_lines` in address blocks. The QR bill uses
`Party.qr_name`.

## 8. Frontend

### 8.1 Types (`frontend/src/types/api.ts`)

```typescript
export type PartyKind = 'person' | 'organisation'
export type PartyRoleKind = 'issuer' | 'representative' | 'landowner'

export interface PartyRoleRow { id: string; zev: string; party: string; role: PartyRoleKind; valid_from: string; valid_to: string | null }

export interface Party {
    id: string; zev: string; kind: PartyKind
    title: string; first_name: string; last_name: string
    organisation_name: string; name_addition: string
    email: string; phone: string
    address_line1: string; address_line2: string; postal_code: string; city: string
    notes: string; display_name: string
    participations: Array<{ id: string; valid_from: string; valid_to: string | null }>
    roles: PartyRoleRow[]
}
```

`Participant` gains `party`, `kind`, `organisation_name`, `name_addition`, `display_name`,
`roles`. `Zev` loses `owner`, gains `issuer: { party: string; display_name: string } | null`.

### 8.2 API client (`lib/api/zev.ts`)

`fetchParties(zevId)`, `createParty`, `updateParty`, `deleteParty`,
`fetchPartyRoles(zevId, { includeEnded })`, `assignPartyRole`, `endPartyRole`; query keys
`zev.parties(zevId)`, `zev.partyRoles(zevId, includeEnded)`.

### 8.3 ZEV settings → Parties (`features/zev/ZevPartiesSection.tsx`, new)

Tab `parties` after General. Sections:

- **Issuer** and **Representative**: today's holder with "since", the history behind "Show
  history", and "Change from…" (party picker + date) for managers.
- **Landowners**: list with "since/until"; add (party picker + date), end (date).
- **Other parties**: non-participant parties (contact cards); add / edit (person or
  organisation form) / delete (only unused).

Party picker: every party of the ZEV by `display_name`, with "New contact…" opening the party
form. Viewers see everything read-only. Follows
`2026-04-frontend-management-page-design.md` (action hierarchy, `ConfirmDialog` for ending a
role, responsive layout).

### 8.4 Participants

- Participant form: kind switch (person / organisation), organisation name, name addition; on
  create, "Same person as an existing participant" picks a party (fills and locks the name
  fields).
- Cards show `display_name`, the name addition, and role badges (Issuer, Representative,
  Landowner) replacing the "Owner" badge (which compared `zev.owner` with `participant.user`).

### 8.5 Owner reads replaced

`ZevListPage` (owner column and "change owner" dialog → issuer name, dialog removed), `Layout`
switcher subtitle (`issuer.display_name`), `zevForm.ts` (`owner` dropped), the wizard keeps its
"responsible person" form (it creates the issuer).

### 8.6 i18n

Keys in all four locales under `pages.zevSettings.tabs.parties`, `pages.zevSettings.parties.*`,
`pages.participants.kind.*`, `pages.participants.organisationName`,
`pages.participants.nameAddition`, `pages.participants.sameParty*`, `parties.roles.*`,
`admin.fields.issuer*` / `representative*` (field catalogue).

## 9. Transfer archive and backups

- Archive **format version 5**: new sections `parties` (`PARTY_FIELDS` + archive `id`) and
  `party_roles` (`party_id`, `role`, `valid_from`, `valid_to`), written before participants;
  `PARTICIPANT_FIELDS` loses the moved fields and gains `party_id`.
- Importing v1–4: one party per participant from its fields (`kind=person`), no roles (the
  archive never named the owner).
- `backups/registry.py`: `zev.Party` and `zev.ZevPartyRole` in the per-ZEV section;
  `restore_zev.py` drops the `owner_id` account transform.

## 10. Observability and audit

Audit events with `action_category=governance`, `target_type` `zev.Party` /
`zev.ZevPartyRole`, metadata `{role, valid_from, valid_to, party}` for roles. Party edits
through the participant endpoints keep the existing participant audit events.

## 11. Delivery

| PR | Content |
|---|---|
| 1 | Invoice issuer/recipient copy — shipped (#875) |
| 2 | This spec + ADR 0028 |
| 3 | `Party`, `Participant.party`, facade, data migration (one party per participant), ORM lookups, `kind` / `organisation_name` / `name_addition` / `display_name` in API, copy and QR — no other behaviour change |
| 4 | `ZevPartyRole`, `zev/parties.py`, data migration (issuer + landowner from the owner's party; a party from the owner account when it has no participant row), issuer by date in copy / contract / statement / reports, template variables and catalogue, read-only party and role endpoints |
| 5 | Drop `Zev.owner`: creation flows with explicit grants and roles, `ZevSerializer.issuer`, admin owner dialog removed, transfer v5, backups, frontend owner reads replaced |
| 6 | Party and role write endpoints, Parties tab, participant form and badges, user guide |

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A document's text changes after the migration | High | Golden comparison of rendered invoice, contract and statement HTML before/after on the dev data in PRs 3–5 |
| A query by participant name misses the move to `party__` | Medium | Columns are removed, so any leftover lookup fails loudly in tests |
| The facade hides an N+1 on `party` | Medium | `select_related("party")` on list querysets; query-count tests stay pinned |
| Two participations sharing a party surprise an editor | Low | The form says the name and address are shared; "same person" is an explicit choice |
| An old archive imports without an issuer | Low | Documents fall back to the ZEV name; the Parties tab shows "No issuer" as needing attention |

## 13. Test plan

- **PR 3** `zev/test_parties.py`: party validation (person/organisation), `display_name` /
  `name_lines` / `qr_name`; the facade (construct with kwargs, read, edit through, two
  participations share edits, refresh clears staged values); the migration (one party per
  participant, fields copied); `ParticipantSerializer` (new fields, `party` attach in the same
  ZEV only); ordering by party name; an organisation participant on the invoice copy and QR
  bill. Full suite unchanged.
- **PR 4** `zev/test_party_roles.py`: constraints, `assign_role` ending the previous holder,
  refusing a later holder, landowner duplicates, `end_role` deleting empty windows; the
  migration (issuer from the owner row, a new party when none); invoice / contract / statement
  issuer by date (before and after an issuer change); template aliases; the field catalogue.
- **PR 5**: creation flows (party, participant, roles, grant), no `owner` in API, transfer v5
  round trip and v4 import, backups restore; frontend owner reads.
- **PR 6**: party and role endpoints (scoping, viewer read-only, audit); frontend
  `zev-parties-section.test.ts`, participant form; user guide build.

## 14. Acceptance criteria

- [ ] A ZEV records several landowners, an issuer without a login and an outside representative.
- [ ] Changing the issuer from a date makes invoices for periods before that date name the old
      issuer and later ones the new issuer; issued invoices never change.
- [ ] An organisation participant appears with its name on invoices, QR bill and contracts; a
      household shows its second name line.
- [ ] `Zev.owner` no longer exists; creating a ZEV still gives its creator manager access and
      an issuer in one step.
- [ ] Custom templates using `owner_participant.*` / `zev.owner.*` keep rendering.
