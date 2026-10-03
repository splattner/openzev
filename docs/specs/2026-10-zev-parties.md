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
| Frontend | ZEV settings → People & access tab (roles, access, contacts); participant form (kind, organisation, name addition, existing party); role badges; owner reads replaced |
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
| account of the issuer or representative (§5.5) | Manager of that ZEV while the role lasts — the same as a manager grant |
| viewer (grant) | Read in its ZEVs |
| participant | Its own participant rows' party fields through the existing participant endpoints (read); no party/role endpoints |
| no relation | Nothing |

Backend: the party and party-role viewsets use `ZevScopedQuerySetMixin` with
`zev_lookup = "zev"`, no participant path, and `BaseZevScopedPermission`
(`allow_participant_safe_methods = False`). Unsafe methods require `can_manage`; a disabled ZEV
is read-only for non-admins (unchanged rule). Frontend: the People & access tab sits in ZEV settings
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
| `user` | FK → `User`, null | `null` | `SET_NULL`, `related_name="parties"`; the party's own login when it is not a participant (migration `zev.0038_party_user`). A participant's login stays on `Participant.user` |
| `sort_name` | `CharField(200)`, indexed, not editable | `""` | `organisation_name` (organisation) or `last_name` (person), set by `save()` |
| `created_at`, `updated_at` | `DateTimeField` | auto | |

`Meta.ordering = ["sort_name", "first_name", "id"]`, so organisations sort by
their name among people sorted by last name.

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
| `party` | New FK → `Party`, `RESTRICT`, `related_name="participations"`; must be in the same ZEV (`clean()`: `"The party belongs to another ZEV."`). `RESTRICT` (not `PROTECT`) so that deleting a ZEV cascades to both its parties and its participants |
| `title`, `first_name`, `last_name`, `email`, `phone`, `address_line1`, `address_line2`, `postal_code`, `city` | Columns removed; become facade properties (§4.3) |
| `full_name` | Property → `party.display_name` (an organisation participant shows its organisation name everywhere `full_name` is read) |
| `Meta.ordering` | `["party__sort_name", "party__first_name", "id"]` |
| Manager | `ParticipantManager` (default and base manager) always `select_related("party")`; a queryset that uses `.only()` without party fields calls `select_related(None)` first |

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

`kind`, `organisation_name` and `name_addition` are staged the same way
(`PARTY_FACADE_FIELDS` lists all twelve). `save(update_fields=[…])` routes facade
names to the party and saves only the rest on the participant (no participant
write when nothing else is left). `refresh_from_db()` clears `_pending`;
`refresh_from_db(fields=[…])` refreshes facade names on the party. ORM lookups do not go through the facade: every `filter`, `order_by`,
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

**Migrations (PR 4):** `zev.0035_party_role` creates the table; `zev.0036_party_roles_from_owner`
(depends on `invoices.0019`) gives every ZEV that has no issuer row yet, and whose owner account
has a participation in it, an `issuer` and a `landowner` row for that participation's party
(first by `party__sort_name, party__first_name, id`), open-ended, from the earliest of
`Zev.start_date`, the first participant `valid_from`, the first invoice `period_start` and the
first `ContractIssue.rendered_on` — so every document already dated in the ZEV keeps its issuer.
A ZEV whose owner has no participation gets no role (its documents keep naming the ZEV). The
reverse deletes every role row.

### 4.5 Service `zev/parties.py`

| Function | Behaviour |
|---|---|
| `holders_on(zev, role, day) -> QuerySet[Party]` | Parties with that role active on `day` (`allocation.validity.active_on`) |
| `holder_on(zev, role, day) -> Party \| None` | The party of the role row active on `day` (latest `valid_from`), one query with `select_related("party")` |
| `issuer_on(zev, day)` | `holder_on(zev, "issuer", day)`. Until `Zev.owner` is dropped (PR 5): a ZEV that has **no** issuer row at all falls back to the party of the owner account's participation (one more query, `~Exists(issuer rows)`), so a ZEV created without its owner as participant behaves as before once the owner is added |
| `representative_on(zev, day)` | `holder_on(zev, "representative", day)` |
| `assign_role(zev, party, role, valid_from, *, valid_to=None)` | A party of another ZEV → `ValidationError` on `party`; `valid_to < valid_from` → on `valid_to`. Single-holder roles: a row starting after `valid_from` → `ValidationError` ("A later holder exists; end it first."); every row still active on or after `valid_from` is ended `valid_from - 1 day` through `end_role` (deleted when that empties its window); the same party already holding the role open-ended is returned unchanged. Landowner: refuses a second open row for the same party ("The party already holds this role."). Atomic, `select_for_update` on the ZEV's rows of that role; the new row is `full_clean()`ed |
| `end_role(role_row, last_day)` | Sets `valid_to = last_day`; a row with `last_day < valid_from` is deleted |
| `ensure_initial_roles(zev, party, valid_from)` | Issuer + landowner from `valid_from` unless the ZEV already has an issuer row; called by the wizard and self-setup (`zev/services.py`, from PR 4) and `seed_demo` |

### 4.6 Zev

`owner` (and the `owned_zevs` reverse relation) is removed by `zev.0037_remove_zev_owner`:
`AlterField(null=True)`, a `RunPython` whose reverse fills `owner` with the ZEV's earliest
open manager grant (else its last one), then `RemoveField`, so the migration reverses.
`Zev.save()`/`Zev.from_db` are the plain model methods again; `sync_owner_grant` and
`ensure_a_manager` are deleted. New `zev.access.grant_manager(zev, user, *, by=None)`: an
active manager grant is kept, an open grant of another role is promoted (`change_role`), else
an open manager grant from today is created; only the transfer import uses it.
`zev.access.grant_manager_until_role(zev, user, role_start)`: `None` when `role_start <= today`,
else a manager grant `valid_from = today`, `valid_to = role_start − 1` (wizard and self-setup).
Migration `zev.0039_end_grants_covered_by_roles` (data, reverse no-op): every open manager grant
held by an account of a party with an open-ended issuer or representative role that applies
today is ended yesterday (deleted when it starts today or later). `issuer_on` loses its owner fallback (PR 4). The
participant "cannot unlink the owner account" rule goes. Django admin drops the `owner` column.

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
| `roles` | read-only | `[{id, role, valid_from, valid_to}]` of the party, active today or later, sorted by role then `valid_from` (`serializers.current_roles`, from the `party__roles` prefetch; from PR 4) |

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

`PartyViewSet` (`AuditedCreateDestroyMixin`, `AuditedUpdateMixin`, `ZevScopedQuerySetMixin`,
`ModelViewSet`; `http_method_names` without `put`; `scope_parent_path = ("zev",)`, so a create
in a ZEV the caller does not manage → 400 on `zev`). Validation (`PartySerializer.validate`): a
person needs `last_name`, an organisation `organisation_name`; a PATCH cannot move the party to
another ZEV. A DELETE checks participations and roles (also ended ones) first. List queryset: `select_related("zev")`, `prefetch_related("participations",
"roles")`; `participations` sorted by `valid_from`; `roles` as on participants (today or later).

Serializer `PartySerializer`: `id`, `zev`, `kind`, `title`, `first_name`, `last_name`,
`organisation_name`, `name_addition`, `email`, `phone`, `address_line1`, `address_line2`,
`postal_code`, `city`, `notes`, `display_name` (ro), `participations` (ro), `roles` (ro),
`created_at` (ro), `updated_at` (ro). Audit: `party.create` / `party.update` (field diff) /
`party.delete`, category `governance`, target `zev.Party`, display name as target.

### 5.3 Party roles (`/api/v1/zev/party-roles/`, new; `ZevPartyRoleViewSet`)

| Method | Path | Behaviour |
|---|---|---|
| GET | `/zev/party-roles/?zev_id=&include_ended=` | Active and future roles; `include_ended=true` adds history |
| POST | `/zev/party-roles/` | `{zev, party, role, valid_from, valid_to?}` → `assign_role` (201); conflicts → 400 with the service message |
| POST | `/zev/party-roles/{id}/end/` | `{last_day}` → `end_role` (200, or 204 when the row was deleted) |

`ZevPartyRoleViewSet` is a `ReadOnlyModelViewSet` (no PATCH/PUT/DELETE: 405) with `create`
and the `end` action. `create` validates `ZevPartyRoleAssignSerializer` (`zev`, `party` of that
ZEV, `role`, `valid_from`, optional `valid_to`), runs `assert_within_scope`, then `assign_role`;
a service `ValidationError` becomes a 400 with its `message_dict` (e.g. `{"valid_from": ["A later
holder exists; end it first."]}`). `end` validates `ZevPartyRoleEndSerializer` (`last_day`),
refuses a disabled ZEV for non-admins, and returns the ended row or 204 when `end_role` deleted
it. The list filter applies to `list` only. Serializer `ZevPartyRoleSerializer`: `id`, `zev`, `party`,
`party_display_name`, `role`, `valid_from`, `valid_to`, `created_at`, `updated_at`, all
read-only. Both viewsets: `zev_lookup = "zev"`, no participant path; a participant-only account
gets 403. `BaseZevScopedPermission._get_zev` resolves `Party` and `ZevPartyRole` through `.zev`.

No PATCH/DELETE: history is changed by assigning or ending. Audit events (§10):
`party.create`, `party.update`, `party.delete`, `party_role.assign`, `party_role.end`, scoped to
the ZEV.

### 5.4 ZEVs

`ZevSerializer` drops `owner` (and its `validate_owner` / default-to-caller `create`). It
gains read-only `issuer` (`{party, display_name}` of today's issuer or `null`) for the
switcher and the ZEV list, read from the `issuer_roles` prefetch that `ZevViewSet.get_queryset`
adds (one query for the list). Self-setup grants the caller a manager role explicitly (§6);
`ZevViewSet.create` (admin) grants nobody. The admin "change owner" (`PATCH zev.owner`) is gone.

### 5.5 Access through the issuer and representative roles (ADR 0028 decision 8)

**Rule.** An account manages a ZEV on a day when a party it belongs to holds a role in
`MANAGING_ROLES = (issuer, representative)` there on that day. A party's accounts
(`zev.access.party_accounts(party)`): `party.user`, then the users of its participations (latest
`valid_from` first), without duplicates. The `landowner` role and plain contacts give nothing.
Access is derived from the role rows, never stored as `ZevAccessGrant`s.

**`zev/access.py`.**

| Function | Behaviour |
|---|---|
| `role_holdings(user, day=None)` | The account's managing role rows active on `day` (party via `Party.user` or `participations__user`), distinct |
| `_grant_sets(user)` | Managed and viewable ZEV ids from grants, each joined with the ZEV ids of `role_holdings` (memoised; one grant query + one role query per request) |
| `holds_managing_role_ever(user)` | Any managing role row, at any time — `services.has_its_own_login` counts it, so a non-admin cannot rewrite the login of an issuer's participant row |
| `party_accounts(party)` | As above |
| `role_managers(zev, day=None)` | `[(account, role_row)]` managing `zev` through a role on `day` |
| `has_manager(zev, *, exclude_grant=None, day=None)` | An active manager grant (other than `exclude_grant`) or any `role_managers` |
| `is_last_manager(grant)` | A manager grant whose ZEV has no other manager — grant or role (`has_manager(..., exclude_grant=grant)`) |
| `keeping_a_manager(*zevs)` | Context manager: runs the change in a transaction; any of `zevs` that had a manager and has none afterwards rolls it back and raises `NoManagerLeft` |
| `role_holdings_by_account(day=None)` | `{account_id: [role rows]}` for the admin accounts list, in a fixed number of queries |
| `build_memberships(grants, participants, *, roles=())` | Each entry gains `roles` (managing role names held today); a role sets `access` to `manager` |

`bump_generation` is also connected to `Party` and `ZevPartyRole` saves and deletes, so the memo
never answers from a stale role or account link.

**Guards.** `NO_MANAGER_LEFT = "This would leave the ZEV without a manager. Give someone
manager access first."` lives in `zev/access.py` (re-exported by `zev/parties.py`).

- `assign_role` and `end_role` of a managing role (`zev/parties.py`) check `has_manager` before
  and after the change, inside its transaction: a ZEV that had a manager and would have none
  today → `ValidationError({"party": [NO_MANAGER_LEFT]})`; the API (`create`, `end`) returns it
  as a 400. `end_role` is atomic.
- The changes that take a role manager's account away run inside `keeping_a_manager`:
  - `POST /zev/participants/{id}/unlink-account/` → 400 `{"detail": NO_MANAGER_LEFT}`, the link
    stays;
  - `DELETE /zev/participants/{id}/` (`ParticipantViewSet.destroy`) → 400 `{"detail":
    NO_MANAGER_LEFT}`, the row stays;
  - `DELETE /auth/users/{id}/` over every ZEV the account manages (`managed_zev_ids`): its manager
    grants cascade and its `Party.user` is cleared → 403 `NO_MANAGER_LEFT` with a `user.delete`
    audit event of status `denied`. This also covers an account that is a ZEV's only *grant*
    manager.
- `Party.user` is not writable through the API (only an invitation sets it), so deleting the
  account is the only way it is cleared.

**API.**

- `PartySerializer` gains read-only `accounts: [{id, email, full_name, is_active}]` (from the
  `select_related("user")` / prefetched `participations__user`).
- Role audit events (`party_role.assign` / `.end`) carry `metadata.manager_accounts`: the logins
  the role makes managers (empty for a landowner).
- Zugang `GET /zev/zevs/{id}/access/` appends, after the grants, one read-only entry per
  `role_managers(zev)`: `{id: "role-<role id>-<user id>", zev, role: "manager", valid_from,
  valid_to, is_active, granted_by: null, created_at, user, source: "role", party_role: {role,
  party, party_display_name}}`; grant entries carry `source: "grant"`. PATCH/DELETE address grant
  ids only.
- Zugang `POST` takes `email` **or** `party` (`{"email": ["Give either an email address or a
  party."]}` otherwise). For a party of the ZEV (else 400 on `party`): its first account gets the
  grant; without one, its `email` is used like an address (an existing account with that email,
  else an invitation); a party without either → 400 `{"party": ["This party has no email address
  to send an invitation to. Add one first."]}`. A party without an account is linked to the
  account the grant went to (`Party.user`). Errors about the account (an admin, already has
  access) are keyed by the field used. The audit event's metadata names the `party`.
- `/auth/me` and the admin accounts list: memberships carry `roles`; the accounts list chip
  (`AccountMemberships`) appends each role's label (`pages.accounts.membership.issuer` /
  `.representative`), e.g. "Verwaltung · Rechnungssteller".

**Frontend.**

- Types: `ZevAccessGrant.source`, `.party_role`; `ZevAccessGrantInput` with optional `email` /
  `party`; `Membership.roles`; `Party.accounts`.
- Zugang (`ZevAccessSection`): "Give access to" a party (default; picker of the ZEV's parties
  with their login, "invite <email>" or "no email address" — the last disabled) or an email
  address. Role entries show an "As <role>" badge and "Through the role of <party>; changes with
  the role above", without actions (on the login's grant row when it has one, §8.3). The end date uses `CivilDateInput` (`minDate` today).
- Roles card: assigning the issuer or representative opens a `ConfirmDialog` naming the logins
  that get manager access (`grantsAccess`) or saying nobody does (`noLogin`); contacts show
  their login. Issuer, representative and contacts hints say what the role or contact means for
  access.

## 6. Creation flows

| Flow | Creates |
|---|---|
| Wizard `create_zev_with_owner_setup` | Account (`role=user`, temporary password), ZEV, a **person party** from the owner data, the owner **participant** of that party (`valid_from = start_date`), **issuer + landowner** roles from `start_date`, the metering points and their assignments. The account manages through the issuer role and gets **no grant** — except a ZEV starting later, where `grant_manager_until_role` gives it a manager grant from today to `start_date − 1` |
| Self-setup `create_zev_for_existing_owner` | ZEV, the caller's party and participant, issuer + landowner; access through the issuer role, a bridging grant only for a later start (as the wizard) |
| Admin `ZevViewSet.create` | The ZEV only (admins need no grant); parties, roles and access are added afterwards in ZEV settings |
| Transfer import | Parties from the archive (§9; roles from format 5, a follow-up PR); a manager grant for the importing account (`grant_manager`) |
| `seed_demo` | Finds its demo ZEVs through the demo owner's manager grant or issuer role (`_owned_zevs`) |

## 7. Documents and templates

### 7.1 Issuer by document

| Document | Issuer | Where |
|---|---|---|
| Invoice | `issuer_on(zev, invoice.period_end)` | `invoices/document_parties.build_issuer(zev, day)` — the copy (§3.1a of the invoice spec) |
| Contract | `issuer_on(zev, rendered_on)` | `invoices/contract_pdf.py` |
| Annual statement | `issuer_on(zev, date(year, 12, 31))` | `invoices/annual_statement.py` |
| Reports default participant (`views_reports.py` `FinancialSummaryView`) | the caller's own row, else the latest participation of the issuer on 31 Dec of the year | |

The issuer block is `document_parties.build_issuer(zev, day)`; contracts and statements get it
with `representative` (`build_representative`) and the `owner_participant` alias from
`issuer_context(zev, day)`. Without an issuer on that day: name = ZEV name, no address,
`from_participant: false` (the key keeps its name, since frozen copies carry it), as before
without an owner row. A statement for a year before the first issuer's `valid_from` (a year
before the ZEV started) therefore names the ZEV, where it used to name the owner.

### 7.2 Issuer copy schema change (PR 3)

`Invoice.issuer` and `Invoice.recipient` gain `party` (UUID string or `""`), `kind`,
`organisation_name` and `name_addition`, and take `name` / `name_lines` from the party's
`display_name` / `name_lines`. The issuer is the party of the owner account's participation
(`document_parties.issuer_party`) until PR 4 moves it to the dated role. Old copies stay valid
(missing keys read as empty). The QR bill's creditor and debtor names are the copy's
`name_lines` joined on one line, cut at 70 characters (`pdf._qr_name`). In the invoice
template context, `participant.display_name`, `.name_lines`, `.kind`,
`.organisation_name` and `.name_addition` come from the recipient copy.

The built-in invoice, contract and annual-statement templates print `name_addition` after
the issuer's and the participant's name. The conditional is inline, so a party without one
renders byte-identical HTML and no contract version is minted by the template change.

### 7.3 Template variables

| Variable | Meaning |
|---|---|
| `issuer.name`, `.name_lines`, `.kind`, `.organisation_name`, `.name_addition`, `.address_line1`, `.address_line2`, `.postal_code`, `.city`, `.email`, `.phone`, `.iban`, `.bank_name`, `.vat_number` | Issuer (invoice: from the copy; contract/statement: live on the document's date) |
| `representative.*` | Same name/contact/address keys for the representative on the document's date, or `None` |
| `participant.display_name`, `.name_lines`, `.organisation_name`, `.name_addition`, `.kind` | Recipient |
| `owner_participant.*` | Deprecated alias of `issuer` (`full_name` → `issuer.name`) |
| `zev.owner.get_full_name`, `zev.owner.email` | Deprecated alias → `issuer.name`, `issuer.email`; `zev.owner.username` → `""` (from PR 5: `document_parties.OwnerAlias`, set as `owner` on the `zev` `FrozenView` in the invoice context and in `issuer_context` for contracts and statements) |

`field_catalog_data.py` lists the new groups (`issuer`, `representative`; name, name addition,
organisation name, address, phone, email, and for the issuer IBAN, bank name and VAT number) in
all three catalogues and drops `ownerParticipant`; the deprecated aliases keep rendering. In PR 4
the contract catalogue kept a `zevOwner` group for the built-in contract template's
no-issuer branch; PR 5 prints `issuer.name` / `issuer.email` there (the ZEV name without an
issuer) and drops the group and its keys. New i18n keys `admin.fields.issuer`, `representative`, `zevOwner`, `partyName`,
`organisationName`, `bankName`; `ownerParticipant` is removed. The built-in
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
`fetchPartyRoles(zevId, { includeEnded })`, `assignPartyRole`, `endPartyRole` (resolves `null`
on 204); query keys `zev.parties(zevId)`, `zev.partyRoles(zevId, includeEnded)`. Types as
shipped: `PartyRoleName`, `PartyRoleWindow` (`{id, role, valid_from, valid_to}` on parties and
participants), `Party`, `PartyInput` (its editable fields), `ZevPartyRole` (with
`party_display_name`); `ParticipantInput` gains optional `party`, `kind`,
`organisation_name`, `name_addition`, and its name and email fields become optional.

### 8.3 ZEV settings → People & access (`features/zev/ZevPeopleSection.tsx`)

Tab `people` after General (`ZevSettingsTab = 'general' | 'people' | 'billing' | 'documents' |
'audit' | 'export'`); `/zev-settings/parties` and `/zev-settings/access` redirect to it
(`MERGED_INTO_PEOPLE` in `ZevSettingsTabRoute`, `<Navigate replace>`). The save bar treats it
like Audit and Export (`OUTSIDE_THE_FORM`). `ZevPeopleSection` renders `ZevPartiesSection`: two cards, **Roles** and **Other people**,
with access shown and changed **on each person's row** — there is no separate access list.

- Access per row: `AccessControls` (`features/zev/PartyAccess.tsx`) gets the access list rows
  (`fetchZevAccess`, `queryKeys.zev.access(zevId, false)`) of the row's logins
  (`Party.accounts`) and shows: a role-derived entry → "Manages in OpenZEV" + login; a grant →
  "Manage" / "Read only" (+ "Invitation pending", "until …") with Make manager/viewer (viewer
  through `ConfirmDialog`), Resend invitation, Remove access (`ConfirmDialog`); no access →
  "No access to OpenZEV" with a Manage / Read only select and "Give access" (a login exists) or
  "Invite" (only an email) → `createZevAccess({party, role})`; neither login nor email → "No
  login and no email address". The issuer and representative holder rows pass `managingRole`:
  without a login they say an invited login will manage and offer "Invite" (as manager).
  Mutations, toasts and confirmations live in `useAccessActions(zevId)`, shared by all rows.
- Rows: the current issuer and representative holders, every listed landowner, and in
  **Other people** the contacts (parties without participations), the parties with access not
  shown elsewhere (e.g. a participant given read-only access, with a "Participant" badge) and
  bare logins with access that belong to no party ("Login only").
- **Other people** header: "Add contact" and "Give access" (`GiveAccessForm`: email — the
  default — or a party of the ZEV, role, optional end date with `CivilDateInput`).
- A contact can be deleted only without roles and without access. Ended grants are not listed
  (the audit log keeps them).

Sections of the roles card and the contacts in Other people:

- **Issuer** and **Representative**: today's holder with "since", the history behind "Show
  history", and "Change from…" (party picker + date) for managers.
- **Landowners**: list with "since/until"; add (party picker + date), end (date).
- **Other parties**: non-participant parties (contact cards); add / edit (person or
  organisation form) / delete (only unused).

Party picker: every party of the ZEV by `display_name`, with "New contact…" opening the party
form; the created contact is selected in the picker. Viewers see everything read-only. Follows
`2026-04-frontend-management-page-design.md` (action hierarchy, responsive layout).

As shipped: one query of all roles (`include_ended=true`) and one of the parties; each block
derives today's holder, upcoming rows ("From" badge) and the history client-side
(`todayBusinessIso`). Issuer and representative (`SingleHolderRole`): "Set" when nobody holds
the role, else "Change from…", opening an inline `AssignForm` (picker + date, default today)
with a hint that the previous holder ends the day before; no issuer → `warning-banner`.
Landowners (for a ZEV and a vZEV alike; the hint says a community spanning several plots has several, and #761 phase 3 links each landowner to its plot or building): current and future rows; "End" opens an inline last-day form (default today);
"Add landowner" the same `AssignForm`. Other contacts: parties without participations, with
their role badges; edit in `PartyFormModal` (`features/zev/PartyFormModal.tsx`: kind,
organisation name, title, first/last name — "contact" labels for an organisation —, name
addition, email, phone, address, notes); delete (with `ConfirmDialog`) only while it holds no
role. Every change invalidates parties, roles, access, the ZEV list (issuer) and participants.
Styles `.zev-parties-*` in `index.css` (`.zev-parties-block-first` drops the divider of the
contacts card's first block), reusing the `.zev-access-*` rows.

### 8.4 Participants

- Participant form: kind switch (person / organisation), organisation name, name addition (with
  a hint), "contact" labels for first/last name of an organisation; a person needs first and
  last name, an organisation its name (`participantFormSchema`). On create, "Same person or
  organisation as" (the ZEV's parties, `fetchParties`) picks a party: the party fields are
  hidden behind a note naming it and the payload carries only `party` plus the participation
  fields (`mapParticipantFormValuesToInput`). On edit a note says the name and address are the
  party's. `formatParticipantName` uses the organisation name for an organisation.
- Cards show `display_name`, the name addition, and role badges (Issuer, Representative,
  Landowner) replacing the "Owner" badge (which compared `zev.owner` with `participant.user`).

### 8.5 Owner reads replaced

`ZevListPage` (owner column and "change owner" dialog → `Issuer` column showing
`issuer.display_name` or "–", dialog, its mutation and the users/participants queries
removed), `Layout` switcher subtitle (`issuer.display_name`, else the account's relation; the
admin users query is gone), `zevForm.ts` (`owner` dropped; `ZevFormField = keyof ZevInput`),
`types/api.ts` (`Zev.owner` → `Zev.issuer`, `ZevInput.owner` and the `owner_not_found` restore
conflict removed). The participants page shows the party's roles held today as badges
(`pages.participants.roles.{issuer,representative,landowner}`) instead of the "Owner" badge,
sorts the issuer first, and drops the "Owners" summary count; the unlink and delete actions no
longer hide for the owner's row. The wizard keeps its "responsible person" form (it creates the
issuer). Removed keys: `pages.zevs.ownerModal.*`, `setOwner`, `messages.assignFailed`,
`validation.selectNewOwner`, `pages.participants.owner`, `summary.owners`,
`admin.fields.zevOwner*`, `restore…owner_not_found`; `pages.zevs.col.owner` → `col.issuer`.

### 8.6 i18n

Keys in all four locales under `pages.zevSettings.tabs.parties`, `pages.zevSettings.parties.*`,
`pages.participants.kind.*`, `pages.participants.organisationName`,
`pages.participants.nameAddition`, `pages.participants.sameParty*`, `parties.roles.*`,
`admin.fields.issuer*` / `representative*` (field catalogue).

## 9. Transfer archive and backups

- PR 3 keeps format version 4: `PARTICIPANT_FIELDS` gains the optional `kind`,
  `organisation_name` and `name_addition`, the importer builds one party per participant
  from the flat fields (`Party.full_clean()` first), and an older archive imports every
  participant as a person.
- Archive **format version 5** (PR 5b): the `participants` section gains two files,
  `parties.json` (`PARTY_FIELDS` + archive `id`, every party of the ZEV) and `party_roles.json`
  (`party_id`, `role`, `valid_from`, `valid_to`), written and imported before the participants;
  `PARTICIPANT_FIELDS` loses the moved fields and each participant gains `party_id`. They are
  files of the participants section rather than sections of their own, because a participant
  cannot travel without its party (SPEC-2026-08-zev-transfer-archive §6).
- Importing v1–4: one party per participant from its fields (`kind=person`), no roles (the
  archive never named the owner).
- `backups/registry.py`: `zev.Party` (PR 3, written before `zev.Participant`) and
  `zev.ZevPartyRole` (PR 4) in the per-ZEV section;
  `restore_zev.py` drops the owner fallback of the account transform, the `owner_ref` fact and
  the `owner_not_found` conflict, and `ensure_a_manager` after a recreation (PR 5): a recreated
  community has no managers until an admin grants access.

## 10. Observability and audit

Audit events with `action_category=governance`, `target_type` `zev.Party` /
`zev.ZevPartyRole`, metadata `{role, valid_from, valid_to, party}` for roles. Party edits
through the participant endpoints keep the existing participant audit events.

## 11. Delivery

| PR | Content |
|---|---|
| 1 | Invoice issuer/recipient copy — shipped (#875) |
| 2 | This spec + ADR 0028 |
| 3 | `Party`, `Participant.party`, facade, migrations `zev.0032_party` / `0033_participant_parties_data` / `0034_participant_party_required` (one party per participant), ORM lookups, `kind` / `organisation_name` / `name_addition` / `display_name` in API, copy, QR and built-in templates — no other behaviour change |
| 4 | `ZevPartyRole`, `zev/parties.py`, data migration (issuer + landowner from the owner's party; no role when the owner has no participation), issuer by date in copy / contract / statement / reports, wizard and self-setup set the roles, template variables and catalogue, read-only party and role endpoints, `ParticipantSerializer.roles`, `zev.ZevPartyRole` in backups |
| 5 | Drop `Zev.owner` (`zev.0037`): creation flows with explicit grants, `ZevSerializer.issuer`, admin owner dialog removed, `zev.owner.*` template alias, backups, frontend owner reads replaced, role badges on participants |
| 5b | Transfer archive format 5 (`parties.json`, `party_roles.json` in the participants section) |
| 6 | Party and role write endpoints, Parties tab, participant form and badges, user guide |
| 7 | The issuer and representative manage the ZEV (§5.5): `Party.user`, derived access, guards, Zugang by party, role entries in Zugang, confirmation in the Parties tab (ADR 0028 decision 8) |
| 8 | One People & access tab: access shown and changed on each person's row (issuer/representative "manages", others manager/read-only), Other people with contacts and remaining logins; old tab URLs redirect |

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A document's text changes after the migration | High | Golden comparison of rendered invoice, contract and statement HTML before/after on the dev data in PRs 3–5 |
| A query by participant name misses the move to `party__` | Medium | Columns are removed, so any leftover lookup fails loudly in tests |
| The facade hides an N+1 on `party` | Medium | `select_related("party")` on list querysets; query-count tests stay pinned |
| Two participations sharing a party surprise an editor | Low | The form says the name and address are shared; "same person" is an explicit choice |
| An old archive imports without an issuer | Low | Documents fall back to the ZEV name; the Parties tab shows "No issuer" as needing attention |

## 13. Test plan

- **PR 3** `zev/test_parties.py` (16, shipped): `PartyTests` (4: validation by kind, names
  and name lines, the 70-character QR name, sorting organisations among people),
  `ParticipantFacadeTests` (7: creating makes the party, edits write through incl.
  `update_fields`, two participations share edits, refresh drops staged values, another ZEV's
  party refused, an organisation participant's recipient copy, the QR debtor name with the
  second line), `ParticipantApiTests` (4: organisation participant, names required by kind, a
  second participation of the same party, another ZEV's party refused), `PartyMigrationTests`
  (1: forward copies every field into a party, backward restores them). The rest of the suite
  moved its name lookups to `party__…`; `zev/test_onboarding.py`'s upgrade test now writes its
  rows with the historical models. Golden check on the dev data: 21 invoices, 9 contracts and
  18 annual statements render byte-identical HTML before and after.
- **PR 4** `zev/test_party_roles.py` (22, shipped): `AssignRoleTests` (7: a new issuer ends
  the previous one the day before, a holder replaced on its first day is removed, a later
  holder must be ended first, landowners many but once per party, another ZEV's party refused,
  ending before the start removes the role, the database allows one open issuer and an ordered
  window), `IssuerLookupTests` (3: the owner fallback without issuer rows, no fallback once a ZEV
  has issuer rows, self-setup makes the owner issuer and landowner and `ensure_initial_roles`
  is idempotent), `DocumentIssuerByDateTests` (5: invoice by `period_end`, an approved invoice
  keeps its issuer after a change, contract by its date plus the `owner_participant` alias,
  statement by 31 Dec, representative on the contract date), `PartyRoleApiTests` (6: a viewer
  lists parties with participations and roles, roles current vs. `include_ended`, read-only
  405, a participant gets 403, a participant row lists its party's roles, another ZEV's party
  404), `PartyRoleMigrationTests` (1: issuer and landowner from the first dated document, none
  without an owner participation, reverse removes them). `test_allocation_query_counts`
  budget 17 → 18 (the owner fallback on a ZEV without roles). Golden check on the dev data:
  21 invoices, 2 issued and 9 current contracts and 15 of 18 annual statements render
  byte-identical HTML; the 3 others are 2025 statements of a ZEV that started in April 2026
  (§7.1).
- **PR 5** (shipped): `zev/test_without_owner.py` (5: a ZEV shows its issuer and no owner, an
  admin-created ZEV gives nobody access, self-setup makes the caller manager and issuer,
  `zev.owner.*` in a custom template resolves to the issuer, the migration reverses with the
  current manager as owner); `zev/test_access.py` `CreatorGrantTests` replaces the owner
  invariant tests (`grant_manager` promotes a viewer, is idempotent) and `GrantMigrationTests`
  uses historical models; backups: a recreated community needs no former manager and starts
  without managers; the suite creates ZEVs with `testing.helpers.create_managed_zev(owner=…)`
  / `ZevFactory(owner=…)` (ZEV + manager grant) and reads `zev_manager(zev)` where it read
  `zev.owner`; tests that relied on the owner fallback give the owner's participation the
  issuer role. Backend 3820 passed. Golden check on the dev data: 21 invoices, 2 issued
  contracts and 18 annual statements byte-identical; 3 current contracts of a ZEV without an
  issuer now name the ZEV where they named the owner account.
- **PR 5b** (shipped): `zev/test_transfer.py` `PartyTransferTests` (4: parties and roles round
  trip, a format-4 archive gives each participant a party and no roles, an unknown `party_id`
  and overlapping issuers are rejected); `SchemaParityTests` covers `PARTY_FIELDS` and
  `PARTY_ROLE_FIELDS`; the legacy-format tests rewrite exports with `as_format_version`.
  Backend 3824 passed.
- **PR 6** (shipped): `zev/test_party_roles.py` `PartyWriteApiTests` (10: a manager adds,
  edits and deletes a contact with audit events; names required by kind; a party in use cannot be
  deleted; edits show on every participation; a manager of another ZEV cannot add a party here;
  a viewer reads but cannot write; a new issuer ends the previous one, with the audit event; a
  later holder is refused with the reason; ending a role, and ending one before it started
  deletes it); `PartyRoleApiTests` now checks roles only change by assigning and ending (405 on
  PATCH/DELETE). Frontend `tests/zev-parties-section.test.ts` (4: today's issuer, no
  representative, landowners and contacts; viewer without actions; set a representative from a
  date; end a landowner), `tests/participant-form-mapping.test.ts` (+2: organisation payload and
  validation, a second participation sends only the participation). User guide: ZEV setup →
  Parties tab, participant management (type, second name line, same party).
- **PR 7** (shipped): `zev/test_role_access.py` (15): `RoleAccessTests` (the issuer's
  participant account manages exactly while the role lasts; a representative with its own
  account manages, a landowner neither manages nor views; memberships name the role; holding the
  role protects the login), `LastManagerTests` (ending the only managing role or handing it to a
  party without a login is refused; with a manager grant the role can go; a manager grant can go
  while the issuer manages; the API reports the reason), `ZugangTests` (the list shows role
  managers; access for a party with a login goes to that login; a party without one is invited
  and linked; no email → 400; email or party, not both; a role assignment's audit names the
  logins and the party lists its accounts). `PartyRoleApiTests`: a former issuer's participant
  gets no parties, today's issuer's does. Query budgets: `/auth/me` 3 → 4, the access memo 1 → 2
  queries. Frontend: `zev-access-section.test.ts` +2 (access to a party; role entries without
  actions), `zev-parties-section.test.ts` (setting a representative confirms the login first).
- **PR 8** (shipped): frontend `tests/zev-people-section.test.ts` (5: two cards and the issuer
  row says it manages; a landowner gets read-only access from its row; a contact is invited as
  manager; a login given access by email is listed with its actions; a viewer gets no access
  controls). `ZevAccessSection` and its test are removed. `zev-parties-section.test.ts` mocks the
  access list and auth. No backend change.
- **Review follow-up** (QR readiness and last-manager guards): `zev/test_role_access.py`
  `LastManagerOutsideRolesTests` (5: unlinking the issuer's account and deleting its participant
  are refused; with a manager grant both go through; deleting the account behind the issuer
  party is refused with a denied audit event; deleting a ZEV's only grant manager is refused);
  `invoices/test_readiness.py` `IssuerSetupTests` (2: no issuer; an issuer without and then with
  an address). Frontend `tests/readiness-cockpit.test.ts` +1 (the issuer-address warning links to
  People & access).
- **Creator by role** (`zev/test_without_owner.py`): self-setup makes the caller issuer without
  a grant; a ZEV starting later gets a bridging grant to the day before the start;
  `EndCoveredGrantsMigrationTests` (0039 ends the issuer's grant, another manager's stays).
  `testing.helpers.zev_manager` falls back to the first role manager.
- **Wording and roles in the accounts list**: frontend `tests/account-memberships.test.ts` (1: a
  manager through a role names it, a grant or a viewer names none). The unused
  `pages.accounts.membership.owner` label is removed.

## 14. Acceptance criteria

- [x] A ZEV records several landowners, an issuer without a login and an outside representative.
- [x] Changing the issuer from a date makes invoices for periods before that date name the old
      issuer and later ones the new issuer; issued invoices never change.
- [x] An organisation participant appears with its name on invoices, QR bill and contracts; a
      household shows its second name line.
- [x] `Zev.owner` no longer exists; creating a ZEV makes its creator the issuer and landowner in
      one step, and the issuer role is their manager access (no grant on top of it).
- [x] Custom templates using `owner_participant.*` / `zev.owner.*` keep rendering.
