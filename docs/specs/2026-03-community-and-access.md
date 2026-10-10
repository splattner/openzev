# Feature Spec: Community and access management

- Spec ID: SPEC-2026-community-access
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-03-24
- Target Release: Ongoing baseline
- Related Issues: n/a (baseline)
- Related ADRs: 0001, 0003, 0008
- Impacted Areas: backend, frontend, docs

---

## 1. Problem and outcome

ZEV operators, administrators, and energy consumers need a safe, multi-tenant
system for managing communities (ZEVs), users, participants, and metering
points while enforcing strict role boundaries. Access must be scoped per ZEV
ownership so that no user can see or modify data outside their tenant.

**Outcome:** consistent role-aware behaviour in every UI page and API endpoint,
with backend-enforced ZEV scoping and frontend UX guardrails.

---

## 2. Scope

### In scope

- User model with a platform role (`admin` or `user`) plus per-ZEV access
  from grants and participant links (#761, SPEC-2026-10-zev-access-grants)
- Authentication (JWT via SimpleJWT), self-registration, email verification,
  password management, impersonation
- ZEV CRUD and owner lifecycle (creation wizard, self-setup, owner transfer)
- Participant master data CRUD and account lifecycle (auto-creation, invitation,
  link/unlink)
- Metering point and assignment CRUD (covered in depth in
  `2026-03-metering-point-management.md`)
- Frontend route protection and navigation visibility
- Community switcher and per-community shell (ManagedZevProvider)

### Out of scope

- External IAM / SSO providers
- Multi-tenant billing across unrelated organisations
- Metering data import, tariffs, invoicing (separate specs)

---

## 3. Data model

### 3.1 User

Extends `AbstractUser` (Django `accounts.models`).

| Field | Type | Description |
|---|---|---|
| `id` | `IntegerField` (PK, auto) | Django default PK |
| `username` | `CharField(150)` | Unique login name |
| `email` | `EmailField` | |
| `first_name` | `CharField(150)` | |
| `last_name` | `CharField(150)` | |
| `role` | `CharField(20)` choices `UserRole` | `admin` or `user` (default `user`); migration `accounts.0021` mapped the old `zev_owner` / `participant` / `guest` to `user` |
| `may_create_zev` | `BooleanField` (default `False`) | May set up a ZEV of its own through self-setup (§7.3); set by self-registration |
| `must_change_password` | `BooleanField` (default `False`) | Set `True` on admin-created or invitation-created accounts |
| `is_active` | `BooleanField` | `False` until email verification for self-registered users |
| `preferred_zev` | `ForeignKey('zev.Zev')`, null, `SET_NULL` | Account-level default community: an account with several communities lands here on login. `None` = first managed by name. Set by the frontend via `/auth/me/` |

**Computed properties:**

| Property | Logic |
|---|---|
| `is_admin` | `role == 'admin'` OR `is_superuser` |

`is_zev_owner` was removed with #761: whether an account may manage a ZEV is
`zev.access.can_manage(user, zev)` (§4).

### 3.2 UserRole enum

| Value | Label |
|---|---|
| `admin` | Admin |
| `user` | User |

What a `user` account may do in a ZEV comes from its grants and participant
links there (§4.1), never from the role.

### 3.3 EmailVerificationToken

| Field | Type | Description |
|---|---|---|
| `id` | `IntegerField` (PK, auto) | |
| `user` | FK → `User` (`CASCADE`) | |
| `token` | `CharField(64)`, unique, indexed | `secrets.token_urlsafe(48)` |
| `created_at` | `DateTimeField` (auto) | |
| `consumed_at` | `DateTimeField` (nullable) | Set when consumed |

**Validity rule:** `consumed_at IS NULL AND now < created_at + 24h`.

### 3.4 Zev

(Full field list in `2026-03-admin-governance-and-settings.md`; key access-relevant fields here.)

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `name` | `CharField(200)` | Community display name |
| `start_date` | `DateField` | Community start date |
| `zev_type` | `CharField(10)` | `zev` or `vzev` |
| `grid_operator` | `CharField(200)`, blank | Name of the VNB — free text (see §3.4a) |
| `grid_operator_elcom_id` | `PositiveIntegerField`, null | ElCom operator id when the name was picked from the official list; null when typed |
| `tariff_source_url` | `URLField(500)`, blank | Where this operator publishes its machine-readable tariffs (Art. 7b StromVV); used by the tariff import — see `2026-09-vse-tariff-import.md` |
| `billing_interval` | `CharField(20)` | `monthly`, `quarterly`, `semi_annual`, `annual` |
| `disabled_at` | `DateTimeField`, null, indexed | Set when the ZEV is disabled (retired, not deleted); `null` = active. Read-only on `ZevSerializer` — only `disable`/`enable` may change it (§7.1a) |
| `disabled_by` | FK → `User` (`SET_NULL`), null | Who disabled it (owner or admin); `related_name="+"` |
| `disabled_reason` | `CharField(500)`, blank | Free-text reason passed to `disable` |
| `created_at` | `DateTimeField` (auto) | |
| `updated_at` | `DateTimeField` (auto) | |

**Ordering:** `["name", "id"]` — the trailing `id` keeps paginated walks
stable (§3.7).

### 3.4a Grid operator picker

`grid_operator` stays free text; `grid_operator_elcom_id` records *which*
official operator it is when the user picked one. The pair exists because the
same utility was reaching the database as "EKZ", "Elektrizitätswerke des
Kantons Zürich", or a typo — and the value is printed on contracts and
invoices via `{{ zev.grid_operator }}`.

**Source.** ElCom publishes its electricity-tariff data as Linked Data on the
federal LINDAS platform under `TermsOfUse/Open-Use`. `manage.py
fetch_grid_operators` queries the SPARQL endpoint and writes
`backend/zev/data/grid_operators.json` (553 operators for 2026, ~82 KB): id,
name, UID, website, plus the source, cube, licence, period and fetch date.

**Shipped as a fixture, not queried live.** The list changes on a tariff-year
cadence, and the self-setup wizard is the first form a new owner sees — it
must not fail because an external SPARQL endpoint is unreachable. Run the
command once per tariff year and commit the result. It refuses to write when
fewer than `--min-operators` (default 400) come back, so a changed query or
cube cannot silently truncate a good fixture.

**A suggestion source, not a constraint.** Deliberately not a foreign key: an
operator missing from ElCom's tariff cube — a recent merger, a small municipal
works — must still be enterable. The frontend uses an `Autocomplete`, and
`grid_operator_elcom_id` is derived from the typed name on every change, so
editing a picked name by one character drops the id rather than leaving it
pointing at a different utility. `ZevSerializer.validate_grid_operator_elcom_id`
rejects ids that are not in the shipped list; `None` is always valid.

Existing ZEVs needed no backfill — the field is simply null for them.

`tariff_source_url` sits beside these two for the same reason they do: it
belongs to the operator relationship, not to billing configuration. It is
per ZEV rather than in `AppSettings` because there is no central registry —
each operator hosts its own address — and one deployment serves ZEVs on
different operators.

### 3.5 Participant and Party

Since #761 phase 2 (ADR 0028, SPEC-2026-10-zev-parties) a participant is a
**party's** billing relationship with the ZEV. Names, contact data and the
address are the party's.

**`zev.Party`**

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `zev` | FK → `Zev` (`CASCADE`, `related_name="parties"`) | A party belongs to one ZEV |
| `kind` | `CharField(20)` choices `PartyKind` | `person` (default) or `organisation` |
| `title` | `CharField(10)` choices `PartyTitle` | `mr`, `mrs`, `ms`, `dr`, `prof`, or blank |
| `first_name`, `last_name` | `CharField(100)`, blank OK | For an organisation: its contact person |
| `organisation_name` | `CharField(200)`, blank OK | |
| `name_addition` | `CharField(200)`, blank OK | Second name line (another household member, "c/o …") |
| `email` | `EmailField`, blank OK | Required at participant API validation level |
| `phone` | `CharField(30)` | |
| `address_line1`, `address_line2` | `CharField(200)` | |
| `postal_code` | `CharField(10)` | |
| `city` | `CharField(100)` | |
| `notes` | `TextField` | |
| `sort_name` | `CharField(200)`, indexed, not editable | `organisation_name` or `last_name`, set on save |
| `created_at`, `updated_at` | `DateTimeField` (auto) | |

`clean()`: a person needs `last_name`, an organisation `organisation_name`.
Properties: `person_name` (`"{title_display} {first_name} {last_name}"`),
`display_name` (organisation name or person name), `name_lines`
(`display_name`, then `name_addition`), `qr_name` (name lines on one line, at
most 70 characters). Ordering `["sort_name", "first_name", "id"]`.

**`zev.Participant`**

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `zev` | FK → `Zev` (`CASCADE`) | Parent community |
| `party` | FK → `Party` (`RESTRICT`, `related_name="participations"`) | Same ZEV (`clean()`); several participations may share a party |
| `user` | FK → `User` (`SET_NULL`, nullable) | Linked user account (optional) |
| `valid_from` | `DateField` | Start of participation |
| `valid_to` | `DateField` (nullable) | End of participation (open = active) |
| `notes` | `TextField` | |
| `allocation_weight` | `DecimalField(12, 4)`, `MinValueValidator(0.0001)` | Default `1`. Unitless relative weight for splitting a `COMMUNITY`-mode metering point's costs and a `weight`-keyed `SHARED_*` tariff (`SPEC-2026-08-shared-metering-points`) — never a percentage, per-mille, or Wertquote |
| `created_at` | `DateTimeField` (auto) | |
| `updated_at` | `DateTimeField` (auto) | |

**Facade:** `kind`, `title`, `first_name`, `last_name`, `organisation_name`,
`name_addition`, `email`, `phone`, `address_line1`, `address_line2`,
`postal_code`, `city` (`PARTY_FACADE_FIELDS`) are properties that read the
party; setting one stages the value, and `save()` creates the party (none yet)
or writes the staged values to it, in one transaction. `save(update_fields=…)`
routes facade names to the party. `refresh_from_db()` drops staged values. ORM
lookups use `party__…`. The default manager (`ParticipantManager`, also the
base manager) always `select_related("party")`.

**Ordering:** `["party__sort_name", "party__first_name", "id"]`.

**Computed properties:** `full_name` / `display_name` → `party.display_name`;
`name_lines` → `party.name_lines`; `get_title_display()`.

**`zev.ZevPartyRole`** — a party's dated role in the ZEV (`issuer`,
`representative`, `landowner`; at most one issuer and one representative on
any day). The issuer and the representative make the party's accounts
managers of the ZEV while the role lasts (§4.1); a landowner gets nothing.
Model, constraints and the `zev/parties.py` service: SPEC-2026-10-zev-parties
§4.4–4.5, access §5.5.

### 3.6 MeteringPoint and MeteringPointAssignment

Covered in `2026-03-metering-point-management.md`. Relevant to access:
- MeteringPoint has FK → Zev (CASCADE).
- MeteringPointAssignment links a metering point to a participant with
  `valid_from`/`valid_to` range.
- Assignments are constrained within the participant's own validity window.
- Only one active assignment per metering point at a time.

### 3.7 List ordering must be a total order

Every DRF list endpoint is paginated by the project default
(`PageNumberPagination`, `PAGE_SIZE = 50`), which is `LIMIT`/`OFFSET`. Page 1
and page 2 are separate queries, and Postgres makes no promise about the
relative order of rows that tie on the `ORDER BY` key across separate queries.
A tie straddling a page boundary can therefore come back on *both* pages or on
*neither* — silently, with no error.

This was latent while clients only ever fetched page 1. Once the frontend
started walking the whole chain (`fetchAllPages`, #484), "the complete set"
could quietly be missing a row (#489).

**Rule:** every `Meta.ordering` must reach a unique column — in practice by
appending `"id"` unless a unique field is already in the list
(`MeteringPoint.meter_id`, `FeatureFlag.name`, `OAuthProvider.name`,
`User.username` are the exceptions that need nothing). The same applies to any
`.order_by()` in a view, which **replaces** `Meta.ordering` outright rather
than extending it, so a model-level tiebreaker does not reach it —
`VatRateListCreateView` and `AdminApiKeyListView` sort for themselves and
carry their own trailing `"id"`.

Changing `Meta.ordering` generates an `AlterModelOptions` migration, which is
metadata only and a no-op against the database.

Both halves are pinned by `backend/testing/test_pagination_ordering.py`: a
model-level check that walks every model in the project's own apps, and
per-view checks driven through a real request.

---

## 4. Roles and permission classes

Since #761 phase 1 (SPEC-2026-10-zev-access-grants, ADR 0027, which
supersedes ADR 0003) access is decided **per ZEV**, from what the account
holds there, and an account gets the union of everything it holds. Every
"may this account view/manage this ZEV" decision goes through
`backend/zev/access.py` (`can_manage`, `can_view`, `managed_zev_ids`,
`viewable_zev_ids`, `participant_zev_ids`, `live_participant_q`).

### 4.1 Relationships and the platform role

```
admin                 →  global access, all CRUD, configuration, impersonation (User.role)
manager grant         →  that ZEV: everything today's owner may do (ZevAccessGrant, role "manager")
viewer grant          →  that ZEV: read everything a manager reads, change nothing (role "viewer")
issuer/representative →  that ZEV as a manager, while a party the account belongs to (Party.user
                         or one of its participations) holds the role — derived, not a grant
participant link      →  own rows through Participant.user while the row is current
                         (valid_to null or ≥ today); sent invoices stay visible afterwards
no relationship       →  authenticated, no domain access
```

`User.role` is `admin` or `user` (#761 step 7); nothing but `is_admin` reads
it. An account without a grant passes no management gate (403), whatever it
did before. `ZevViewSet.self_setup` is gated by `User.may_create_zev`. In the
reports self-service rule (`invoices/views_reports.py _self_service`) an
account with no current participant row gets 404 when it has an ended one,
and is served as a manager (400 without ids) when it never took part.
`User.is_zev_owner` no longer exists.

A ZEV has no owner account (`Zev.owner` was removed in #761 phase 2,
migration `zev.0037_remove_zev_owner`, SPEC-2026-10-zev-parties §4.6). Whoever
creates a ZEV through the wizard or self-setup becomes its issuer and
landowner and manages it through that role, without a grant (a ZEV starting
later bridges the days before with `zev.access.grant_manager_until_role`); a
transfer import gives the importing account a manager grant from
`zev.access.grant_manager(zev, user)` (an existing open grant is promoted, an
active manager grant kept); a ZEV an admin creates through `POST /zevs/` gets
no grant. Whom its documents are from is the dated
issuer role (SPEC-2026-10-zev-parties §4.4), and the accounts of the issuer
and the representative manage the ZEV through that role
(`zev.access.role_holdings`, SPEC-2026-10-zev-parties §5.5): `managed_zev_ids`
and `viewable_zev_ids` include those ZEVs, memberships carry `roles`, and the
last-manager rule counts them.

### 4.2 Backend permission classes

Defined in `accounts/permissions.py` and `zev/permissions.py`.

| Class | Location | Logic |
|---|---|---|
| `IsAdmin` | `accounts` | `user.is_authenticated AND user.is_admin` |
| `HasZevAccess` | `accounts` | Coarse gate. Authenticated, and admin, or `may_hold_management_access(user)`, or (read → `viewable_zev_ids(user)` non-empty; write → `managed_zev_ids(user)` non-empty). A request is a read when its method is safe or its `view.action` is in the view's `viewer_allowed_actions`. Which ZEV is decided by the scoped queryset or an explicit `can_manage`/`can_view` in the view. Replaces `IsZevOwnerOrAdmin` |
| `HasZevReadAccess` | `accounts` | `HasZevAccess` that treats every request as a read — for the MCP endpoint, POST-only but read-only (ADR 0025), so a viewer may use it |
| `BaseZevScopedPermission` | `zev` | Base class for ZEV-tenant-aware permissions; `has_permission` (coarse gate) and `has_object_permission` (per-ZEV decision), §4.3 |
| `ZevManagementPermission` | `zev` | Extends `BaseZevScopedPermission`; POST restricted to admin only (DELETE is not a supported method on `ZevViewSet` at all); write methods on an already-disabled ZEV also require admin (`has_object_permission`) |
| `ZevDisablePermission` | `zev` | `admin` or `can_manage(user, zev)`, without the disabled-ZEV write block |
| `MeteringPointPermission` | `zev` | Extends `BaseZevScopedPermission`; `allow_participant_safe_methods = True` |
| `MeteringPointAssignmentPermission` | `zev` | Extends `BaseZevScopedPermission`; no participant safe-method override |

### 4.3 BaseZevScopedPermission detail

**`has_permission(request, view)`:**
1. Not authenticated → deny.
2. `admin` or `may_hold_management_access(user)` → allow.
3. Safe method → allow if `allow_participant_safe_methods`, or if the account
   holds an active manager or viewer grant anywhere.
4. Unsafe method → allow if the account holds an active manager grant anywhere.

**`has_object_permission(request, view, obj)`:**
1. `admin` → allow.
2. Resolve `zev` from the object graph (Zev, Participant, MeteringPoint,
   MeteringPointAssignment).
3. **Disabled ZEV, non-safe method** → deny unless `admin`. A disabled ZEV
   stays readable to its managers, viewers (and, where the queryset admits
   them, nobody else — participants never see it); only `admin` may still
   write to it (ZEV lifecycle phase 2 — see §7.1a). `Tariff`/`TariffPeriod`/
   `Invoice`/`MeterReading` use `HasZevAccess`, which has no
   `has_object_permission`, so they don't inherit this rule — see §4.5's
   `assert_target_not_disabled` (`Tariff`/`TariffPeriod`/`MeterReading`) and
   `invoices.views._deny_if_zev_disabled` (`Invoice`).
4. Unsafe method → allow if `can_manage(user, zev)`.
5. Safe method → allow if `can_view(user, zev)`; else, if
   `allow_participant_safe_methods`, allow if
   `zev.participants.filter(user=user).exists()`.
6. Else → deny.

`ZevViewSet.disable` deliberately does **not** go through this rule: its
permission is `ZevDisablePermission` (`can_manage`, without step 3), so
calling `disable` on an already-disabled ZEV is a `400` ("already disabled")
from the view rather than a `403` from the permission layer — the caller is
not being denied permission to touch their own ZEV, the request is just
redundant.

### 4.4 Read scoping and the `zev_id` filter (`ZevScopedQuerySetMixin`)

`scope_queryset` returns the relation-scoped queryset (`_scope_by_relation`),
then narrows it by the optional `?zev_id=` query parameter. Both live here
because every ZEV-scoped viewset already funnels its `get_queryset` through
this method; leaving the parameter to each viewset is how it came to be
accepted and silently ignored on six of them (#411).

Class attributes each viewset declares:

| Attribute | Meaning |
|---|---|
| `zev_lookup` | ORM path from the model to its `Zev` (`""` for `ZevViewSet`) |
| `participant_path` | ORM path from the model to its `Participant` (`""` for `ParticipantViewSet`); `None` = a participant link reveals nothing |
| `participant_distinct` | `True` when the participant path crosses a to-many relation |
| `participant_visible` | optional `Q` a row must also match to be visible through a participant link |
| `participant_access_survives_end` | `True` when ended participant rows still count (invoices) |
| `viewer_allowed_actions` | unsafe-method actions that only read (`InvoiceViewSet`: `{"download_pdfs"}`) |
| `scope_parent_path` | write-scoping path, §4.5 |

| Viewset | `zev_lookup` | `participant_path` | Notes |
|---|---|---|---|
| `ZevViewSet` | `""` | `None` | a ZEV record (settings, bank details) is readable only through a grant, also for an account that rents in it |
| `ParticipantViewSet` | `zev` | `""` | |
| `MeteringPointViewSet` | `zev` | `assignments__participant` | distinct |
| `MeteringPointAssignmentViewSet` | `metering_point__zev` | `participant` | |
| `TariffViewSet` / `TariffPeriodViewSet` | `zev` / `tariff__zev` | `None` | |
| `InvoiceViewSet` | `zev` | `participant` | `participant_visible = sent_to_participant()`, `participant_access_survives_end = True`, `viewer_allowed_actions = {"download_pdfs"}` |
| `MeterReadingViewSet` | `metering_point__zev` | (custom `_participant_q`) | readings inside the window of an assignment the caller holds, on a current participant row |

**Read rule** (safe methods, and `viewer_allowed_actions`): admin → every
row. Otherwise the union of
- every row of a ZEV in `viewable_zev_ids(user)` (manager or viewer grant),
  disabled ZEVs included (read-only), and
- the rows reached through the caller's own participant rows
  (`<participant_path>__user = user`), excluding disabled ZEVs, only while
  the row is current (`live_participant_q`, unless
  `participant_access_survives_end`), and narrowed by `participant_visible`.

`participant_visible` narrows only the participant branch: a manager who is
also a participant of the same ZEV sees its unsent invoices through the grant.

**Write rule (default-deny).** For any other unsafe request the queryset is
just the rows of `managed_zev_ids(user)`, with no participant branch. A write
by a viewer or participant to a detail route — custom actions included —
therefore resolves to 404 in `get_object()` before view code runs.
`zev/test_access_scoping.py ViewerWriteRouterWalkTests` walks every unsafe
route to keep it that way.

| `?zev_id=` | Result |
|---|---|
| omitted, or empty | relation scope only, unchanged |
| a ZEV in the caller's scope | narrowed to that ZEV |
| a ZEV outside the caller's scope | empty list (never that ZEV's data) |
| a non-UUID value | `400` with `zev_id` in the body |

The filter can only narrow: it adds a conjunctive `filter()` to the
already-scoped queryset, so it is not a route to another tenant's data.

**Participant-only narrowing (`participant_visible`):** `InvoiceViewSet` sets
it to `invoices.models.sent_to_participant()`, so a participant sees an
invoice only once it has been sent to them (#861), and — because invoices set
`participant_access_survives_end` — keeps seeing those after leaving the ZEV.

### 4.5 Write scoping (`ZevScopedQuerySetMixin`)

`has_object_permission` runs on detail routes only — DRF has no object to
check on create, so it is never consulted there. A permission class alone
therefore governs *which existing rows* a caller may touch, not *which ZEV a
new row may be filed under*. Until #424 a `zev_owner` could post a payload
naming another community's ZEV and have it accepted on every ZEV-scoped
endpoint, and could move one of their own rows into a foreign ZEV with a
`PATCH`.

`ZevScopedQuerySetMixin` closes both directions, alongside the read scoping it
already owned. Each viewset declares `scope_parent_path`: the attribute chain
from a write payload to the ZEV the row would belong to.

| Viewset | `scope_parent_path` |
|---|---|
| `ParticipantViewSet` | `("zev",)` |
| `MeteringPointViewSet` | `("zev",)` |
| `MeteringPointAssignmentViewSet` | `("metering_point", "zev")` |
| `TariffViewSet` | `("zev",)` |
| `TariffPeriodViewSet` | `("tariff", "zev")` |
| `MeterReadingViewSet` | `("metering_point", "zev")` |

**`assert_within_scope(validated_data)`**, run from `perform_create` and
`perform_update` before the save:
1. Resolve the target ZEV via `scope_parent_path`. Not present in the payload
   (a `PATCH` that leaves the relation alone) → nothing to check, allow.
2. `admin` → allow.
3. `not zev.access.can_manage(user, zev)` (no active manager grant on it) → `ValidationError` on the relation field (HTTP 400).
4. `zev.disabled_at is not None` → `ValidationError` on the relation field,
   a different message ("This ZEV is disabled…") (ZEV lifecycle phase 2).
   This is the create-time counterpart of `has_object_permission`'s
   disabled-ZEV rule (§4.3) — DRF never consults object permissions on
   create, which is the reason this whole mixin exists, so the same rule
   needs its own check here. It runs for every viewset in the
   `scope_parent_path` table above, independent of which permission class
   that viewset uses — this is what closes the create-side of the gap
   `has_object_permission` leaves open for `Tariff`/`TariffPeriod`/
   `Invoice`/`MeterReading` (§4.3 point 3).
5. Else → allow.

Rejection is a field validation error rather than a permission denial so it
reads like DRF's other related-field errors and names the offending field
without describing the ZEV behind it.

**`assert_target_not_disabled(instance)`** (ZEV lifecycle phase 2 follow-up)
is the existing-row counterpart: `assert_within_scope` only fires when the
payload *names* the ZEV relation, so a `PATCH` editing some unrelated field of
a row already sitting under a disabled ZEV would otherwise sail through.
`admin` → allow; else resolve the instance's current ZEV via `zev_lookup`
(§4.4) and raise `ValidationError({"detail": "..."})` if it is disabled.
Called from `perform_update` (after `assert_within_scope`) and from a new
`perform_destroy` this mixin now defines. This is what gives `Tariff`/
`TariffPeriod`/`MeterReading` the same existing-row protection
`has_object_permission` already gives `Participant`/`MeteringPoint`/
`MeteringPointAssignment`/`Zev` (§4.3 point 3) — those three don't use that
permission class, so they don't inherit it any other way.

Two viewsets override `perform_destroy` completely (their own workflow guards
call `instance.delete()` directly rather than `super().perform_destroy()`),
which bypasses the mixin's version and needs its own copy of the check:
`TariffViewSet.perform_destroy` (ahead of its billed-tariff dynamic-evidence
guard) and `TariffPeriodViewSet.perform_destroy`. `InvoiceViewSet` barely uses
`perform_update`/`perform_destroy` at all — it mutates almost entirely through
custom `@action` methods and a fully custom `destroy()` — so it has its own
separate, non-inherited fix instead: see
`2026-03-invoice-lifecycle-and-communication.md` §5.2's addendum and
`invoices.views._deny_if_zev_disabled`.

Two consequences for anything added later:

- A new ZEV-scoped viewset must declare `scope_parent_path`, or its create
  route is unscoped. `None` disables the check.
- `perform_create` / `perform_update` overrides must go through
  `super()` rather than calling `serializer.save()` directly, or they step
  over the check. `AuditedUpdateMixin` sits in front of the scoping mixin and
  cooperates for this reason.

---

## 5. Authentication and account lifecycle

### 5.1 JWT authentication

**Token endpoint:** `POST /api/v1/auth/token/`

**Payload:** `{ email, password }` (preferred) or `{ username, password }` (backward-compatible)

**Two-factor challenge:** if the account has a second factor (a confirmed `TotpDevice` or a registered passkey), the password step returns `200 {"mfa_required": true, "mfa_token": "<signed>", "methods": ["totp", "recovery_code"]}` and sets **no** cookies. `POST /api/v1/auth/token/mfa/` `{mfa_token, code}` then completes the login (TOTP code or one-time recovery code). Magic-link consume and onboarding-link consume return the same challenge shape; the OAuth door honours an IdP `amr` claim instead (`OAuthProvider.require_mfa_claim`, default `False`). `methods` is `["recovery_code"]` for an account whose only factor is a passkey. A passkey (WebAuthn) itself signs in on its own via `POST /auth/passkeys/authenticate/{begin,complete}/` with no password and is never challenged. Accounts without a factor see the pre-2FA behaviour unchanged. Full contract: `2026-09-two-factor-authentication.md` §5.

Helper `accounts.jwt_utils.make_jwt_for_user(user, *, impersonated_by=None) -> dict` and `add_custom_claims(token, user)` set the custom claims (used by `CustomTokenObtainPairSerializer`, every session-minting door — verify-email, set-initial-password, magic/onboarding links, OAuth, passkey — and impersonation, so all issue the same claims):

| Claim | Value |
|---|---|
| `role` | `user.role` |
| `email` | `user.email` |
| `full_name` | `user.get_full_name()` |
| `must_change_password` | `user.must_change_password` |
| `sv` | `user.session_version` — the account's session version when the token was issued (§5.6b) |
| `impersonated_by` | admin id; only on impersonation sessions |

**Session version check:** `CookieJWTAuthentication.get_user` refuses an access token whose `sv` (a missing claim reads as `0`) differs from `user.session_version` (`401`, code `session_revoked`) — see §5.6b. That check, and token validation generally, applies to an `Authorization: Bearer` header as before; an invalid, expired or signed-out **`openzev_access` cookie** is instead treated as no credentials (the browser sends it unprompted), so public `AllowAny` endpoints — the login page's `registration-enabled/` and `oauth/providers/` — keep answering `200`, while protected views answer `401` and drive the client's refresh.
**MFA policy enforcement:** `CookieJWTAuthentication.authenticate` also refuses (`403`) an unsafe request from an account whose role requires two-factor authentication and is past its grace period with no factor enrolled, with a short exemption list for self-service security actions and every admin action on another account excluded — see `2026-09-two-factor-authentication.md` §7.3a. Not reached by `ApiKeyAuthentication` at all.

### 5.1b API key authentication

`accounts.authentication.ApiKeyAuthentication` (`backend/accounts/authentication.py`) accepts `Authorization: Api-Key ozv_<prefix>_<secret>` on every REST endpoint except the default-deny `accounts` app surface (`ACCOUNTS_API_KEY_ALLOWLIST`; see the module docstring). A key inherits its owner's access (admin, grants, participant links), is refused on unsafe methods when `read_only=True`, and marks the request `audit_source = "api_key"`.

`mcp_server.authentication.McpApiKeyAuthentication` (`backend/mcp_server/authentication.py`) subclasses it for the MCP endpoint (`POST /api/v1/mcp/` only — SPEC-2026-mcp-server): it also accepts `Authorization: Bearer ozv_…` (many MCP clients cannot send a custom scheme), skips the `accounts` allow-list and the read-only-by-method check (the endpoint is always `POST`; each MCP tool declares its own `read_only`), and marks the request `audit_source = "mcp"` instead of `"api_key"`. Only an admin or an account with a manager or viewer grant passes there (`HasZevReadAccess`); cookies/JWT are not accepted on that endpoint at all.

### 5.1a Last-login tracking

`User.last_login` (Django's own `AbstractUser` field; no migration) is stamped
by `accounts.jwt_utils.record_login(user)` — a thin wrapper around Django's
own `django.contrib.auth.models.update_last_login`, the function
`django.contrib.auth` wires to the `user_logged_in` signal for the admin site,
which none of this project's login views raise (they return JSON, not a
redirect through `django.contrib.auth.login()`).

Called explicitly, once, at each door that actually mints a new session:

- `CustomTokenObtainPairView.post` (password login, no second factor)
- `TokenMfaView.post` (the second step of a two-step login)
- `verify_email` (the auto-login on first verification)
- `oauth_token_exchange`
- `PasskeyAuthenticateCompleteView.post`
- `invoices.views_public.magic_link_consume`
- `zev.views_public.onboarding_consume`

**Deliberately not called** from `accounts.jwt_utils.make_jwt_for_user` itself,
even though every door above (except the plain password login, which builds
its tokens through the serializer directly) calls it: that function also
backs two things that are not a login and must not restamp it —
`session_revocation.keep_current_session` (reissuing tokens under the *same*
session after a password or email change) and impersonation (the admin signed
in; the target did not — neither account's `last_login` changes). A failed
password attempt, and the password-verified-but-still-awaiting-a-second-factor
response, do not stamp it either — no session exists yet at either point.
`set_initial_password` reissues claims after a first password is set, seconds
after the login that got the caller there (`verify_email` or a magic/onboarding
link); it does not call `record_login` either, for the same "not a new
sign-in" reason.

Surfaced only on `AdminUserSerializer` (§6.1); `/auth/me/`, impersonation
responses, and the detail view do not carry it.

**Token refresh:** `POST /api/v1/auth/token/refresh/` reads `openzev_refresh` cookie; CSRF via `CookieJWTAuthentication` (`SessionAuthentication.enforce_csrf` on unsafe methods) + `CsrfViewMiddleware` kept for admin/Django views. Before rotating, `CookieTokenRefreshView` also requires the refresh token's `sv` to match the account's and the account to be active; otherwise `401` and the auth cookies are cleared.

**Cookie transport:** httpOnly cookies `openzev_access` / `openzev_refresh` + `csrftoken` via `django.middleware.csrf.get_token` (`CsrfViewMiddleware` sets cookie). `CSRF_TRUSTED_ORIGINS` defaults to `CORS_ALLOWED_ORIGINS` in development. A `DEBUG=False` deployment must instead provide at least one public HTTPS trusted origin; `accounts.E005` rejects an empty or insecure list so HTTPS cookie sessions do not depend on an unverified deployment assumption.

**Production configuration checks:** `accounts.checks.production_hosts_configured` rejects empty, wildcard, or loopback-only `ALLOWED_HOSTS` (`accounts.E003`) and requires `FRONTEND_URL` to be a public HTTPS origin (`accounts.E004`). `production_configuration_configured` rejects the console email backend and incomplete SMTP settings (`accounts.E006`/`E007`), and rejects empty or development WebAuthn relying-party settings (`accounts.E008`/`E009`). These checks are skipped when `DEBUG=True`, which is the development `.env.example` mode.

**Frontend:** `frontend/src/lib/api/client.ts` `api = axios.create({withCredentials:true, xsrfCookieName:'csrftoken', xsrfHeaderName:'X-CSRFToken'})` scoped to instance (no `axios.defaults`).

**Audit:** `CustomTokenObtainPairView.post` records an `AuditActionCategory.AUTH` event on every attempt rather than delegating to `TokenObtainPairView.post` unmodified — a successful login records `auth.login` (`status=success`, the authenticated user as both actor and target); a wrong password, unknown username, or inactive account each record `auth.login_failed` (`status=failed`, no actor — the caller proved nothing) with the attempted `email`/`username` value in `target_display` so a credential-stuffing pattern is visible without correlating requests by IP alone. The failure reason is deliberately not distinguished in the response (`CustomTokenObtainPairSerializer`'s generic "no active account" message) or in the audit event itself, to avoid the audit log becoming an oracle for account enumeration.

### 5.2 Self-registration

**Endpoint:** `POST /api/v1/auth/register/` (AllowAny)

**Payload:** `{ email }`

**Flow:**
1. Apply the per-IP throttle (`429` when exceeded), then require an object payload
   and validate the email, including the `User.email` model length limit
   (254 characters; `400` otherwise). Over-length addresses are refused before
   reserving a mail slot or issuing an account/token.
2. Reserve `register-mail:<sha256(lowercase email)>` for 15 minutes with an ownership
   nonce. An existing reservation does no work.
   A cache connection failure in either operation returns `503` before issuance;
   the throttle is never bypassed.
3. In a short transaction, lock an existing user row before checking eligibility.
   A pending signup is inactive, has an unusable password and at least one `signup`
   token, with no invitation or consumed-token history. Other existing accounts
   get no mail or token. Otherwise create the inactive user (`role=user`,
   `may_create_zev=True`, `must_change_password=True`, unusable password), retrying
   only a confirmed username collision (up to 3 attempts).
4. Create the new `signup` token in the same transaction and capture the IDs of
   earlier unused signup links. An initial token failure rolls back the new user
   as well; an issuance failure releases the owned reservation and returns the
   uniform response, allowing retry.
5. Commit before rendering and sending `{FRONTEND_URL}/verify-email?token={token}`.
   No database transaction remains open during SMTP. Editable templates use
   `config.safe_format.render_with_fallback`. A failed send retains the pending
   credential and atomically releases only its own reservation; a cache failure
   during release is logged and leaves the cooldown to expire.
6. After delivery, take the user lock again. Retire only the captured older links,
   and only if the issued token is still unused and the account inactive. Never
   delete a later issuance, recreate a cancelled token, or undo verification.
   Cleanup failures are logged separately and retain the delivered mail's cooldown.
7. Normal attempts return `201` with
   `{"detail": "If that address can be used, check your inbox."}`, including
   unavailable addresses and issuance/delivery failures. The guarantee is
   status/body normalization, not timing resistance.

**Lifecycle:** pending signup → verification activates it; explicit admin
`is_active: false` → cancelled signup with no unused activation credentials.
Cancellation applies even when already inactive, including edits that also
change other fields. The admin edit form omits `is_active`, preserving its
links. Session revocation remains an active → inactive transition. Verified
accounts and invitation accounts are excluded from signup resends. Initial
user/token creation is atomic, so a failed first issuance cannot leave a new
account without the token history that identifies a pending signup.

Registration, verification and admin updates serialize on the user row, always
locking it before reading/updating its credentials. Email is not unique at the
database level: creation of the same address is protected only by the cache
reservation, not a database invariant. A case-insensitive uniqueness migration
would need a duplicate-data and blank-address policy across all provisioning paths.

### 5.3 Email verification

**Endpoint:** `POST /api/v1/auth/verify-email/` (AllowAny)

**Payload:** `{ token }`

**Flow:**
1. Require an object payload and a string token. Trim surrounding whitespace;
   empty or over-64-character tokens return `400` before lookup.
2. Resolve the token's user ID, then acquire that user row's lock in a transaction.
3. Reload the token under the lock; require an inactive user and a valid, unused
   token within its purpose-specific lifetime (signup: 24 hours; invitation: 7 days).
   Missing, cancelled, consumed, expired and already-active cases return `400`.
4. Mark it consumed, delete other unused verification tokens, activate the user,
   and record `email.verify` in the same transaction.
5. After commit, return an MFA challenge when required; otherwise use
   `accounts.jwt_utils.make_jwt_for_user` and set the httpOnly `openzev_access` /
   `openzev_refresh` cookies (+ `csrftoken`) to sign in. A later admin cancellation
   revokes sessions using the version counter (§5.6b).

### 5.4 Initial password set

**Endpoint:** `POST /api/v1/auth/me/set-initial-password/` (IsAuthenticated)

**Payload:** `{ new_password }`

**Guard:** only allowed if `must_change_password == True` or user has no usable
password. Otherwise returns 400 ("Use the change-password endpoint instead.").

**Flow:**
1. Validate password via Django password validators.
2. Set password, clear `must_change_password` flag, revoke the account's other sessions (`revoke_sessions`, §5.6b), and revoke the account's onboarding links (`zev.onboarding.revoke_active_for_participant` — the link's stated purpose, "until they choose to set a password", is fulfilled, so a leaked mail must not stay a live bearer credential).
3. Issue fresh JWT via `accounts.jwt_utils.make_jwt_for_user(user)` set as httpOnly cookies `openzev_access` / `openzev_refresh` (+ `csrftoken` via `get_token`) so updated claims take effect.

### 5.5 Password change

**Endpoint:** `POST /api/v1/auth/me/change-password/` (IsAuthenticated)

**Payload:** `{ old_password, new_password }`

Validates old password, sets new password, clears `must_change_password`, then **signs the account out of every other session** (`revoke_sessions`, §5.6b) and revokes the account's onboarding links: whoever knew the old password, or held a stolen session, must not stay signed in. The response carries a fresh token pair under the new session version, so the caller stays signed in (an impersonation session stays an impersonation session). API keys are not revoked — they are separate credentials.

### 5.6 Profile (me)

**Endpoint:** `GET | PATCH /api/v1/auth/me/` (IsAuthenticated)

- GET → returns `UserSerializer` of current user (including `preferred_zev`,
  always present, `null` when unset).
  (The participant-only `zev_name` / `zev_count` were removed in #761 step 7;
  `memberships` carries every community name.)
- GET additionally carries `memberships` — every community the account relates
  to, in the shape of §6.4's `memberships` — and `may_create_zev: boolean`
  (#761).
- GET additionally carries `has_usable_password: boolean` — whether the account
  can re-authenticate with a password (participants and OAuth-only accounts
  cannot); the email-change form (§5.6a) is offered only when it is true.
- PATCH → partial update of **first name, last name and `preferred_zev` only**
  (`SelfUserSerializer`). A payload that tries to *change* `email`, `username`,
  `role`, `must_change_password` or `is_active` is rejected `400` naming the
  field (`"This cannot be changed here."`) and nothing in it is applied; a
  payload that merely repeats the current value is accepted and ignored, so a
  client that sends the whole object back keeps working. (Before this, any user
  could change their own email — the sign-in identifier and magic-link target —
  without re-authenticating, clear a forced password change, or deactivate
  themselves.) Admins edit all of these through `PATCH /auth/users/{id}/`. The
  response is shaped like GET.
- `preferred_zev` accepts a ZEV UUID or `null`. Only a community the account
  belongs to is accepted — one it can view (admin, grant) or holds a current
  or past participant row in (`400` "You can only set a community you belong
  to as the default." otherwise).

### 5.6a Email change

The email is the login identifier and the target of every emailed sign-in link,
so whoever controls it controls the account. Changing it therefore survives a
stolen session: the request needs the current password, the new address must
prove it is reachable before anything changes, and the old address is told.

**Request:** `POST /api/v1/auth/me/email-change/` (IsAuthenticated) `{ new_email, current_password }`,
throttled per account (`AuthEmailChangeThrottle`, scope `auth_email_change`,
`5/hour`, `AUTH_EMAIL_CHANGE_THROTTLE_RATE` — it also bounds password guessing by
a session holder).

| Outcome | Response |
|---|---|
| Impersonation session | `403` |
| Account has no usable password (participants — whose address the community owner maintains on the participant record — and OAuth-only accounts) | `403` `{code: "no_password"}` |
| Malformed address / same as current / missing or wrong password | `400` (wrong password audited `auth.email_change.failed`, reason `bad_password`) |
| Address held by another account (case-insensitive) | `202`, **same body as success**, no mail sent — cannot be used to find which addresses have accounts; audited `auth.email_change.failed` (`DENIED`, reason `address_in_use`) |
| Otherwise | `202`; a confirmation link is emailed to the **new** address; audited `auth.email_change.requested`. A mail failure returns the same `202` body, is logged and audited as `auth.email_change.failed` (`FAILED`, reason `mail_failed`), and is not recorded as requested. |

**Token:** `accounts/email_change.py` — a `django.core.signing` token (salt
`accounts.email-change`, 24 h) carrying `{u: user id, n: new address, f: fingerprint}`,
where the fingerprint is a hash of the account's *current* address and password
hash. It is stateless yet single-use and mortal: applying it changes the
address, and any later change of address or password makes the fingerprint
differ. It also dies if the account is deactivated or someone else took the
target address meanwhile.

**Confirm:** `POST /api/v1/auth/confirm-email-change/` `{ token }` (AllowAny,
`AuthVerifyThrottle`, `auth_verify`) — unauthenticated because the link is opened
from a mailbox, possibly on another device. Every refusal is the same `400 "This
link is invalid or has expired."`. On success, under a row lock: set the
address, **revoke all sessions** (§5.6b), email the *previous* address (which
shows only a masked new address), audit `auth.email_change.confirmed` (actor =
the account, diff of `email`). No session is minted; the person signs in again
with the new address.

Frontend: `EmailChangeForm` (Profile tab; "managed by your administrator" hint
when `has_usable_password` is false) and the public `/confirm-email-change`
page (`ConfirmEmailChangePage`, spends the single-use link exactly once even
under React StrictMode). The mails are fixed system messages
(`accounts/emails.py`), deliberately not `EMAIL_TEMPLATE_DEFAULTS` entries: a
security notice an admin can reword can be made to stop saying what happened.

### 5.6b Session revocation ("sign out everywhere")

Tokens are stateless JWTs, so nothing server-side lists "sessions". Instead
`User.session_version` (`PositiveIntegerField`, default `0`, migration `0019`)
is stamped into every token as `sv`; bumping it makes all earlier tokens fail
(§5.1). Decision and trade-offs: ADR 0022. API keys are separate credentials and
are not affected.

`accounts/session_revocation.py`: `revoke_sessions(user)` — an atomic
`UPDATE … SET session_version = session_version + 1`, then a reload so tokens
minted straight afterwards carry the new value; `keep_current_session(request,
response, user)` — hand the caller a fresh pair so revoking *other* sessions
does not sign them out. `User.save()` deliberately never writes
`session_version` (a plain save from an instance loaded before a revocation
would otherwise write the old value back and revive the sessions just signed
out).

Sessions are revoked, all with `auth.*` audit events where the action is an
explicit one:

| Trigger | Effect |
|---|---|
| Password change / initial password set | other sessions end; caller keeps theirs |
| Email change confirmed | all sessions end |
| Admin two-factor reset (`DELETE /users/{id}/mfa/`) | target's sessions end |
| Admin deactivates an account (`PATCH /users/{id}/` `is_active: false`) | sessions end — so reactivating later does not bring back unexpired tokens |
| `POST /api/v1/auth/me/sessions/revoke/` (IsAuthenticated; `403` while impersonating) | other sessions end; caller keeps theirs; audited `auth.sessions.revoked` (`scope: others`) |
| `POST /api/v1/auth/users/{id}/revoke-sessions/` (IsAdmin; `400` for the admin's own account) | all of the target's sessions end; audited `auth.sessions.revoked` (`scope: all`, admin as actor) |
| `POST /api/v1/auth/logout/` (AllowAny; CSRF-enforced, unauthenticated by design so it still clears cookies when the access token is already expired — the user is resolved from the refresh cookie instead) | **all** of the caller's sessions end, on every device; audited `auth.logout` (`scope: all`). Only a token from a currently valid session revokes; stale tokens just clear cookies. During impersonation this revokes the *impersonated* account (the main cookies hold its tokens), never the admin parked in the backup cookies — the event's actor is the impersonated account. |

Not revoked by design: API keys, an
outstanding MFA challenge token. There is no per-device list: a counter can say
"everything before now is dead", not "this one device" (ADR 0022).

All four new endpoints are absent from `ACCOUNTS_API_KEY_ALLOWLIST`
(default-deny): a key must not be able to re-point or sign out its own owner.

Frontend: `SessionsCard` on the Security tab ("Sign out other devices"), and
"Sign out everywhere" in the admin accounts row menu (not on the admin's own row).
Explicit logout ("Logout" in the user menu) signs out everywhere by design —
the 7-day refresh token would otherwise survive it.

### 5.6c Security notification emails

`accounts/notifications.py`. Every change to how an account is secured emails
that account's own address a short, fixed notice — not an editable
`EMAIL_TEMPLATE_DEFAULTS` entry, and it cannot be turned off (a security notice
an admin can reword can be made to stop saying what happened).

| Trigger | Event | Names |
|---|---|---|
| `POST /me/passkeys/register/complete/` | `passkey_added` | the passkey |
| `DELETE /me/passkeys/{id}/` | `passkey_removed` | the passkey |
| `POST /me/mfa/totp/confirm/` | `totp_enabled` | — |
| `DELETE /me/mfa/totp/` (only if the device was confirmed) | `totp_removed` | — |
| `POST /me/mfa/recovery-codes/` | `recovery_codes_regenerated` | — |
| `POST /me/change-password/` | `password_changed` | — |
| `DELETE /users/{id}/mfa/` (only if something was removed) | `mfa_reset_by_admin` | — |
| `POST /users/{id}/revoke-sessions/` | `sessions_revoked_by_admin` | — |

Not sent for: an abandoned (unconfirmed) TOTP enrolment either begun or
discarded; `POST /me/sessions/revoke/` (the person's own action, on themselves);
a `DELETE /users/{id}/mfa/` that had nothing to remove. The email-change
confirmation and notice (`emails.py`, §5.6a) are part of that flow and are not
`notifications.py` events.

`notify(user, event, *, request=None, detail="")` is called as the last step of
each action above, after it has already succeeded, and never raises: a
notification failure must not turn a completed action into an error response.
It queues `accounts.tasks.send_security_notification` (Celery; `autoretry_for`
`OSError`/`SMTPException`, backoff, 3 retries) — a slow mail server cannot hold
up the request. `django.conf.settings.EMAIL_TIMEOUT` (default 20s,
`EMAIL_TIMEOUT` env var) bounds that server-side. The task re-reads the account
by id at send time and sends nothing if it is gone, deactivated, or has no
address by then. `compose(user, event, *, detail, when, ip)` is pure (no I/O),
so its wording is unit-tested directly; `ip` comes from
`request.audit_ip_address` (the audit middleware) and is omitted from the body
when unknown.

### 5.7 Impersonation

**Endpoint:** `POST /api/v1/auth/users/{user_id}/impersonate/` (IsAuthenticated)

**Permission:** admin only (`request.user.is_admin`).

**Allowed targets:** any active non-admin account (#761: impersonation is on
the account, and the session sees everything it holds — every grant and
participant row). Impersonating an admin or an inactive account returns 400
(`"Admin and inactive accounts cannot be impersonated."`, audited `DENIED` with
metadata `is_admin` / `is_active`).

**Flow:**
1. Generate via `_make_jwt_for_user(target)` + `impersonated_by = request.user.id` claim, set as httpOnly cookies `openzev_access` / `openzev_refresh` (+ `csrftoken` via `get_token`); park caller tokens in `ADMIN_ACCESS_COOKIE` / `ADMIN_REFRESH_COOKIE`.
2. Return `{ impersonated_user, impersonator }` (tokens are cookies, not body).

**Frontend flow (`AuthContext.startImpersonation`):**
1. Call impersonate endpoint (cookies handled via `api` with `withCredentials`); backup cookies stored httpOnly.
2. Re-fetch `/auth/me/` to update the UI context.

**Stop impersonation:** restore `ADMIN_*` cookies to main pair, clear backup cookies, re-fetch `/auth/me/`.

### 5.7a Frontend query cache lifecycle

Most TanStack Query keys (invoices, metering data, dashboard summaries, ...)
are not partitioned by user identity — see `queryKeys.ts`. Without an
explicit reset, a response still in flight for the outgoing account could
resolve after the switch and land in the cache the incoming account reads
from, or a component still mounted through the transition could go on
showing the previous account's cached data (openzev#573).

`AuthProvider` closes that gap with a single `resetQueryCache()` helper,
called at every point the authenticated identity changes — `login`,
`logout`, `startImpersonation`, and `stopImpersonation` (the same four
boundaries `invalidatePrefSaves()` already guards, see 9.4):

1. `await queryClient.cancelQueries()` — marks every in-flight query
   cancelled, so a response that resolves after this point is discarded by
   react-query instead of being written into the cache.
2. `queryClient.clear()` — drops every cached query result and mutation
   state, so nothing from the outgoing identity survives for a component
   that stays mounted across the transition to read.

`login` and the impersonation transitions await this before issuing their
network request, so the cache is empty before the new identity's data can
start loading. `logout` clears synchronously alongside `setUser(null)` and
fires the reset without awaiting it, matching its existing fire-and-forget
`logoutRequest()` call.

`refreshUser()` updates the same-account user snapshot without clearing the
query cache. Account link/unlink changes in another session are picked up
on page reload or an explicit `refreshUser()` call; the client has no polling
or push for these changes. Link/unlink actions leave JWT sessions valid, while API
permissions use the current database user. Reloading also starts a fresh
frontend query cache.

### 5.8 Forced password change redirect

`ProtectedRoute` sends required password changes to `/account` with
`state.forcePasswordChange = true`; see the guard ordering and account-route
matching in §9.1.

### 5.9 Auth endpoint throttling

Every public auth *write* endpoint carries a per-IP rate limit
(`AuthRateThrottle` subclasses in `accounts/throttling.py`), so a stranger who
can hit them without any credential is bounded even when the interactive UI's
cookie sessions stay unthrottled:

| Endpoint | Throttle class | Scope | Default rate (env override) |
|---|---|---|---|
| `POST /api/v1/auth/token/` | `AuthLoginThrottle` | `auth_login` | `40/hour` (`AUTH_LOGIN_THROTTLE_RATE`) |
| `POST /api/v1/auth/token/mfa/` | `AuthMfaThrottle` | `auth_mfa` | `10/hour` (`AUTH_MFA_THROTTLE_RATE`), keyed on the account in the challenge token (per-IP if the token is unreadable) |
| `POST /api/v1/auth/passkeys/authenticate/{begin,complete}/` | `AuthPasskeyThrottle` | `auth_passkey` | `30/hour` (`AUTH_PASSKEY_THROTTLE_RATE`), per IP, both calls counted |
| `POST /api/v1/auth/token/refresh/` | `AuthRefreshThrottle` | `auth_refresh` | `60/hour` (`AUTH_REFRESH_THROTTLE_RATE`) |
| `POST /api/v1/auth/register/` | `AuthRegisterThrottle` | `auth_register` | `10/hour` (`AUTH_REGISTER_THROTTLE_RATE`) |
| `POST /api/v1/auth/verify-email/` | `AuthVerifyThrottle` | `auth_verify` | `30/hour` (`AUTH_VERIFY_THROTTLE_RATE`) |
| `POST /api/v1/auth/confirm-email-change/` | `AuthVerifyThrottle` | `auth_verify` | shares the verify budget |
| `POST /api/v1/auth/me/email-change/` | `AuthEmailChangeThrottle` | `auth_email_change` | `5/hour` (`AUTH_EMAIL_CHANGE_THROTTLE_RATE`), per authenticated account |
| `POST /api/v1/auth/oauth/login/<provider_slug>/` | `AuthOAuthInitiateThrottle` | `auth_oauth_initiate` | `60/hour` (`AUTH_OAUTH_INITIATE_THROTTLE_RATE`) |
| `POST /api/v1/auth/oauth/token-exchange/` | `AuthOAuthExchangeThrottle` | `auth_oauth_exchange` | `40/hour` (`AUTH_OAUTH_EXCHANGE_THROTTLE_RATE`) |

Rates live in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`. A request over the
budget is refused with `429 Too Many Requests` before the view body runs. The
test settings (`config/settings_test.py`) disable all scopes so the rest of the
suite is not throttled.

Limits are keyed by DRF's `SimpleRateThrottle.get_ident()` through `NUM_PROXIES` trusted hops. The audit log records the same hop via `config.client_ip.client_ip`, storing invalid or empty values as `NULL` for inet safety instead of DRF's raw-string bucket. The shipped nginx configurations overwrite `X-Forwarded-For`; with `NUM_PROXIES=1`, an outer proxy's address is therefore the attributed identity. Preserving the original client address requires a deliberately sanitised, append-preserving proxy chain and a matching hop count. Operator guidance is canonical in `charts/openzev/README.md` ("Reverse proxies and NUM_PROXIES").

Shipped values: default `0`; production-like and fullstack compose set `1` behind overwriting nginx; dev compose keeps `0`; Helm `backend.numProxies` defaults to `0` on the backend deployment only.

---

## 6. User management (admin)

### 6.1 User list

**Endpoint:** `GET /api/v1/auth/users/` (IsAdmin)

Admin only — the user list is the instance-wide account registry; exposing it
to owners would leak every participant's contact details across communities.
Owners have no consumer for it: account linking is admin-only.

**Queryset:** all users, ordered by username. Any non-admin role → 403.

**Serializer:** `AdminUserSerializer` (list only) — `UserSerializer` plus two
read-only fields, so the page can say where an account belongs without a second
request per row:

- `memberships` — one entry per community the account relates to, sorted by
  community name (case-insensitive) then id:
  `{ zev, zev_name, zev_disabled, zev_billing_interval, access: "manager" | "viewer" | null,
  roles, participants: [{ id, valid_from, valid_to, live }] }` — its active grant
  there (if any) and every participant row it holds there, current or ended
  (#761, SPEC-2026-10-zev-access-grants §7.7). `zev_billing_interval` is the
  community's `Zev.billing_interval`, which sets a participant's dashboard
  periods. Built by `zev.access.build_memberships` from prefetched rows (active
  grants via `zev.access.active_grants_prefetch()`, participations with their
  ZEV), so the
  list stays a fixed number of queries. `/auth/me` returns the same shape for
  the caller.
- `mfa_methods` — `"totp"` (a *confirmed* authenticator device; an abandoned
  enrolment does not count) and/or `"passkey"`, in that order.
- `mfa_compliance` — where the account stands against
  `AppSettings.mfa_required`, or `null` when the policy is off: `{ status: "compliant" | "grace" | "overdue", deadline }` (`deadline`
  ISO datetime, from `mfa.grace_deadline`). `"compliant"` once the account holds
  any factor, regardless of the deadline; otherwise `"grace"` before the
  deadline and `"overdue"` after it. Computed by `mfa.compliance_status(user,
  app_settings=..., has_factor=...)`, called with the `AppSettings` singleton
  loaded once per request (cached on the one child serializer instance a
  `many=True` list reuses for every row) rather than once per account — see
  the query-count test.

Both `memberships` and `mfa_methods` are derived from prefetched relations
(`select_related("totp_device")`, `prefetch_related` on the active grants,
`participations__zev`, `webauthn_credentials`), so the list costs a fixed
number of queries whatever the number of accounts (pinned by a query-count
test). `/auth/me/`, impersonation responses and the detail view keep the plain
`UserSerializer` and do not carry these fields.

`last_login` — the account's own `User.last_login`, stamped at every genuine
sign-in (§5.1a) and `null` for an account that has never signed in. This is
the one added field that is not derived from a prefetched relation; it costs
nothing extra since it is a plain column on the already-selected row.

### 6.2 User create

**Endpoint:** `POST /api/v1/auth/users/` (IsAdmin)

**Payload:** `{ username, email, first_name, last_name, role, password?, password2? }`

Admin only. `password`/`password2` are **optional**. The admin console's "New
account" action sends neither: `UserCreateSerializer.validate()` then generates
a random 16-character password (`generate_temporary_password`) and stashes it
on `self.generated_password` for the view to read — never persisted anywhere
but the hashed column. `UserListCreateView.create()` overrides the default
`CreateModelMixin` behaviour to add `generated_password` to the response body
when one was generated (never present when the caller supplied their own).
Either way `password2` must match `password` (`400` otherwise) and the account
is created with **`must_change_password=True`**: nobody but the account holder
should keep a password an admin picked or generated. A supplied password still
runs through Django's validators; a generated one does not (nothing for a
human to judge as weak) but is long enough to pass them on the next change.

### 6.3 User detail

**Endpoint:** `GET | PATCH | DELETE /api/v1/auth/users/{id}/` (IsAdmin)

- PATCH: `UserSerializer` partial update. Role-change safety:
  - Admin cannot change own role away from admin.
  - Non-admin cannot change any role.
  - **Deactivation safety** (`validate_is_active`): an admin cannot set
    `is_active: false` on their **own** account (`400`) — deactivating already
    revokes every session (`UserDetailView.perform_update`, §5.6b), so doing it
    to yourself would sign you out mid-edit with no way back in except another
    administrator. There is no separate "last active admin" guard: the only way
    to reach zero active admins through `is_active` is exactly this case (a
    non-self deactivation always leaves the acting admin active).
- DELETE: two guards:
  1. **Last-admin guard** — blocked if the target `is_admin` and no other
     user with `role=admin` exists (→ 403 "Cannot delete the last admin
     account."). Self-deletion is allowed when another admin remains.
  2. **Linked-account guard** — blocked if user has linked participant records
     (→ 403 "Linked participant accounts cannot be deleted.").
  3. **Last-manager guard** — the delete runs inside `zev.access.keeping_a_manager`
     over every ZEV the account manages (grant or role, `managed_zev_ids`); when its
     cascaded manager grants or its cleared `Party.user` leave one of them without a
     manager, it is rolled back (→ 403 `NO_MANAGER_LEFT`, denied `user.delete` audit
     event). SPEC-2026-10-zev-parties §5.5.

  Success audit is recorded before `instance.delete()` so the actor FK is
  valid; `on_delete=SET_NULL` nullifies `actor_user` on self-deletion while
  preserving `actor_display` and `target_id`.

### 6.4 Admin accounts page (frontend)

**File:** `frontend/src/pages/AdminAccountsPage.tsx` (Users tab of
`AdminAccountsHubPage`). Helpers in `frontend/src/features/accounts/`.

**Model of the page:** one row per *account* — not per participant. An account
that belongs to several communities is still one row, with one chip per
community. This replaced a participant-first table in which the same account
repeated per participant row and the role editor on each row silently changed
the account's role everywhere.

- **Columns:** *Account* (display name, platform-role badge, `Inactive` badge
  when `is_active` is false, `username · email`), *Communities*
  (`AccountMemberships`), *Security* (a badge per `mfa_methods` entry or "No
  two-factor", `AccountMfaComplianceBadge` when `mfa_compliance` is non-null
  and not `"compliant"`, and a muted "Last sign-in `<date>`" /
  "Never signed in" line from `last_login`), *Actions*.
- **Membership chips** read `Owner|Participant · <community>`. Selecting one
  calls `setSelectedZevId(zev)` (as the scope-line community switch does — which also
  saves the admin's `preferred_zev`, as any switch does) and opens
  `/participants?focus=<participant>` (`/participants` when the account is an
  owner with no participant record). Memberships are edited there, not here.
- **Stats:** accounts, accounts with two-factor, accounts without a community
  (non-admin accounts with no membership: the ones waiting for access or a
  participant link), accounts the MFA policy names that have not enrolled
  yet (`accountList.needsTwoFactor`: `"grace"` or `"overdue"`), accounts that
  have never signed in (`last_login === null`).
- **Filters** (`accountList.filterAccounts`, client-side): search over display
  name, username and email; platform role (`admin` / `user`); community; two-factor (all accounts,
  or only those `needsTwoFactor`). The community filter matches *any*
  membership, owner or participant.
- **New account** (`AccountCreatedNotice` in
  `frontend/src/features/accounts/`): a platform account not tied to any
  community — a second admin, an API-only service account, or any account an
  operator wants to set up ahead of use. The form asks for username, email,
  names and platform role only; there is no password field — `createUser`
  never sends one, so the server always generates it (§6.2). The response's
  `generated_password` (when present) is shown once in a dismissible notice
  with a copy button and is never requested from the server again.
- **Actions:** *Edit* (username, email, names, **platform role** — labelled as
  such, with a hint that it applies in every community); menu: *Impersonate*
  (any active non-admin account — `canImpersonateAccount`), *Reset
  two-factor*, **View activity** (navigates to
  `/admin/audit?actor=<id>&actorUsername=<username>` — the platform audit log
  pre-filtered to this account as actor; see
  `2026-05-audit-log-and-operational-traceability.md` §7.1), *Sign out
  everywhere*, *Deactivate*/*Activate* (toggles `is_active`; not offered on
  the admin's own row — the server refuses deactivating yourself, §6.3),
  *Delete*. *Delete* is disabled while the account belongs to any community
  (`canDeleteAccount`, mirroring the server's guard) and is not offered for
  the admin's own row.
- **Activation:** follows the
  [dialog contract](2026-04-frontend-management-page-design.md#dialog-behavior)
  and leaves open edit forms unchanged.
- **Removed from this page:** the participant-linking *Link existing*/*Create
  account*/*Unlink* actions and the participants-without-account rows — see
  §6.5. ("Create account" there created an account *for a specific
  participant*; "New account" above is unrelated — a platform account with no
  participant attached.)

### 6.5 Account linking on the Participants page (frontend)

Linking is a fact about one community's participant, so it lives with the
participants (`ParticipantCardsSection`, `useParticipantAccountLinking`,
`LinkAccountModal` in `frontend/src/features/participants/`).

- Each participant card has an **Account** section: the linked username, or "No
  account yet".
- **Admin only** (the endpoints are admin-only; the accounts query only runs for
  admins): *Link existing* in the card menu when the participant has no account
  and at least one linkable account exists (`accountList.linkableAccounts` —
  any non-admin account, also one already holding participant rows elsewhere,
  matching the server's rule since #761); *Unlink* when it has one, except on
  the owner's own participant, which the server refuses to detach.
- Unlink failures produce one operation-owned error toast, including after
  dismissing the pending confirmation. `onConfirm` uses `consumeReportedError`
  to avoid a second generic dialog error; retry requires reopening the dialog.
  `participant-account-linking.test.ts` covers failures with the dialog open
  and dismissed; `confirmation-operations.spec.ts` exercises both through the
  Participants page.
- Owners keep the existing *Send/Copy/Revoke onboarding link* actions, which
  create the account. Nothing about the endpoints or permissions changed.

---

## 7. ZEV management

### 7.1 ZEV viewset

**URL prefix:** `/api/v1/zev/zevs/`
**Permission:** `[IsAuthenticated, ZevManagementPermission]`

**Queryset scoping:**
- `admin` → all ZEVs.
- otherwise → the ZEVs the account holds a manager or viewer grant on
  (`zev.access.viewable_zev_ids`). A participant link alone does not expose
  the ZEV record.

**Create (POST):** admin only (enforced in `create()` and
`ZevManagementPermission.has_permission`).

**Delete (DELETE): not a supported method.** `ZevViewSet.http_method_names`
excludes `delete`, so any `DELETE /api/v1/zev/zevs/{id}/` gets a `405`
regardless of caller — including an admin. This used to be an admin-only hard
delete (`ZevManagementPermission.has_permission`), but a bare
`instance.delete()` collides with `Invoice.zev`'s `on_delete=PROTECT` the
moment a ZEV has any invoice, and it skipped the disable-first safety step
the lifecycle (§7.1a) is built around. The only supported way to permanently
remove a ZEV is disable, then the admin-only `purge` action (§7.1b), which
deletes the `PROTECT`-guarded rows in the right order and requires
confirming the ZEV's exact name.

**Disabled ZEVs are read-only to non-admins** (`ZevManagementPermission.
has_object_permission`): any non-safe method on a ZEV whose `disabled_at` is
set is rejected unless the caller is an admin. The owner still sees it (their
`owner == user` queryset scope is unaffected by `disabled_at`) but cannot
write to it — not even re-clear `disabled_at` itself, since that field is
read-only on `ZevSerializer` regardless of disabled state.

**Serializer:** `ZevSerializer` (all fields except `disabled_at`/
`disabled_by`/`disabled_reason`, which are read-only — see §7.1a). Retrieve
uses `ZevDetailSerializer` which nests `participants` (via
`ParticipantSerializer`, many=True, read-only).

**Issuer:** `ZevSerializer` adds read-only `issuer` — `{party, display_name}`
of the party holding the issuer role today, or `null` — read from the
`issuer_roles` prefetch (`Prefetch("party_roles", ZevPartyRole issuer rows
with select_related("party"))`) that `ZevViewSet.get_queryset` adds, so a
list costs one query for all ZEVs. There is no `owner` field (#761).

### 7.1a Disable and enable (ZEV lifecycle, phases 1–2)

Disable is retirement, not deletion: nothing under the ZEV is touched, and it
is reversible via `enable`. This is the ZEV lifecycle issue's three-state
model (`active → disabled → gone`) — the state, its two entry points, and (as
of phase 2) cutting off access to what is under a disabled ZEV. Still not
done, tracked on that issue: the dynamic-tariff/invoice Celery tasks skipping
a disabled ZEV; the admin purge; and any frontend UI — nothing calls either
action yet, so this remains API-only.

**`POST /api/v1/zev/zevs/{id}/disable/`** — the ZEV's owner, or an admin.
Permission is `ZevDisablePermission` (not `ZevManagementPermission`, which
would otherwise sweep this POST into its admin-only rule, and deliberately
not the ordinary `BaseZevScopedPermission` either — see §4.3) via a
`get_permissions()` override keyed on `self.action`. Body: `{"reason": "..."}`
(optional, defaults to `""`). Sets `disabled_at = now()`, `disabled_by =
request.user`, `disabled_reason = reason`; `400` if already disabled. Returns
the updated `ZevDetailSerializer` representation. Records `zev.disable`
(category `governance`), with `metadata.reason` when a reason was given.

**`POST /api/v1/zev/zevs/{id}/enable/`** — admin only (`IsAdmin`, via the same
`get_permissions()` override) — the owner cannot self-serve this. Clears
`disabled_at`/`disabled_by`/`disabled_reason`; `400` if not currently
disabled. Records `zev.enable`.

**Access cutoff (phase 2):** once disabled —

- A participant loses read access to everything under that ZEV that
  `ZevScopedQuerySetMixin` scopes for them: metering points, invoices, and
  readings via the metering `raw-data`/`chart-data` actions (§4.4). Not
  `Participant`/`MeteringPointAssignment` rows specifically — a participant
  already gets `403` from every method on those two regardless of ZEV state
  (§12.1), so there was nothing for this change to alter there.
- Managers and viewers keep read access everywhere (the grant branch of the
  scoping is untouched by the disabled-ZEV rules) but lose write access to every ZEV-scoped model —
  `Zev`/`Participant`/`MeteringPoint`/`MeteringPointAssignment` via
  `has_object_permission` (§4.3), `Tariff`/`TariffPeriod`/`MeterReading` via
  `assert_target_not_disabled` (§4.5), `Invoice` via its own
  `_deny_if_zev_disabled` — and to creating any new row under the ZEV
  (`assert_within_scope`, §4.5, plus `Invoice`'s `generate`/`generate-all`,
  below). `revoke-access` and both PDF downloads are deliberately exempt:
  revoking reduces exposure, and downloads are reads.
- The public unauthenticated routes reject a disabled ZEV exactly like their
  existing "not valid" cases, so a bearer of an old link cannot tell a
  disabled ZEV apart from a wrong secret or an opted-out one:
  `invoices.access_tokens.resolve()` (invoice QR links, and the magic-link
  request/consume flow built on it — see
  `2026-09-participant-invoice-access.md`) and `zev.onboarding.resolve()`
  (onboarding links — see `2026-09-participant-onboarding-link.md`) both
  return `None` for a disabled ZEV's token, same as every other failure.
- Generating a new invoice for a disabled ZEV — `POST /invoices/generate/`
  and `/invoices/generate-all/` — is refused (`400`, non-admin only). These
  two bypass `ZevScopedQuerySetMixin` entirely (a direct `Participant`/`Zev`
  lookup, not a `ModelViewSet` create), so `assert_within_scope` never
  reaches them; each carries its own copy of the same rule instead. See
  `2026-03-invoice-lifecycle-and-communication.md` §5.2 for the full list of
  invoice write actions and which are blocked.

**Self-setup guard, updated:** `self_setup`'s "you already have a ZEV" check
(§7.3) now excludes disabled ZEVs (`disabled_at__isnull=True`), so an owner
who disables their only community is not permanently locked out of creating a
replacement through that endpoint.

The ZEV list awaits enable/disable requests, reports failures through the
operation's mutation, and disables repeat actions while pending. Confirmations
follow the [dialog contract](2026-04-frontend-management-page-design.md#dialog-behavior).

### 7.1b Purge (ZEV lifecycle, phase 4)

The terminal transition (`active → disabled → gone`). Implemented in
`zev.purge.purge_zev()`, called from `POST /api/v1/zev/zevs/{id}/purge/`
(`IsAdmin`, via the same `get_permissions()` override as `enable` — the
owner cannot self-serve this either). Body: `{"confirm_name": "<exact ZEV
name>"}`; a mismatch is `400` and nothing is touched. Refuses (`400`,
`ZevPurgeError`) unless the ZEV is already disabled — purge is never a
shortcut from active.

The frontend validates and captures the ZEV id and typed confirmation at
submission. Purge follows the
[dialog contract](2026-04-frontend-management-page-design.md#dialog-behavior).

**What is deleted.** Every model that hangs off a ZEV is `CASCADE` from
`Zev` directly or from a row that is itself `CASCADE` from it —
`Participant` (→ `MeteringPointAssignment`, `ParticipantOnboardingToken`),
`MeteringPoint` (→ `MeterReading`, `MeteringPointAssignment`), `Tariff`
(→ `TariffPeriod`), `metering.ImportLog` — so Django's delete collector
walks all of that from one `zev.delete()`. Two relations are `PROTECT`
instead and are deleted explicitly first, in their own step:
`invoices.Invoice` (whose own `CASCADE` children —
`InvoiceItem`/`InvoiceDynamicSourceEvidence`/`InvoiceAccessToken`/
`EmailLog` — then follow automatically) and `exports.ExportJob`. Everything
runs inside one `transaction.atomic()` block.

**What survives**, via `SET_NULL`: `audit.AuditEvent.zev`,
`invoices.ContractIssue.zev`/`.participant`, `backups.BackupJob.zev`,
`accounts.User.preferred_zev`. `ContractIssue` is documented as an immutable
archive; the audit trail (including the `zev.purge` event itself) is the
record that the purge happened, not something the purge should erase.

**Media files.** `Invoice.pdf_file` and `ExportJob.result_file` are not
touched by `on_delete` at all — Django never deletes `FileField` bytes on
row delete — so their storage paths are collected before the transaction
and the files removed from storage only after it commits (a rolled-back
transaction must not have already destroyed files a rollback cannot bring
back).

**Response:** `{"detail", "deleted_counts": {export_jobs, invoices,
participants, metering_points, tariffs}, "media_files_deleted"}`. Records
`zev.purge` (category `governance`) the same way `zev.delete` does — by
`target_id`/`target_display` only, no `target=`/`zev=`, since the row is
already gone — with the same counts in `metadata`.

**Deliberately not done**, tracked on the ZEV lifecycle issue: an automatic
pre-purge safety backup. The backups feature already takes one before a
per-ZEV *restore* (`backups.tasks._take_safety_backup`), but that helper is
shaped around a `RestoreJob` and a configured `BackupDestination` — wiring
an equivalent into this synchronous request/response flow is its own piece
of work. An admin who wants that safety net today can export a transfer
archive or run `openzev_backup` before purging. No frontend UI yet either.

### 7.2 Create-with-owner wizard

**Frontend:** `ZevListPage` runs a four-step modal (ZEV details, responsible
person + payment details, metering points, review). Step 3 lists every
metering point as an inline-editable row (meter ID, meter type, location
description) — there is no separate editor or draft, so what is on screen is
exactly what gets sent. It starts with one empty row; "Add metering point"
appends a row and focuses its meter ID; a row can be deleted while more than
one remains. "Next" requires a non-blank, unique (after trimming) meter ID on
every row; on failure the banner names the problem and each offending row
shows its own error.

**Endpoint:** `POST /api/v1/zev/zevs/create-with-owner/` (admin only)

**Payload:** `ZevCreateWithOwnerSerializer`:
```json
{
  "name": "...",
  "start_date": "...",
  "zev_type": "vzev",
  "billing_interval": "monthly",
  "grid_operator": "...",
  "bank_name": "...",
  "bank_iban": "...",
  "owner": {
    "username": "",
    "title": "mr",
    "first_name": "...",
    "last_name": "...",
    "email": "...",
    "phone": "...",
    "address_line1": "...",
    "postal_code": "...",
    "city": "..."
  },
  "metering_points": [
    { "meter_id": "CH...", "meter_type": "consumption" }
  ]
}
```

`bank_name` is an optional informational label for the payment account, and
`bank_iban` is optional (both allow_blank). Non-empty IBANs are
normalized to compact uppercase form and validated with the ISO 13616 MOD-97
checksum. The wizard and self-setup endpoint use the shared
`has_required_iban_address()` helper for the recipient-address rule. When an
IBAN is provided, the owner participant's address,
postal code, and city are required because they form the creditor address on a
QR-Rechnung. The wizard collects payment details alongside the responsible
person's address; the step-4 review echoes the IBAN (or `–` when blank, with
the informational bank name in parentheses only when non-empty). A blank or
invalid IBAN keeps the billing-settings warning until it is corrected.

**Service:** `create_zev_with_owner_setup()` (atomic transaction):
1. Generate unique username (email-local → full-name → first-name fallback, suffix if taken).
2. Create `User` with `role=user`, `must_change_password=True`, temporary password (the owner's manager grant comes from `Zev.save()`).
3. Create `Zev` with that user as owner.
4. Create owner `Participant` with `valid_from = zev.start_date`.
5. Create each `MeteringPoint` → create `MeteringPointAssignment` to owner participant.
6. Return `{ zev: {id, name}, owner: {id, username, temporary_password}, owner_participant_id, metering_points: [{id, meter_id}] }`.

### 7.3 Self-setup

**Endpoint:** `POST /api/v1/zev/zevs/self-setup/` (IsAuthenticated; admin or
`user.may_create_zev`, else 403 `"This account cannot create a ZEV."`; refused
with 400 while the account holds an active manager grant on a non-disabled ZEV)

For self-registered users who have completed email verification and password
setup. Creates a ZEV + owner Participant in one step.

**Payload:** `ZevSerializer` — the same optional bank fields as the wizard,
including `bank_name` / `bank_iban`. The verify-email create-ZEV card collects
the owner participant's creditor address and payment details together. It
normalizes and validates non-empty IBANs before submission and sends `""` when
left blank. The address is sent as `owner_address_line1`,
`owner_address_line2`, `owner_postal_code`, and `owner_city`; it is copied to
the owner participant created by the service.

The owner address fields are optional when no IBAN is supplied. A non-empty
IBAN requires `owner_address_line1`, `owner_postal_code`, and `owner_city`.

**Guards:**
- Admin, or `user.may_create_zev`.
- The account must not already hold an active manager grant on an *active* ZEV
  (a disabled one does not count — see §7.1a).

**Service:** `create_zev_for_existing_owner()` → creates Zev + Participant.

---

## 8. Participant management

### 8.1 Participant viewset

**URL prefix:** `/api/v1/zev/participants/`
**Permission:** `[IsAuthenticated, BaseZevScopedPermission]`

**Queryset scoping:**
- `admin` → all participants (with prefetched assignments).
- manager / viewer grant → participants of the ZEVs held (writes: managed ZEVs only).
- participant link → only own current record(s) where `user == request.user`.

### 8.2 Participant create

**Serializer:** `ParticipantSerializer` with auto-account creation.

On create:
1. Validate `email` is present (required at serializer level), and the name
   by kind: a person needs `last_name`, an organisation `organisation_name`.
2. Reject if `user` field is passed directly (accounts are created
   automatically).
2a. Without `party`, a new party is created from the name, contact and address
   fields; with `party` (an existing party of the same ZEV, else 400
   `"The party belongs to another ZEV."`), the new participation shares it.
3. Call `ensure_participant_account()`:
   - Generates unique username from participant name/email.
   - Creates `User` with `role=user`, `must_change_password=True`,
     temporary 12-char password.
   - Links user to participant.
4. Return participant data including `account_username` and `initial_password`.

On update:
1. Sync the linked user's `email`, `first_name`, and `last_name` via
   `sync_participant_user_fields()`. The role is never written (#761).
2. Edit guard: only admins may edit a participant record linked to an account
   with its own login (`zev.services.has_its_own_login`: admin,
   `may_create_zev`, or any grant ever held) — 400 on `user`. Ordinary owners
   cannot edit their own owner-linked participant record through this
   endpoint.

A participant's address is no longer geocoded: the participants map draws buildings, and the
geocode cache warm-up is dispatched (`transaction.on_commit()`, so a rolled-back write cannot
enqueue a task that reads uncommitted data) when a building with `address_line1` and `city`
is saved (SPEC-2026-10-buildings-and-sites §7.7). `ParticipantSerializer` no longer carries
`building_footprint`.

### 8.3 Participant actions

| Action | URL | Method | Permission | Description |
|---|---|---|---|---|
| Send invitation | `/{id}/send-invitation/` | POST | admin or `can_manage` | Reset password, send invitation email |
| Contract PDF (read) | `/{id}/contract-pdf/` | GET | authenticated (self or admin/owner) | Stream the latest issued contract snapshot; 404 before the first issuance. Never mints a version. |
| Contract PDF (issue) | `/{id}/contract-pdf/` | POST | authenticated (self or admin/owner) | Issue or reuse the persisted versioned contract snapshot and stream it as PDF (see SPEC-2026-08-contract-pdf-redesign) |
| Link account | `/{id}/link-account/` | POST | admin only | Link an existing non-admin account; it may already hold participant rows here or elsewhere (#761). An admin account → 400 |
| Unlink account | `/{id}/unlink-account/` | POST | admin only | Unlink the account; its role is left unchanged (#761). Blocked if the account is the ZEV owner. |
| Create account | `/{id}/create-account/` | POST | admin only | Create new user account and link to participant |

### 8.4 Invitation email flow

`send_participant_invitation()` (atomic):
1. Ensure account exists via `ensure_participant_account()`. For linked
   accounts, synchronize profile fields (never the role); the password of an
   account with its own login is left alone. Newly created accounts have the
   `user` role.
2. Generate new temporary password (12 chars).
3. Set `must_change_password = True`.
4. Send email with username + temporary password to participant email.
5. Return `(username, temporary_password)`.

---

## 9. Frontend routing and access control

The app root (`App.tsx`) mounts `AppRoutes` through a data router
(`createBrowserRouter([{ path: '*', element: <AppRoutes /> }])` +
`RouterProvider`), not `BrowserRouter`. `ZevSettingsPage` relies on this for
its in-app dirty-draft guard (`useBlocker`, blocked outside
`/zev-settings/*`): `useBlocker` throws outside a data router, so tests that
render `/zev-settings` through `AppRoutes` must use the data-router setup —
`MemoryRouter` crashes there.

### 9.1 ProtectedRoute component

`ProtectedRoute({ children, allowedRoles?, allowUnlinked? })`:
1. If loading → show loading indicator.
2. If not authenticated → redirect to `/login`.
3. If `must_change_password` and not impersonating and not on `/account`
   (with an optional trailing slash) → redirect to `/account`.
4. Unless `allowUnlinked` is true, if the selected shell role is `none` and
   the path is neither `/` nor `/account` (with an optional trailing slash)
   → redirect to `/` before mounting the protected page.
5. If `allowedRoles` (a `ShellRole[]`) is specified and the account's shell
   role for the selected community (`useCommunityAccess().shellRole`, §9.4) is
   not in the list → redirect to `/`.
6. Otherwise → render children.

The outer shell guard uses `allowUnlinked` for authentication before
`ManagedZevProvider` mounts. A second guard inside the provider checks the
selected relation before mounting `Layout`. Public authentication and
bearer-link routes stay outside both guards.

### 9.2 Route → role mapping

Protected routes below exclude shell role `none` through the inner shell
guard, except `/` and `/account`.

Allowed roles are **shell roles** (`ShellRole` in `lib/communityAccess.ts`:
`admin` · `manager` · `viewer` · `participant` · `former` · `none`), the
account's relation to the selected community (§9.4). "ZEV scope" below is
`ZEV_SCOPE = ['admin', 'manager', 'viewer']` in `AppRoutes.tsx`; a viewer
reaches every ZEV-scope route and sees its pages read-only
(SPEC-2026-10-zev-access-grants §9.5).

| Route | Allowed roles | Page component |
|---|---|---|
| `/` | any authenticated | `HomePage`: `OverviewPage` in ZEV scope, `DashboardPage` for current participants, `/me/invoices` redirect for former participants, `GuestHomePage` for shell role `none` (linking explanation + secondary account link) |
| `/dashboard` | ZEV scope, `participant` | `DashboardPage` (manager title/navigation: Energy balance; participant root remains `/`) |
| `/account` | any authenticated | `AccountProfilePage` — tabs `profile` (default) · `security` (password, linked accounts, two-factor) · `api-keys`, chosen by `?tab=`; a forced password change and an OAuth link return open `security` (`resolveAccountTab`) |
| `/admin` | `admin` | `AdminOverviewHubPage` (tabs = routes; default tab `overview`) |
| `/admin/overview` · `/admin/zevs` · `/admin/invoices` · `/admin/dynamic-sources` · `/admin/audit` · `/admin/health` | `admin` | `AdminOverviewHubPage tab=…` (KPIs · ZEVs table · all invoices · dynamic price sources · platform audit log · System health) |
| `/admin/audit-logs` | `admin` | alias → `/admin/audit` |
| `/admin/system-settings` | `admin` | `AdminSystemSettingsPage` |
| `/admin/accounts` | `admin` | `AdminAccountsHubPage` (Users tab) |
| `/admin/accounts/users` · `/admin/accounts/api-keys` | `admin` | `AdminAccountsHubPage tab=…` |
| `/admin/api-keys` | `admin` | alias → `/admin/accounts/api-keys` |
| `/admin/templates` | `admin` | `AdminTemplatesHubPage` (PDF tab) |
| `/admin/templates/pdf` · `/admin/templates/email` | `admin` | `AdminTemplatesHubPage tab=…` |
| `/admin/pdf-templates` | `admin` | alias → `/admin/templates/pdf` |
| `/admin/email-templates` | `admin` | alias → `/admin/templates/email` |
| `/participants` | ZEV scope | `ParticipantsPage` |
| `/zev-settings` | ZEV scope | `ZevSettingsTabRoute` → `ZevSettingsPage` (General tab) |
| `/zev-settings/:tab` (`general` · `people` · `billing` · `documents` · `audit` · `export`; `parties` and `access` redirect to `people`) | ZEV scope | `ZevSettingsTabRoute` → `ZevSettingsPage tab=…` (people tab: roles and people, each with its access on its row, SPEC-2026-10-zev-parties §8.3; audit tab embeds `AuditLogsPage scope="owner"`; export tab keeps the transfer archive) |
| `/audit-logs` | ZEV scope | alias → `/zev-settings/audit` (owner-scoped log in the settings hub) |
| `/metering/points` | ZEV scope, `participant` | `MeteringPointsPage` (read-only for participants, no nav entry; former participants redirect home) |
| `/metering-points` | ZEV scope, `participant` | alias → `/metering/points` |
| `/metering/chart` | ZEV scope, `participant` | `MeteringChartPage` (`tab="chart"`, guarded against former participants; tab switches preserve state) |
| `/metering/quality` | ZEV scope | `MeteringChartPage` (`tab="quality"`) — intentional participant restriction: quality shows whole-ZEV severity counts, participant names, and overlap warnings (operator view; backend role-scoping means no leak either way) |
| `/metering/imports` | ZEV scope | `MeteringChartPage` (`tab="imports"`, consuming the header-free `ImportsContent` body) |
| `/metering-data` | any authenticated | alias → `/metering/chart`, except `?tab=quality` → guarded `/metering/quality`; `tab` is always stripped, remaining params preserved |
| `/imports` | ZEV scope | alias → `/metering/imports` (query preserved) |
| `/tariffs` | ZEV scope | `TariffsPage` |
| `/billing/invoices` · `/billing/emails` | ZEV scope | `BillingHubPage tab=…` (invoices · email delivery/history + retry) |
| `/billing/statements` | any authenticated | alias → `/reports` (the annual-statement ZIP moved there with the other yearly documents) |
| `/billing/periods` | ZEV scope | compatibility alias → `/`, where period work lives on manager Overview |
| `/billing/invoices?period_start&period_end` | ZEV scope | deep link from the Overview period table preselects that period |
| `/billing` | ZEV scope | alias → `/billing/invoices` |
| `/invoices` | ZEV scope | alias → `/billing/invoices` (query preserved) |
| `/invoices/:invoiceId` · `/billing/invoices/:invoiceId` | any authenticated | `InvoiceDetailPage` (own invoices only for participants, backend-enforced) |
| `/me/statement` | `participant` | `ReportsPage` (participant branch; impersonating admins carry the target account's relations) |
| `/me/invoices` | `participant`, `former` | `MyInvoicesPage` (own invoices, read-only; reuses the role-scoped invoice list — no new grant, recorded exception 2) |
| `/reports` | ZEV scope, `participant` | `ReportsPage` (participants: own downloads; owners/admins: annual ZEV report, tax overview, and annual-statement ZIP) |
| `/login` | public | `LoginPage` |
| `/verify-email` | public | `VerifyEmailPage` |
| `/confirm-email-change` | public | `ConfirmEmailChangePage` |
| `/oauth/callback` | public | `OAuthCallbackPage` |
| `/join/:prefix` | public | `ParticipantOnboardingPage` (onboarding bearer link) |
| `/signin/:token` | public | `MagicSignInPage` (magic sign-in link) |
| `/i/:prefix` | public | `PublicInvoicePage` (invoice bearer link) |

Legacy admin routes `/admin/settings/regional`, `/admin/settings/vat`,
`/admin/features`, and `/admin/oauth` redirect into tabs on
`/admin/system-settings` and remain admin-only.

Aliases use `AliasNavigate`, `InvoiceDetailAlias` or `MeteringDataAlias`:
redirects replace
history and retain incoming query parameters/hash; destination-pinned query
keys (System tabs) win over incoming values. Invoice IDs are encoded in the
canonical detail path; legacy Metering removes only `tab`. Settings `access`
and `parties` use `AliasNavigate` to `/zev-settings/people`, retaining
`focus`, other query parameters and the hash. Destination guards remain
responsible for access.

Same-hub workflow links replace history and
retain query/hash/state. Cross-hub links open the destination's own context;
Reports owns year selection, and source/audit links supply their documented
filter parameters. Draft retention is described in
`2026-08-zev-transfer-archive.md` §9; source filtering in
`2026-09-dynamic-tariffs.md` §10.4.

Shared hub URL edits use `usePageNavigation`: routed tabs in Billing, Metering,
Admin Accounts, Admin Overview, Templates and ZEV Settings replace history and
retain query parameters/hash. Templates updates `template`; Metering removes
the obsolete `tab` parameter. Account and System keep query-based tabs and
push changes into history while preserving unrelated parameters/hash. Account
keeps hidden panels mounted for one-time secrets; existing active-panel and
shared settings-draft behavior in the other hubs remains intact. Standalone
invoice/import wrappers render a header plus the same body the hub consumes,
so scope/loading failures retain one route title.

### 9.3 Navigation visibility

The sidebar (`Layout.tsx`) shows sections conditionally:

| Section | Condition |
|---|---|
| Overview (`/`), Energy balance (`/dashboard`), Metering (`/metering/chart`, active on `/metering/chart` + `/metering/quality` + `/metering/imports`), Billing (`/billing/invoices`, active on `/billing/*`), Reports | `isZevScope` (shell role `admin`, `manager` or `viewer`; the `/reports` route itself also allows participants) |
| Account (`/account`) | shell role `none` (only nav entry; landing page explains the unlinked state) |
| Dashboard (`/`) | shell role `participant` |
| My invoices (`/me/invoices`) | shell role `participant` or `former` (a former participant sees only this entry) |
| Annual statement (`/me/statement`) | shell role `participant` (consumption is available on the participant dashboard) |
| Setup group (participants, metering points `/metering/points`, tariffs, ZEV settings `/zev-settings`) | `isZevScope` (audit logs live in the ZEV settings hub; no standalone entry) |
| Feasibility (`/feasibility`, standalone entry below Setup) | `isZevScope` + `feasibility_calculator_enabled` (planning tool, not a setup step) |
| Platform group (four entries: Overview `/admin`, Accounts `/admin/accounts`, Templates `/admin/templates`, Settings `/admin/system-settings`) | `role == 'admin'` (ZEVs/API keys/invoices/audit-logs/pdf+email templates live as hub tabs) |

Overview stays active on `/admin` and its six tab routes, without matching
Accounts, Templates or Settings.

The community is chosen where it is named: in the page's scope line. Every
ZEV-scoped page header names the selected community as its eyebrow
(`PageHeader` `eyebrow`); pages that name the *selected* community also pass
`communitySwitch`, and `PageHeader` then renders the name through
`CommunitySwitcher` (`frontend/src/components/CommunitySwitcher.tsx`). When
the provider lists more than one entry (§9.4), the name is a button
(`.community-switch`: the kicker's type plus a down caret) that opens a
Mantine `Menu` of every community the account relates to; otherwise — one
community, none, or no provider — it stays plain text, so a participant or
manager with one community sees no control. Each menu item shows the
community name and, for non-admin relations, the account's relation below it
(`nav.relation.{manager,viewer,participant,former}`, class
`community-menu-relation`); the current community carries `aria-current="true"`
and a check mark. When the selection is fixed (`isSelectable` false) the other
items are disabled. The switch chooses a community; it manages nothing. Its
accessible name is `nav.chooseZevCurrent` ("Choose (v)ZEV, current:
{{name}}"), its `title` `nav.chooseZev`. Keyboard handling, focus return to
the trigger on Escape or selection, and outside-click dismissal are the
menu's. When the ZEV settings draft is dirty, selecting a different community
opens `ConfirmDialog` (portalled to `document.body`, since the scope line is a
paragraph): Cancel keeps the current selection and edits; Switch without
saving changes the selection and drops the draft. Selecting the current
community or switching with a clean draft opens no confirmation.
`ZevSettingsPage` publishes and clears this state through `zevUnsavedGuard`;
`community-switcher.test.ts` covers the list, the relation labels, the plain
fallbacks, the dirty-draft flow and fixed selections. Pages with the switch:
Overview, Energy balance (`DashboardPage`), Metering chart and imports,
Metering points, Billing hub and invoices, Reports, Participants, Tariffs, ZEV
settings, and the owner audit log (not its `/admin` view). The invoice
detail page (the invoice's own community), My invoices and every `/admin/*`
page keep a plain eyebrow. The sidebar names no scope: it holds the logo, the
navigation and the account. On mobile, Escape closes the sidebar drawer and
returns focus to its menu button. Mobile navigation ignores the saved desktop
collapse preference. Returning to desktop restores it, closes the drawer and
releases the scroll lock; focus on a control that the breakpoint hides moves
to the visible equivalent (the drawer's menu button ↔ the sidebar's collapse
button). Focus elsewhere is preserved.
The shell's skip link, `main` landmark and focus after navigation follow
SPEC-2026-04 §7.1. The account disclosure is the sidebar's last control
(`.sidebar-footer .sidebar-user`; trigger with the name and the
up/down selector mark; panel `#user-menu-list` opens upward with the login's
email as its first line, then Account, the
language choices, Logout and, as its last line, the source-code link
`.user-menu-about` — GitHub mark, "OpenZEV" and the app version, opening in a
new tab). Opening it focuses the Account link; Escape closes it and returns
focus to the trigger; tabbing out or clicking outside closes it; its language
choices are ordinary buttons, and selecting a language leaves it open. Account
settings deliberately live behind the account row, not in the main navigation
(which stays about the community's work); on `/account` the trigger carries
`is-current` (the current nav row's pale forest), so the sidebar still shows
where the user is. In the collapsed rail the trigger shows only the selector
mark (the name as its tooltip) and expands the sidebar before opening. There is no account control in the page header: `header.top-nav`
holds only the mobile app bar (`.mobile-bar`, ≤768px: menu button plus the
decorative logo lockup, sticky) and, during impersonation, the impersonation
banner; on desktop it is empty otherwise.
My invoices, the one participant page that lists across
every membership, shows the community name only when the account has exactly
one membership (`soleCommunityName(user)`, from `/auth/me` `memberships`) and
otherwise names the broader scope (`pages.myInvoices.allCommunities`), so a
single name never mislabels it. The participant dashboard, statement page,
metering points and chart name the selected community, because they ask about
it (`zev_id`): `selectedCommunityName` (`frontend/src/lib/membership.ts`) takes
the readable ZEV record, else the selected switcher entry. Viewers get
`nav.relation.viewer` after the community name (`PageHeader` `scopeNote`),
whether or not the name is a switch; invoice detail uses the relation to
the invoice's own community. No other relation adds a note, and the note is not
part of the browser tab title.
The invoice detail page shows the invoice's own `zev_name` (a deep link may
land on an invoice of a different community than the global selection). The
owner audit-logs page follows the Setup convention (selected ZEV name); every
`/admin/*` page instead shows the platform label (`nav.platformScope`), so
platform headers never name a community and never a role.
Group labels (`nav.setupGroup`, `nav.platformGroup`) separate ZEV-scoped
entries from platform tooling; the operational links above Setup
(Overview, Energy balance, Metering, Billing, Reports) have no group heading.
Platform reuses `Overview` and `Settings`; its link accessible names include
the translated Platform group label (`nav.scopedLabel`: `{{scope}}: {{label}}`).
Tooltips appear only in the collapsed desktop rail; visible labels wrap.
There is no header or sidebar scope chip: every page header names its scope
in the eyebrow (the community, or "Platform administration" under
`/admin/*`), so the working context stays visible when the nav scrolls, the
sidebar collapses, or the sidebar lives in the mobile drawer.
The Manage action on `/admin/zevs` (`setSelectedZevId` + jump to `/`) is
how an admin enters a ZEV's working scope from platform scope.

Active navigation state is exposed to assistive tech: the active sidebar
entry carries `aria-current` alongside its visual class — `"page"` on the
exact route, `"true"` on hub entries visually active on sub-routes (Metering
on `/metering/chart` + `/metering/quality` + `/metering/imports`, Billing on
`/billing/*`).

The manager Overview uses period cards (`BillingPeriodsPage` and
`BillingPeriodCard`) plus `SetupGuidance` for first-run setup and warnings. It uses
`/api/v1/invoices/invoices/readiness/` and `…/attention/` — the contract is
documented in `2026-03-invoice-lifecycle-and-communication.md` §5.6a.

### 9.4 ManagedZevProvider (global community context)

`ManagedZevProvider` / `useManagedZev()` provide the selected community for
every page (`lib/managedZev.tsx`; the names were kept through #761).

**Behaviour:**
- `entries: CommunityEntry[]` (`{id, name, relation}`) from
  `communityEntries(user, zevs)`: an admin → every ZEV with relation `admin`;
  otherwise one entry per `user.memberships` item (`/auth/me`), its relation
  from `relationOf` in `lib/membership.ts` (the grant's `manager` / `viewer`,
  else `participant` while a participant row is live, else `former`).
- `managedZevs`: ZEV records — every ZEV for an admin, the ZEVs with a
  manager or viewer entry otherwise. The ZEV list is fetched for admins and
  grant holders.
- `selectedZev` is the record for the selection, `null` for a
  participant-only entry; `relation` is the selected entry's relation.
- `isSelectable`: an admin always; anyone else with more than one entry
  (`resolveCommunitySelection`).
- The selection is server-authoritative: the account's `User.preferred_zev`
  (saved on every switch) follows the user across browsers. No browser
  storage is used, so one account's choice cannot leak into another session.
- Resolution order: the session's explicit pick (if still listed) → the
  account's `preferred_zev` (if listed) → the first entry by name. The pick
  resets on every account change; until the user switches, the server
  preference wins.
- Switches apply optimistically; `AuthProvider.updatePreferredZev`
  serializes the `PATCH /auth/me/` saves per user so the latest choice wins,
  and session transitions prevent queued saves from dispatching and ignore
  late in-flight responses. A failed save keeps the local selection
  for the rest of the session.
- Before the community list loads, management memberships supply selection.
  Loaded records remove missing management entries; participant/former entries
  remain selectable without a readable ZEV record. Failed refreshes retain the
  cached selection.
- Exposes the ZEV query's loading/fetching/error state and a retry callback alongside
  the reconciled selection. Page behavior follows the
  [ScopeGuard contract](2026-04-frontend-management-page-design.md#41-shared-components).

**`useCommunityAccess()`** (`lib/communityAccess.ts`) turns the selected
relation into `{shellRole, isZevScope, canManage, canWriteSelectedCommunity,
isParticipantScope, isAdmin}`: `canManage` is role capability (`admin` and
`manager`); `canWriteSelectedCommunity` is the effective write availability
(role capability plus a resolved selected community permitting writes — a manager
keeps read access to a disabled ZEV but loses write access, an admin can
still write; a manager without a resolved community record cannot write). `viewer` only reads it (pages hide write controls);
`participant` and `former` get the participant view; without a relation the shell role is
`none`. `shellRoleForZev(user, zevId)` answers for a record's own community
(the invoice detail page). AuthProvider is required: provider errors propagate,
and missing auth never grants manager access. The outer authentication route
uses `useOptionalManagedZev()` before ManagedZevProvider mounts; without a
community relation, a non-admin gets `none`. The required `useManagedZev()`
hook still rejects a missing provider. Details: SPEC-2026-10-zev-access-grants §9.

---

## 10. API endpoint summary

### 10.1 Auth endpoints (`/api/v1/auth/`)

| Method | URL | Permission | Description |
|---|---|---|---|
| POST | `/token/` | AllowAny | JWT login (sets httpOnly cookies `openzev_access` / `openzev_refresh` + `csrftoken` via `get_token`; header `Authorization: Api-Key` is case-insensitive) |
| POST | `/token/mfa/` | AllowAny | Complete a two-factor login: `{mfa_token, code}` (TOTP or recovery code) → sets the same cookies as `/token/` |
| POST | `/passkeys/authenticate/begin/`, `/passkeys/authenticate/complete/` | AllowAny | Passwordless passkey sign-in (user verification required); sets the same cookies as `/token/` |
| POST | `/token/refresh/` | AllowAny | JWT refresh (reads `openzev_refresh` cookie; CSRF via `CookieJWTAuthentication` + `CsrfViewMiddleware`) |
| POST | `/register/` | AllowAny | Self-register an account that may set up a ZEV (`may_create_zev`) |
| POST | `/verify-email/` | AllowAny | Consume verification token, activate user |
| GET / PATCH | `/me/` | IsAuthenticated | View/update own profile |
| POST | `/me/change-password/` | IsAuthenticated | Change password (requires old password) |
| POST | `/me/set-initial-password/` | IsAuthenticated | Set password for first time (verification flow) |
| POST | `/me/email-change/` | IsAuthenticated | Ask for an email change; needs the current password; link goes to the new address (§5.6a) |
| POST | `/confirm-email-change/` | AllowAny (token) | Apply an emailed email-change link (§5.6a) |
| POST | `/me/sessions/revoke/` | IsAuthenticated | Sign out every other session (§5.6b) |
| POST | `/users/{id}/revoke-sessions/` | IsAdmin | Sign an account out everywhere (§5.6b) |
| GET / POST | `/users/` | IsAdmin | List users / Create user |
| GET / PATCH / DELETE | `/users/{id}/` | IsAdmin | User detail (delete blocked if linked, last admin, or a ZEV's last manager) |
| GET | `/me/mfa/` | IsAuthenticated | Own second-factor status: `{totp, passkeys, recovery_codes_remaining, required, grace_until}` |
| POST / DELETE | `/me/mfa/totp/` | IsAuthenticated | Begin TOTP enrolment (`{provisioning_uri, secret, qr_svg}`, `503` without `MFA_ENCRYPTION_KEYS`) / remove the device and its recovery codes |
| POST | `/me/mfa/totp/confirm/` | IsAuthenticated | `{code}` activates the device and returns ten recovery codes once |
| POST | `/me/mfa/recovery-codes/` | IsAuthenticated | Regenerate the recovery codes (returned once) |
| GET | `/me/passkeys/` | IsAuthenticated | Own passkeys (`id, name, aaguid, transports, created_at, last_used_at`) |
| POST | `/me/passkeys/register/begin/`, `/me/passkeys/register/complete/` | IsAuthenticated | Register a passkey (`{credential, name}`); the first factor also returns recovery codes once |
| PATCH / DELETE | `/me/passkeys/{id}/` | IsAuthenticated | Rename / remove own passkey (`409` if the role's policy would be left unmet) |
| DELETE | `/users/{id}/mfa/` | IsAdmin | Remove all of a user's second factors and recovery codes; audited as `auth.mfa.reset` |
| POST | `/users/{user_id}/impersonate/` | IsAuthenticated (admin only) | Impersonate participant/owner |
| GET / PATCH | `/app-settings/` | IsAuthenticated (update: admin only) | Application settings singleton: date formats for everyone, the two-factor policy `mfa_required` / `mfa_grace_period_days` for admins only (see `SPEC-2026-09-two-factor-authentication` §4.4) |
| GET | `/system-health/` | IsAuthenticated, IsAdmin | Platform health snapshot for the admin Overview hub's System-health tab: `{database: {status, engine, size_bytes}, celery: {status, workers_responding, queue_depth, broker_configured, detail?}, mfa: {status, encryption_key_configured}, email: {status, mode, backend}, backups: {status, destinations_enabled?, schedule_enabled?, last_successful_at?, age_hours?, stale?, encrypted?, encryption_required?, encryption_key_problem?}, checked_at}`. Best-effort probes: DB failure and zero responding workers are `degraded`; an unavailable broker ping or an unset `MFA_ENCRYPTION_KEYS` (ADR 0021, `SPEC-2026-09-two-factor-authentication` §4.5) is `unknown` — an expected state on an instance that hasn't opted into two-factor auth, not a fault. Email reports configuration only. The backups probe is `unknown` without an enabled destination or when its probe fails; it reports whether encryption is required and whether a configured key was rejected, so the health card distinguishes blocked creation from permitted plaintext backups. Broker connection and Redis socket timeouts are one second with connection retries disabled; worker replies have a one-second timeout. A dedicated Kombu mailbox publishes on that same connection without the application producer pool and with publication retries disabled. Redis depth uses passive queue declaration for the configured default queue, including its priority buckets. Optional `detail` contains only an exception class, never a raw exception message or broker credentials. |
| GET / POST | `/vat-rates/` | IsAdmin | VAT rate management |
| GET / PATCH / DELETE | `/vat-rates/{id}/` | IsAdmin | VAT rate detail |
| GET | `/feature-flags/` | IsAuthenticated, IsAdmin | List all feature flags (admin-only; syncs defaults on read) |
| PATCH | `/feature-flags/{id}/` | IsAuthenticated (admin only) | Toggle a feature flag |
| GET | `/registration-enabled/` | AllowAny | Public, minimal `{enabled: bool}` — self-registration status for the login page (no flag enumeration) |

### 10.2 ZEV endpoints (`/api/v1/zev/`)

| Method | URL | Permission | Description |
|---|---|---|---|
| GET / POST | `/zevs/` | IsAuthenticated, ZevManagementPermission (create: admin only) | List/create ZEVs |
| GET / PATCH / PUT / DELETE | `/zevs/{id}/` | IsAuthenticated, ZevManagementPermission (delete: admin only; write on a disabled ZEV: admin only) | ZEV detail (retrieve uses ZevDetailSerializer with nested participants) |
| POST | `/zevs/create-with-owner/` | IsAuthenticated, ZevManagementPermission (admin only) | Wizard: create ZEV + owner + metering points |
| POST | `/zevs/self-setup/` | IsAuthenticated | Self-setup: create ZEV for self-registered owner |
| POST | `/zevs/{id}/disable/` | IsAuthenticated, ZevDisablePermission (owner of that ZEV, or admin) | Disable a ZEV — reversible, touches nothing else (§7.1a) |
| POST | `/zevs/{id}/enable/` | IsAuthenticated, IsAdmin | Re-enable a disabled ZEV — admin only (§7.1a) |
| POST | `/zevs/{id}/purge/` | IsAuthenticated, IsAdmin | Permanently delete a disabled ZEV and everything under it — irreversible, admin only (§7.1b) |
| GET | `/grid-operators/` | IsAuthenticated | The official ElCom grid-operator list for the ZEV form picker — static reference data, **unpaginated** (see §3.4a) |
| GET / POST | `/participants/` | IsAuthenticated, BaseZevScopedPermission | List/create participants |
| GET / PATCH / PUT / DELETE | `/participants/{id}/` | IsAuthenticated, BaseZevScopedPermission | Participant detail |
| POST | `/participants/{id}/send-invitation/` | admin or `can_manage` | Send invitation email |
| GET | `/participants/{id}/contract-pdf/` | IsAuthenticated | Read the issued participation contract (404 before the first issuance; never mints) |
| POST | `/participants/{id}/contract-pdf/` | IsAuthenticated | Issue the participation contract (issues or reuses the persisted versioned snapshot) |
| POST | `/participants/{id}/link-account/` | admin only | Link user account to participant |
| POST | `/participants/{id}/unlink-account/` | admin only | Unlink user account from participant |
| POST | `/participants/{id}/create-account/` | admin only | Create + link user account |
| GET / POST / PATCH / DELETE | `/parties/`, `/parties/{id}/` | IsAuthenticated, BaseZevScopedPermission (viewers read, managers write; no participant link) | A ZEV's parties with their participations and current roles; delete only while unused (SPEC-2026-10-zev-parties §5.2) |
| GET / POST | `/party-roles/`, `/party-roles/{id}/` | IsAuthenticated, BaseZevScopedPermission (viewers read, managers write; no participant link) | Current and future roles (`?include_ended=true` adds the history); POST assigns a role from a date (§5.3) |
| POST | `/party-roles/{id}/end/` | IsAuthenticated, BaseZevScopedPermission (managers) | End a role on `last_day`; 204 when that removed a role that had not started |
| GET / POST | `/metering-points/` | IsAuthenticated, MeteringPointPermission | List/create metering points |
| GET / PATCH / PUT / DELETE | `/metering-points/{id}/` | IsAuthenticated, MeteringPointPermission | Metering point detail |
| GET / POST | `/metering-point-assignments/` | IsAuthenticated, MeteringPointAssignmentPermission | List/create assignments |
| GET / PATCH / PUT / DELETE | `/metering-point-assignments/{id}/` | IsAuthenticated, MeteringPointAssignmentPermission | Assignment detail |

---

## 11. Queryset scoping matrix

All domain viewsets enforce tenant scoping at the queryset level. This is the
backend's primary access control mechanism.

Columns: "grant" = an active manager or viewer grant on the row's ZEV (reads;
writes need a manager grant, §4.4); "participant link" = the caller's own
current participant row (ended rows count only where noted). An account gets
the union of the columns it holds. Rows of a disabled ZEV stay visible through
a grant and disappear through a participant link.

| Resource | admin | grant on the ZEV | participant link | nothing |
|---|---|---|---|---|
| Zev | all | the ZEV | — (never through a link) | PermissionDenied |
| Participant | all | all of the ZEV's | own row (list only; the permission class refuses participant detail reads) | PermissionDenied |
| MeteringPoint | all | all of the ZEV's | meters assigned to the own row | empty list |
| MeteringPointAssignment | all | all of the ZEV's | own assignments | PermissionDenied |
| Tariff / TariffPeriod | all | all of the ZEV's | — | PermissionDenied |
| User (list) | all (`IsAdmin`) | PermissionDenied | PermissionDenied | PermissionDenied |
| ImportLog | all | read: all of the ZEV's, plus logs the caller imported; delete: logs of managed ZEVs (and own logs without a ZEV) | PermissionDenied | PermissionDenied |
| MeterReading | all | all of the ZEV's | raw/chart readings only within own assignment dates (civil day); CRUD routes denied | PermissionDenied |
| Invoice | all | all of the ZEV's | own invoices once sent (`sent_at` set or status `sent`/`paid`; #861), also after the row has ended | empty list |
| AuditEvent | all | events of the ZEV | — | PermissionDenied |

An account with no grant and no participant link passes no management gate
(403) and sees empty metering-point and invoice lists.

For participant raw/chart metering access, the assignment's meter and linked
user must match the reading and caller, and its inclusive validity window
must contain the reading's UTC civil date. A null assignment end is
open-ended; gaps and other holders' periods remain hidden even when the caller
held the same meter before or after them. The query uses a correlated
assignment `Exists` check so returning holders' readings are not duplicated
in aggregates. See the [metering spec §6.1](2026-03-metering-import-and-quality.md#61-readings-queryset-scoping)
and its `metering/test_reading_visibility.py` regression coverage.

---

## 12. RBAC endpoint access matrix (tested)

The `RbacEndpointMatrixTests` test class verifies this matrix. Since #761 the
columns are relations, not roles: *owner* is a `user` account managing the ZEV
(it owns it, so it holds a manager grant), *participant* a `user` account
linked to a participant row, *guest* a `user` account with no relation.

### 12.1 List endpoints

| Endpoint | admin | owner | participant | guest |
|---|---|---|---|---|
| `/api/v1/zev/zevs/` | 200 | 200 | 403 | 403 |
| `/api/v1/zev/participants/` | 200 | 200 | 403 | 403 |
| `/api/v1/zev/metering-points/` | 200 | 200 | 200 | 200 |
| `/api/v1/zev/metering-point-assignments/` | 200 | 200 | 403 | 403 |
| `/api/v1/tariffs/tariffs/` | 200 | 200 | 403 | 403 |
| `/api/v1/metering/readings/` | 200 | 200 | 403 | 403 |
| `/api/v1/invoices/invoices/` | 200 | 200 | 200 | 200 |

### 12.2 Create endpoints

| Endpoint | admin | owner | participant | guest |
|---|---|---|---|---|
| `/api/v1/zev/zevs/` | 201 | 403 | 403 | 403 |
| `/api/v1/zev/metering-points/` | 201 | 201 | 403 | 403 |
| `/api/v1/tariffs/tariffs/` | 201 | 201 | 403 | 403 |

### 12.3 Update endpoints

| Endpoint | admin | owner | participant | guest |
|---|---|---|---|---|
| `/api/v1/zev/participants/{id}/` (PATCH) | 200 | 200 | 403 | 403 |

### 12.4 Invoice dashboard

| Endpoint | admin | owner | participant | guest |
|---|---|---|---|---|
| `/api/v1/invoices/invoices/dashboard/` | 200 | 403 | 403 | 403 |

### 12.5 Unauthenticated access

All API endpoints return 401 for unauthenticated requests.

---

## 13. Serialization

### 13.1 UserSerializer

**Fields:** `id`, `username`, `email`, `first_name`, `last_name`, `role`,
`must_change_password`, `is_active`, `date_joined`, `preferred_zev` (ZEV
UUID or `null`; always present in responses, `null` when unset — the
frontend types it as required-nullable).
**Read-only:** `id`, `date_joined`.

**Role-change validation:**
- Admin cannot change own role (from admin to anything else).
- Non-admin cannot change any role at all.

**`preferred_zev` validation:** a community the account belongs to — one it
can view (admin: any; a grant) or holds a current or past participant row in.
`null` clears the preference.

### 13.1a AdminUserSerializer

Subclass of `UserSerializer` used by `GET /auth/users/` only. Adds the
read-only `memberships` and `mfa_methods` fields described in §6.1. Not used on
create (`UserCreateSerializer`) or detail/update (`UserSerializer`).

### 13.2 UserCreateSerializer

**Fields:** `username`, `email`, `first_name`, `last_name`, `password`,
`password2`, `role`.
**Validation:** passwords must match; password validated via Django validators.

### 13.3 ParticipantSerializer

**Fields:** `id`, `zev`, `user`, `party` (write on create: attach to an
existing party; a participation cannot move to another party), the party's
fields written through — `kind`, `title`, `first_name`, `last_name`,
`organisation_name`, `name_addition`, `email`, `phone`, `address_line1`,
`address_line2`, `postal_code`, `city` — `valid_from`, `valid_to`, `notes`,
`allocation_weight`, `created_at`, `updated_at`, plus computed:
- `account_username` (read-only, from linked user)
- `initial_password` (read-only, only present when account is first created)
- `full_name`, `display_name` (read-only, the party's display name)
- `roles` (read-only, the party's roles active today or later:
  `[{id, role, valid_from, valid_to}]`, from the `party__roles` prefetch)
- `metering_points` (read-only, nested `MeteringPointSerializer`)
- `has_metering_point_assignment` (read-only, boolean)

**Validation:**
- `user` field cannot be set directly ("Participant accounts are created
  automatically.").
- `email` is required (even though the model allows blank).
- A person needs `last_name`, an organisation `organisation_name`.
- A non-admin may not edit a row whose account has its own login (§8.2).

### 13.4 ZevSerializer / ZevDetailSerializer

`ZevSerializer`: all model fields. Owner assignment defaults to `request.user`.
Owner validation: non-admin cannot assign a different owner.

`ZevDetailSerializer`: extends `ZevSerializer`, adds nested `participants`
(ParticipantSerializer, many=True, read-only).

### 13.5 ZevCreateWithOwnerSerializer

Composite serializer for the creation wizard. Nested:
- `owner`: `ZevOwnerAccountSerializer` (username, name, contact details)
- `metering_points`: `OwnerMeteringPointInputSerializer[]` (min_length=1)

Optional scalar fields include `bank_iban` (max 34) and the informational
`bank_name` (max 200), both `required=False, allow_blank=True` — the wizard
collects them with the responsible person's details on step 2 (see §7.2).
Self-setup goes through `ZevSerializer`
(all model fields), so the same optional bank fields are accepted there.

### 13.6 CustomTokenObtainPairSerializer

`CustomTokenObtainPairSerializer` has its own `get_token` with the same claims as helper `_make_jwt_for_user(user) -> dict` (used by `verify_email`/`set_initial_password` and `views_oauth`/`impersonation`): `role`, `email`, `full_name`, `must_change_password`.

---

## 14. Frontend TypeScript types

Key types in `frontend/src/types/api.ts`:

```typescript
type UserRole = 'admin' | 'user'

interface User {
    id: number; username: string; email: string;
    first_name: string; last_name: string;
    role: UserRole; must_change_password: boolean;
}

interface AuthTokens { access: string; refresh: string }
interface ImpersonationTokens extends AuthTokens {
    impersonated_user: User; impersonator: User
}

interface RegisterInput { username: string; email: string }
interface SelfSetupZevInput { name: string; start_date: string; zev_type: 'zev'|'vzev'; billing_interval: string; grid_operator?: string; grid_operator_elcom_id?: number|null; bank_name?: string; bank_iban?: string; owner_address_line1?: string; owner_address_line2?: string; owner_postal_code?: string; owner_city?: string }

interface Zev { id: string; name: string; owner: number; /* + many fields */ }
interface ZevInput { name: string; start_date: string; owner?: number; zev_type: 'zev'|'vzev'; billing_interval: string; /* + optional fields */ }
interface ZevWizardInput extends Omit<ZevInput, 'owner'> {
    owner: ZevOwnerInput; metering_points: OwnerMeteringPointInput[]
}
interface ZevWizardResult { zev: {id, name}; owner: {id, username, temporary_password}; owner_participant_id: string; metering_points: {id, meter_id}[] }

interface Participant { id: string; zev: string; user: number|null; /* + contacts, validity, metering_points */ }
interface ParticipantAccountCreateResult { participant: Participant; account: User; temporary_password: string }
```

---

## 15. Django admin

### 15.1 accounts admin

| Model | Admin class | Key config |
|---|---|---|
| `User` | `CustomUserAdmin` | Extends `UserAdmin`; adds `role`, `must_change_password` fieldset. List display: username, email, name, role, is_active. Filter: role, is_active, is_staff. |
| `AppSettings` | `AppSettingsAdmin` | List: date formats + updated_at |
| `VatRate` | `VatRateAdmin` | List: rate, valid_from, valid_to, updated_at. Ordering: `-valid_from`, `-created_at` |

### 15.2 zev admin

| Model | Admin class | Key config |
|---|---|---|
| `Zev` | `ZevAdmin` | ParticipantInline. List: name, zev_type, owner, billing_interval, disabled_at. Filter: zev_type, billing_interval, disabled_at. Search: name, grid_operator |
| `Participant` | `ParticipantAdmin` | MeteringPointAssignmentInline. List: full_name, zev, email, validity. Filter: zev. Search: name, email |
| `MeteringPoint` | `MeteringPointAdmin` | List: meter_id, zev, meter_type, is_active. Filter: meter_type, is_active. Search: meter_id |

---

## 16. Test plan

### 16.1 Backend test classes

Line counts are not tracked here — they drift with every change. The inventory
lists the test classes per module (test counts are the `test_*` methods).

**`accounts/tests.py`** (18 test classes):

| Class | Tests | Description |
|---|---|---|
| `UserModelTests` | 3 | Role helper properties; superuser creation sets `role=ADMIN`; superuser creation rejects non-admin role |
| `PasswordChangeFlagTests` | 1 | `must_change_password` cleared on password change |
| `TokenLoginCredentialTests` | 1 | Email login issues httpOnly cookie JWTs instead of a response body token |
| `PasswordLoginAuditTests` | 5 | Successful login records `auth.login` with the user as actor and target; wrong password, unknown username, and inactive account each record `auth.login_failed` (status `failed`, no actor) with the attempted identifier in `target_display`; a request with no identifier is still audited |
| `RegistrationTests` | 33 | Email-only signup and validation, including rejection above the model email length limit before issuance and acceptance at the limit; uniform response; pending-registration resend rules (invitation, verified/disabled and active accounts excluded); per-address reservation and release; retry after a mail failure; username-collision retry; explicit inactive-signup cancellation and full admin-form edit preservation; atomic initial issuance, delivery/cleanup failure handling and cache outages; verification payload types/length and active-account refusal; template fallback; disabled registration |
| `FeatureFlagsApiTests` | 5 | Anonymous 401 and non-admin 403 on list; admin can list and toggle; defaults sync on read |
| `ImpersonationTests` | 4 | Admin can impersonate participant/owner; non-admin blocked; admin cannot impersonate admin |
| `LinkedAccountSafetyTests` | 8 | Admin can edit linked account; cannot delete linked; can delete unlinked; cannot delete last admin (with audit-denied assertion); can delete self when other admin exists (with audit actor SET_NULL assertion); can delete other admin when multiple exist; cannot change own role (via both detail and me endpoints) |
| `MeEndpointParticipantContextTests` | 5 | `GET /auth/me/` lists a participant's community in `memberships` and carries no `zev_name` / `zev_count`; the membership carries the community's `zev_billing_interval`; an admin and an account without a community get `[]`; two memberships are both listed, by name |
| `AppSettingsTests` | 5 | Authenticated user reads settings; non-admin read omits the MFA policy, admin read includes it; admin updates; non-admin cannot update |
| `VatRateSettingsTests` | 4 | Admin CRUD; non-admin blocked; overlap rejection; valid_to validation |
| `OAuthProviderConfigTests` | 7 | Production token/userinfo HTTPS and malformed URL validation; admin creates provider (internal host URLs, scheme-less URLs, default redirect URL); non-admin blocked; login initiate uses provider redirect URL |
| `OAuthProviderSecretWriteOnlyTests` | 5 | `client_secret` is write-only: create/list/detail responses never contain it and report `has_client_secret`; create without a secret is refused; blank secret on update keeps the stored value; new secret on update rotates it |
| `UserListCreateAdminOnlyTests` | 6 | Owner/participant/anonymous cannot list or create users; admin can list all users and create |
| `RbacEndpointMatrixTests` | 6 | Full list/create/update/action-delete/unauthenticated matrix across all endpoints |
| `OAuthTokenCleanupTaskTests` | 1 | Token cleanup task keeps active and removes expired entries |
| `PreferredZevApiTests` | 7 | Account-level default community (`preferred_zev`) on `/auth/me/`: none by default; an owner sets one of their own, cannot prefer another owner's or an unknown ZEV, and clears it back to first-by-name; a participant is refused; an admin may prefer any community |

**Other `accounts/` test modules** (class counts exclude helpers and fixture-only bases):

| Module | Classes | Tests | Coverage |
|---|---|---|---|
| `test_session_hardening.py` | 6 | 55 | Self-service profile lockdown (protected fields rejected, repeats accepted, names/preferred community still editable); session revocation (revoked/new/legacy tokens, dead access cookie leaves public endpoints working, refresh refusal, deactivation, stale-instance save cannot revive, API keys and impersonation); password change and revoke endpoints; verified email change (request/confirm, single-use, dies on password/address/deactivation/expiry, no enumeration, throttle, mail failure, API keys) |
| `test_security_notifications.py` | 5 | 26 | Every event composes (subject, body, `{detail}` filled, admin vs. self advice, no-turn-off line); guards (no address, inactive, gone/deactivated by send time); hooked into passkey add/remove, TOTP enable/disable (not for an abandoned enrolment), recovery-code regeneration, password change (not on failure), admin MFA reset (not when nothing was removed) and admin session revocation (not for the self-service one); a broker or mail failure never fails the triggering request |
| `test_admin_users_list.py` | 2 | 13 | Admin user list: memberships per relationship (participant, owner-who-is-also-participant merged into one, owner of several communities sorted by name), confirmed-only `mfa_methods`, `last_login` exposed and `null` before the first sign-in, fixed query count, `/auth/me/` unaffected; `mfa_compliance` (`null` outside the policy, `"grace"` before the deadline, `"overdue"` after it, `"compliant"` once enrolled regardless of the deadline, no added query per account) |
| `test_last_login.py` | 4 | 7 | `last_login` stamped by a plain password login (not by a failed one, not by the password step of a two-step login until `/token/mfa/` completes it) and by the auto-login after email verification; not restamped by a password change or by setting your initial password moments after verifying; untouched on either side of an impersonation session |
| `test_admin_account_actions.py` | 2 | 12 | Account creation (generated password when omitted, returned once and never re-listed, two accounts get different passwords, a supplied password is still accepted, mismatched/weak supplied passwords rejected, generated password passes the validators anyway, response carries the new id, non-admin blocked); self-deactivation guard (blocked with a field error, deactivating someone else works and is audited, reactivating your own account is unaffected, deactivating someone else still revokes their sessions) |
| `test_api_keys.py` | 10 | 81 | Generation, hashing, auth, read-only keys, scope deny-list, audit, throttling, CRUD, admin management |
| `test_oauth.py` | 12 | 72 | Public endpoint validation, bounded JSON object responses, access-token/profile field types and model limits, numeric fallback IDs and linked login without email, redirect/credential containment, verified-email provisioning and linking, admin-only audited exception for trusted providers with an absent claim (new accounts only); provider listing, initiate, callback guards/redirects, link flow, social accounts, audit, `require_mfa_claim` (`OAuthMfaClaimTests`) |
| `test_passkeys.py` | 8 | 64 | Passkey registration and passwordless sign-in against a software authenticator, MFA policy and grace arithmetic, removal guard, admin reset, RP-ID/origin system checks |
| `test_mfa.py` | 4 | 28 | TOTP enrolment/removal/recovery codes, two-step login, MFA at the magic-link/onboarding/OAuth/impersonation/email-verification doors, per-account throttle (`SPEC-2026-09-two-factor-authentication`) |
| `test_registration_concurrency.py` | — (3 functions) | 7 cases | PostgreSQL cancellation/verification/resend row-lock ordering; SMTP outside transactions; transitions during delivery; late cleanup preserves newer links |
| `test_cookie_oauth.py` | — (7 module-level test functions) | 7 | Refresh/logout cookie handling; token exchange sets cookies, consumes codes, and stamps `last_login` |
| `test_impersonation.py` | 5 | 22 | Permissions, audit, cookie round-trip, stop-impersonation |
| `test_throttling.py` | 4 | 15 | Per-IP 429 boundaries for all six public auth write endpoints; budgets are independent; production settings wiring and spoofed `X-Forwarded-For` regression coverage; headers neither evade the login bucket without a trusted proxy nor escape the right-most-entry bucket with one trusted hop |

**`config/test_settings_guards.py`** (4 test classes, 22 tests):

| Class | Tests | Description |
|---|---:|---|
| `ValidateSecretKeyTests` | 4 | Rejects empty and placeholder production keys while allowing them in development |
| `ProductionHostsCheckTests` | 11 | Rejects unsafe hosts and frontend origins; accepts a complete production configuration; preserves distinct system-check IDs |
| `ProductionConfigurationCheckTests` / `SeedDemoGuardTests` | 7 | Rejects empty/insecure CSRF origins, console or incomplete SMTP mail, and empty WebAuthn settings; refuses demo seeding in production |

**`zev/tests.py`** (32 test classes):

| Class | Tests | Description |
|---|---|---|
| `ZevPaymentTermTests` | 4 | Payment term default (30 days), range validation, API accept/reject |
| `ParticipantEndpointRestrictionTests` | 7 | Participant cannot access ZEV/participant lists; can list own metering points; cannot create/update/delete metering points; cannot access assignments |
| `ZevCreationWizardTests` | 6 | Non-admin cannot create ZEV; admin wizard rejects an invalid IBAN and an IBAN without the owner address; creates ZEV + owner + participant + assignments keeping the ZEV's own postal code apart from the owner's; payload persists normalized `bank_iban` + `bank_name` |
| `ZevSelfSetupTests` | 3 | Self-setup persists `bank_iban` + `bank_name` on the created ZEV (owner participant created); an IBAN without the required owner address is rejected without creating the ZEV; falsy-but-valid JSON address values reach serializer validation without being replaced as missing |
| `ParticipantAccountLifecycleTests` | 3 | Create participant auto-creates account with initial password; update saves contact details; invitation resets password and sends email |
| `AdminCanEditOwnerParticipantTests` | 4 | `test_admin_can_edit_the_owner_participant_address` preserves the owner role and ZEV API access; `test_profile_sync_preserves_privileged_roles` synchronizes name/email while preserving owner/admin roles and ZEV API access; `test_onboarding_link_leaves_roles_alone_and_keeps_privileged_logins` leaves every role unchanged (#761), keeps the login of an admin, a self-registered account and a grant holder and neutralises it for a plain account, and verifies email delivery; `test_zev_owner_cannot_edit_their_own_owner_participant_record` retains the edit restriction (now: a non-admin may not edit a participant row whose account has its own login) |
| `ParticipantAccountLinkingTests` | 8 | Admin can link/unlink accounts (unlink leaves the role); an account may hold several participant rows; an admin account cannot be linked; admin can create-and-link; non-admin cannot link/create |
| `ZevOwnerRoleSyncTests` | 1 | Owner transfer promotes new owner, demotes previous |
| `MeteringPointAssignmentValidationTests` | 9 | Unique assignment, no overlaps, historical OK, open-end blocks future, dates within participant window, self-update OK |
| `AssignmentSaveOverlapGuardTests` | 5 | Overlap guard on save path |
| `SeedDemoAssignmentReseedTests` | 1 | Demo seed re-creates assignments |
| `SeedDemoSecondCommunityTests` | 5 | ZEV upsert is idempotent and refreshes config drift; legacy flagship name is renamed, not duplicated; other-owner legacy names untouched; each community carries the config its name implies; previous-month helper returns the complete prior month |
| `SeedDemoSecondCommunitySeedTests` | 2 | Second community seeds a closed and an open month; re-seeding the second community is idempotent |
| `SeedDemoQualityGapTests` | 2 | Deliberate quality gap deletes only the recent reading window; skipped when the period is too young |
| `SeedDemoVatRateTests` | 6 | Swiss VAT history install; idempotent re-run; foreign rates untouched; admin-edited canonical row kept; overlapping custom dates preserved; demo helper is a no-op on migration-seeded rows (class starts empty except the no-op test, which seeds via the real migration function) |
| `SeedDemoCounterRefreshTests` | 2 | Re-seed resets the invoice counter; re-seed keeps the contract counter |
| `SeedDemoHourlyHistoryTests` | 3 | History fills hourly up to the window; an hourly row sums the four quarter samples it replaces; skipped when the window precedes history |
| `SeedDemoReadingResolutionTests` | 3 | Window is hourly until the fine 15-minute tail; last hourly row sums its quarter samples; short windows stay entirely 15-minute |
| `SeedDemoInvoiceSettlementTests` | 2 | Closed run marks every invoice paid and the last cancelled; settlement survives a re-seed |
| `MeteringPointReadingsDeletionTests` | 8 | Admin whole-meter and inclusive-range deletion; string/omitted false values stay bounded; invalid booleans and invalid/incomplete/reversed ranges return 400 without writes; non-admin denied |
| `NextInvoiceNumberTests` | 3 | Invoice number allocation |
| `SeedDemoPeriodHelpersTests` | 6 | Demo seed period helpers |
| `SeedDemoTariffVersionTests` | 11 | Demo seed tariff versioning |
| `SeedDemoLegacyNameCollisionTests` | 5 | Legacy row next to an already-migrated row dropped; duplicate legacy rows keep the newest; a duplicate legacy row with invoices is cleared; current-name upsert does not take over another owner's community; only the demo owner is affected |
| `SeedDemoWindowShiftTests` | 1 | Shifted seed window leaves no readings outside it |
| `SeedDemoAuditResetTests` | 1 | Audit reset clears demo trails but keeps events on other communities |
| `SeedDemoReseedTests` | 1 | One seeded-then-re-seeded database (seeded once in `setUpTestData`), checked as four sub-tests of a single test so `--dist=worksteal` cannot split the class and repeat the seed per worker: Anna's invoice PDFs generated after commit, deterministic reseeding, the flagship's representative and contact, access personas |
| `SeedDemoEndToEndTests` | 7 | Seed runs that need their own database: dynamic tariff rollover on a next-quarter reseed; real-storage PDF lifecycle across a reseed; rollback preserves invoice rows/files; cleanup preserves referenced PDFs; rendering/database and deletion failures are isolated within and between commit callbacks |
| `ZevVatModeTests` | 5 | ZEV VAT mode: default `not_registered`; `clean()` requires a number for `registered` and forbids one otherwise; a PATCH to `inclusive` is accepted and to `registered` without a number rejected |
| `SeedDemoFeatureFlagTests` | 3 | Demo seed enables the features that ship off by default (#691): enables the feasibility-calculator flag, re-enables a flag an admin turned off, and is idempotent |
| `MeteringPointCascadeInfoTests` | 3 | Metering-point list/retrieve/create responses report cascade counts (`reading_count`, `assignment_count`) and the first/last reading span |
| `MeteringPointBehindMeterGenerationTests` | 4 | Behind-the-meter generation flag (SPEC-2026-behind-the-meter-generation): defaults false, allowed on bidirectional/production meters, rejected on consumption (including via PATCH) |
| `AllocationModelAndApiTests` | 6 | Shared-metering-point allocation (SPEC-2026-08-shared-metering-points): `allocation_mode`/`allocation_weight` model defaults and API round-trip, zero/negative weight rejected, both exposed in the serializers |

The second demo community's reading wipe in `seed_demo._seed_second_community`
filters `MeterReading.metering_point` through a `MeteringPoint` subquery scoped to
that ZEV. This avoids a readings self-join in the generated `DELETE`, which can
become a costly nested loop on PostgreSQL when test fixtures are uncommitted and
table statistics estimate an empty readings table. The wipe still removes all
prior readings for that community, including rows outside the new seed window.

**Other `zev/` test modules:**

| Module | Classes | Tests | Coverage |
|---|---|---|---|
| `test_scoping.py` | 1 | 4 | `ZevScopedQuerySetMixin` read scoping (admin, grant, participant link, manager-only resource) |
| `test_access_regression.py` | 2 | 17 | #761: pins what an account with one relationship sees and may change (lists, cross-ZEV detail, reports, dashboard, statements, MCP, main writes); unchanged by the per-ZEV rewrite |
| `test_access.py` | 4 | 24 | #761: `ZevAccessGrant` model, `zev.access` helpers, owner-grant invariant, migration 0031 (SPEC-2026-10-zev-access-grants §13) |
| `test_access_api.py` | 3 | 25 | #761 step 5: the grant API (`/zev/zevs/{id}/access/`: list, give, change, revoke, last-manager rule, audit), email invitations (inactive account, 7-day link, accept via verify-email, resend, revoke, failed send, templates), `/auth/me` memberships, `may_create_zev`, grant holders' logins protected |
| `test_access_scoping.py` | 4 | 14 | #761: viewers read what managers read and write nothing (`ViewerWriteRouterWalkTests` tries every unsafe route); accounts with several relationships get the union; former participants keep sent invoices only |
| `test_write_scoping.py` | 5 | 19 | Write scoping: foreign create refused, move-via-PATCH refused, legit writes and admin bypass still work, audit retained; DELETE on a ZEV is `405` for every role, since the only supported removal path is disable then purge |
| `test_disable_enable.py` | 4 | 17 | ZEV lifecycle phase 1: owner/admin can disable, only admin can enable, both audited, guarded against double-disable/double-enable; a disabled ZEV is read-only to its owner (admin can still write); the self-setup "already have a ZEV" guard excludes disabled ZEVs |
| `test_disabled_zev_scoping.py` | 5 | 27 | ZEV lifecycle phase 2 (§7.1a): creating into a disabled ZEV refused for every `scope_parent_path` model, admin exempt; PATCH/DELETE on an existing `Participant`/`MeteringPoint`/`MeteringPointAssignment` row blocked for the owner, admin exempt, reads unaffected; PATCH/DELETE on an existing `Tariff`/`TariffPeriod`/`MeterReading` row blocked the same way via `assert_target_not_disabled`, including a field unrelated to the ZEV relation (which `assert_within_scope` alone would miss); a participant loses read access to metering points, invoices and readings under a disabled ZEV while the owner keeps it; access returns in full after `enable` |
| `test_purge.py` | 3 | 8 | ZEV lifecycle phase 4 (§7.1b): refuses an active ZEV; a full purge deletes the ZEV and every `CASCADE` child (including both `PROTECT` relations, `Invoice` and `ExportJob`) and removes their media files from storage; `SET_NULL` rows (`AuditEvent`, `ContractIssue`, `BackupJob`) survive with their ZEV link cleared; the endpoint is admin-only, requires the exact ZEV name, refuses an active ZEV, and is audited |
| `test_zev_id_filter.py` | 5 | 15 | `?zev_id=` narrowing on list endpoints |
| `test_transfer.py` | 11 | 92 | Whole-ZEV archive shape, round-trip, rejected archives, schema parity, transfer endpoints, percentage-band/dynamic-source/party/building sections |
| `test_geocoding.py` | 5 | 24 | Building footprint cache, warm tasks for buildings, trigger-on-save dispatches after the surrounding transaction commits, feature flag |
| `test_iban.py` | 4 | 13 | `normalize_iban`/`is_valid_iban` vectors plus shared recipient-address validation: whitespace/case normalization, MOD-97 accept/reject, blank-means-absent, and required address completeness when an IBAN is configured |

### 16.2 Frontend

- `npm run build` checks TypeScript and the production build. Route tests
  verify access and redirects.
- `ProtectedRoute` handles loading, unauthenticated, forced password change,
  redirects for accounts without community access, and shell-role gating.
- `frontend/tests/layout-nav.test.ts` — role navigation, scoped link names,
  the account row's name, the email in the account panel, active state (including the account row on `/account`),
  no scope in the sidebar, the account panel's keyboard behaviour and source
  link, and mobile presentation independent of desktop collapse.
- `frontend/tests/community-switcher.test.ts` — the scope-line community
  switch: list, current mark, relation labels, plain-text fallbacks, the
  dirty-draft confirmation and fixed selections.
- `frontend/screenshots/layout-overflow.spec.ts` — the community menu's
  scrolling and placement across viewport sizes, and focus recovery across
  the mobile breakpoint with browser CSS applied.
- `frontend/tests/nav-labels.test.ts` — distinct labels within community,
  platform and participant navigation plus the charts-tab-vs-hub guard, in
  all four locales.
- `frontend/tests/route-guard-matrix.test.ts` — the §9.2 matrix for all six
  shell roles, denial before rendering for accounts without community access,
  public routes without a session, and
  forced-password access including trailing-slash account URLs.
- `frontend/tests/route-aliases.test.ts` — legacy alias redirects preserve
  query and params (the §9.2 matrix is the frozen contract).
- `frontend/tests/managed-zev-selection.test.ts` (28 tests) — the §9.4
  resolution order (explicit pick → account preference → first managed),
  optimistic switches, failed-save tolerance, and account-switch isolation
  (no cross-account leakage). `frontend/tests/auth-preferred-zev.test.ts`
  (3 tests) — serialized `updatePreferredZev` saves (latest wins), logout
  invalidation of late responses, and cancellation of queued dispatches
  across session transitions. `frontend/tests/auth-preferred-zev.test.ts`'s
  second suite (5 tests) — the §5.7a query cache reset on login, logout, and
  each impersonation edge, plus a delayed-response race: a query already in
  flight for the outgoing account must not repopulate the cache after the
  switch.
- `frontend/tests/zev-create-wizard.test.ts` (8 tests) — the admin creation
  wizard sends `bank_iban` + `bank_name` to `createZevWithOwner` (echoed on the
  step-4 review) and `""` for both when left blank (review shows `–`); rejects
  an invalid IBAN and an IBAN without recipient address on step 2; on step 3
  keeps typed meter IDs when advancing, deletes the right row, flags only the
  row without a meter ID (all rows stay visible), and rejects a duplicate
  meter ID.
- `frontend/tests/verify-email-self-setup.test.ts` — the verify-email
  self-setup card sends `bank_iban` + `bank_name` with `createSelfSetupZev`
  and sends `""` when left blank (no client-side required).

---

## 17. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope leakage across ZEV boundaries | High | Backend queryset scoping per role; `BaseZevScopedPermission` object-level checks; regression test matrix |
| UI-only enforcement drift | High | Backend always enforces permissions; frontend guards are UX convenience only (ADR 0003) |
| Assignment validity edge cases | Medium | Date-boundary tests; serializer + model double validation; ADR 0001 rules |
| Impersonation abuse | High | Admin-only guard; cannot impersonate other admins; impersonation state tracked in JWT claims and `ADMIN_*` backup cookies |
| Query cache leaking one account's data to the next in the same tab | High | §5.7a `resetQueryCache()` cancels in-flight queries and clears the cache at every login/logout/impersonation boundary (openzev#573) |
| Self-registration spam | Medium | Email verification required; unusable password until verified |
| Linked account deletion | Medium | Delete blocked if `participations.exists()`; `SET_NULL` FK prevents cascade |

---

## 18. Acceptance criteria

1. User model has the platform role `admin` or `user` with
   a correct `is_admin` computed property; managing a ZEV is a per-ZEV grant
   (`zev.access`, #761).
2. JWT tokens embed `role`, `email`, `full_name`, `must_change_password`.
3. Self-registration creates an inactive `user` with `may_create_zev`, sends verification email,
   and auto-logs in on verification.
4. `must_change_password` flag redirects to profile; cleared on password change
   or set-initial-password.
5. Admin can impersonate any active non-admin account, never another admin.
6. All domain viewsets scope querysets by role and ZEV ownership.
7. `BaseZevScopedPermission` enforces object-level ZEV ownership checks.
8. Participant creation auto-provisions a linked user account with temporary
   password.
9. Account linking is admin-only and is done from the community's
   **Participants** page (link any existing non-admin account, or unlink —
   the account's role is unchanged); the admin accounts page only *lists*
   memberships and links out to that page. Delete is blocked for accounts that
   belong to a community and for the last admin. `create_superuser` enforces
   `role=ADMIN`, so the `role` column is the canonical admin count.
10. ZEV creation wizard atomically creates ZEV + owner user + owner participant
    + metering points + assignments.
11. Owner transfer promotes new owner and demotes previous owner if they no
    longer own any ZEV.
12. Frontend `ProtectedRoute` enforces role-based route access; navigation
    visibility matches role capabilities.
13. `ManagedZevProvider` scopes all management pages to the selected ZEV.
14. Shared frontend helpers keep pages deduplicated: `frontend/src/lib/clipboard.ts` (`copyToClipboard`) consolidates direct `navigator.clipboard.writeText` calls and is used by `ApiKeysSection` and `ZevListPage`; `frontend/src/lib/participantTitle.ts` (`getTitleLabelMap`) is the single source of title (Mr/Ms/…) label maps used by `ParticipantsPage`; `frontend/src/lib/options.ts` exports `BILLING_INTERVAL_OPTIONS`, `ZEV_TYPE_OPTIONS`, `METER_TYPE_OPTIONS` (validated by `frontend/tests/options.test.ts`). `ZevListPage` stores its copy-feedback timeout in a ref and clears it on unmount/close so repeated copies don't race.
15. Full RBAC matrix (list, create, update, delete, unauthenticated) is covered
    by automated tests.
