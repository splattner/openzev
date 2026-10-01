# Feature Spec: Per-ZEV access grants (accounts layer of #761)

- Spec ID: SPEC-2026-10-zev-access-grants
- Status: Approved
- Scope: Major
- Type: Change
- Owners: Sebastian Plattner
- Created: 2026-10-01
- Target Release: next minor
- Related Issues: [#761](https://github.com/splattner/openzev/issues/761) (phase 1), prerequisite [#861](https://github.com/splattner/openzev/issues/861) / PR #863, related [#862](https://github.com/splattner/openzev/issues/862)
- Related ADRs: [ADR 0027](../adr/0027-per-zev-access-grants.md) (supersedes [ADR 0003](../adr/0003-role-and-zev-scope-enforcement.md)), [ADR 0001](../adr/0001-assignment-only-validity.md) (dated windows), [ADR 0026](../adr/0026-swiss-civil-time-for-billing.md) (civil dates)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

OpenZEV decides what an account may do from one platform-wide `User.role`
(`admin` / `zev_owner` / `participant` / `guest`) and two single-valued
relations: `Zev.owner` (the one account allowed to manage a ZEV) and
`Participant.user`. That cannot express:

1. **A tenant in two ZEVs** with one login.
2. **An owner of ZEV A who rents in ZEV B.** `link_account` rejects owner-role
   accounts, and `ZevScopedQuerySetMixin._scope_by_role` returns from its owner
   branch without adding participant rows.
3. **Several people managing one ZEV** (co-owners in a vZEV, a Verwaltung's
   staff) or **one account managing several owners' ZEVs** (a Verwaltung).
4. **Read-only access** for a bookkeeper (Treuhänder) or a co-owner who only
   wants to look.

**Outcome.** `User.role` only says whether the account is an admin. Managing or
viewing a ZEV is a dated per-ZEV grant (`manager` or `viewer`) that admins and
the ZEV's managers hand out, also to people without an account yet (by email
invitation). Participant access keeps coming from `Participant.user`, and an
account may be linked to many participant rows. Every endpoint answers with the
union of what the account holds. An account with exactly one relationship
(today's every account) sees and can do exactly what it does today.

This is phase 1 (accounts) of #761. Phase 2 (dated issuer/representative party
roles, dropping `Zev.owner`) and phase 3 (buildings/sites) are separate specs.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | New `ZevAccessGrant` + `ZevAccessRole`; `User.role` → `admin`/`user`; new `User.may_create_zev`; `EmailVerificationToken.purpose`; `AppSettings.mfa_required` replaces `mfa_required_roles` |
| Access helpers | New `backend/zev/access.py`, the only place "may this account view/manage this ZEV" is answered |
| Scoping | `ZevScopedQuerySetMixin` rewritten to a union of grants and participant links; default-deny writes below `manager`; former participants keep sent invoices only |
| Permissions | `BaseZevScopedPermission`, `IsZevOwnerOrAdmin` → `HasZevAccess`, ~25 hand-written owner checks |
| Grant API | `/api/v1/zev/zevs/{zev_id}/access/` list/create/update/revoke/resend-invitation |
| Invitations | Unknown email → pending account + grant + invitation email (7-day link) |
| Account plumbing | Link/unlink without role gate, impersonation of any non-admin, single 2FA switch, self-setup gate, `/auth/me` memberships, admin accounts list |
| Frontend | Community switcher, capability-based routes and navigation, viewer read-only UI, ZEV settings "Access" section, MFA switch, link dialog |
| Docs | ADR 0027, this spec, baseline spec updates, user guide |

### Out of scope

- Party roles (issuer, representative, landowner), non-participant parties,
  person/organisation participants, dropping `Zev.owner` — #761 phase 2.
- Buildings/sites and metering-point addresses — #761 phase 3.
- Organisations/teams of accounts (granting a Verwaltung as a whole).
- Who may link an account to a participant row: stays admin-only.
- The participant document inbox (#862).
- Exporting grants in the ZEV transfer archive (accounts are not exported).

## 3. Actors, permissions, and ZEV scope

"Relation to a ZEV" is one of: **manager** (active `manager` grant), **viewer**
(active `viewer` grant), **participant** (linked to a participant row of that
ZEV whose `valid_to` is null or ≥ today), **former participant** (linked only to
rows whose `valid_to` < today). An account can hold several at once; it gets the
union. "Today" is `django.utils.timezone.localdate()` (Swiss civil date, ADR 0026).

| Capability | admin | manager | viewer | participant | former participant |
|---|---|---|---|---|---|
| See ZEV-wide data (participants, metering points, readings, tariffs, all invoices, readiness, audit log, reports) | all ZEVs | that ZEV | that ZEV | — | — |
| Write anything in the ZEV (CRUD, imports, invoice workflow, contract issue, settings, onboarding links, disable) | all ZEVs | that ZEV | — | — | — |
| Downloads/exports (invoice PDFs ZIP, annual statements export, transfer archive, contract PDF GET) | yes | yes | yes | own only, as today | — |
| Grant / change / revoke manager & viewer access | yes | that ZEV | — | — | — |
| Own participant data (own metering points within assignment windows, dashboard, statement, financial summary) | — | — | — | yes | — |
| Own invoices | — | — | — | sent ones (#861) | sent ones |
| Disabled ZEV | read + write | read only | read only | invisible | invisible |
| Enable / purge a ZEV, create a ZEV for someone, link/unlink accounts, platform settings, impersonation | yes | — | — | — | — |

Admin needs no grant; an admin cannot be granted access (the API refuses) or
linked to a participant row (unchanged).

Backend permission classes after this change:

- `accounts.permissions.IsAdmin` — unchanged.
- `accounts.permissions.HasZevAccess` (replaces `IsZevOwnerOrAdmin`) —
  authenticated and (admin, or safe method and `viewable_zev_ids(user)` is
  non-empty, or unsafe method and `managed_zev_ids(user)` is non-empty). A
  coarse gate only; the per-ZEV decision is the scoped queryset or an explicit
  `can_manage`/`can_view`.
- `zev.permissions.BaseZevScopedPermission` and subclasses — see §6.2.

Frontend: `ProtectedRoute` takes `requires: 'admin' | 'zevAccess' | 'participant'`
instead of `allowedRoles` (§9.3).

## 4. Data model

### 4.1 `ZevAccessRole`

**Enum:** `zev.models.ZevAccessRole(models.TextChoices)`: `MANAGER = "manager"`, `VIEWER = "viewer"`.

### 4.2 `ZevAccessGrant`

**Model:** `zev.models.ZevAccessGrant`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | primary key, not editable |
| `zev` | FK `Zev` | — | `on_delete=CASCADE`, `related_name="access_grants"` |
| `user` | FK `AUTH_USER_MODEL` | — | `on_delete=CASCADE`, `related_name="zev_grants"` |
| `role` | `CharField(max_length=10, choices=ZevAccessRole.choices)` | — | |
| `valid_from` | `DateField` | `timezone.localdate` | inclusive |
| `valid_to` | `DateField` | `null` | inclusive; null = open-ended |
| `granted_by` | FK `AUTH_USER_MODEL` | `null` | `on_delete=SET_NULL`, `related_name="+"`; null for migrated and invariant-created grants |
| `created_at` | `DateTimeField(auto_now_add=True)` | | |
| `updated_at` | `DateTimeField(auto_now=True)` | | |

**Meta:** `ordering = ["zev_id", "role", "user_id", "valid_from", "id"]` (total
order). Constraints:

- `UniqueConstraint(fields=["zev", "user"], condition=Q(valid_to__isnull=True), name="one_open_zev_grant_per_user")`.
- `CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")), name="zev_grant_valid_window")`.
- Index on `(user, valid_to)` for the per-request lookup.

**Active on day `d`:** `valid_from <= d and (valid_to is null or valid_to >= d)`.
A grant whose `valid_from` is in the future is not active yet (a planned start).

**Revocation:** `revoke(grant, today)` sets `valid_to = today - 1 day` and saves;
if `valid_from >= today` (the grant never took effect) the row is deleted
instead. Either way access ends immediately. **Role change** (`manager` ↔
`viewer`): the open grant is revoked as above and a new open grant with the new
role and `valid_from = today` is created, in one transaction, so the history
records when the role changed.

**`__str__`:** `f"{user} {role} {zev.name}"`.

**Admin (`zev/admin.py`):** registered read-mostly (`list_display = zev, user, role, valid_from, valid_to`, `list_filter = role`), for support.

### 4.3 `User` changes (`accounts.models`)

| Field | Change |
|---|---|
| `role` | Choices become `UserRole.ADMIN = "admin"` and `UserRole.USER = "user"`; default `user`. Data migration maps `zev_owner`/`participant`/`guest` → `user` (lands in PR 7, §11) |
| `may_create_zev` | New `BooleanField(default=False)`. Set to `True` by self-registration (`register`). Gates `ZevViewSet.self_setup` (§7.6). Data migration: `True` for every account whose role was `zev_owner` |

Properties: `is_admin` unchanged (`role == ADMIN or is_superuser`).
`is_zev_owner` is **removed** (PR 4) so that every remaining reader fails at
import/test time instead of silently answering the old question.

`OpenZevUserManager.create_superuser` keeps forcing `role=admin`.

### 4.4 `EmailVerificationToken.purpose` (`accounts.models`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `purpose` | `CharField(max_length=20, choices=[("signup","Signup"),("invitation","Invitation")])` | `"signup"` | |

`is_valid()`: not consumed and `now < created_at + lifetime`, where lifetime is
24 h for `signup` (unchanged) and 7 days for `invitation`
(`INVITATION_LINK_LIFETIME = timedelta(days=7)`).

### 4.5 `AppSettings.mfa_required` (`accounts.models`)

`mfa_required_roles` (JSON list) is replaced by `mfa_required =
BooleanField(default=False)`. `MFA_POLICY_FIELDS = ("mfa_required",
"mfa_grace_period_days")`; `validate_mfa_required_roles` is replaced by a check
that `mfa_required=True` is refused when `settings.MFA_ENCRYPTION_KEYS` is empty
(same message as today). `mfa_grace_period_days` and `mfa_policy_changed_at`
are unchanged.

**Migration** (schema + data, one migration): `mfa_required = bool(mfa_required_roles)`;
when that is `True`, `mfa_policy_changed_at = now()` so every account the old
list did not cover gets a full grace period rather than being locked out; then
drop `mfa_required_roles`. Release notes must say this.

### 4.6 Data migration for grants

`zev/migrations/00xx_zev_access_grant.py`: create the model, then for every
`Zev`: `ZevAccessGrant(zev=zev, user_id=zev.owner_id, role="manager",
valid_from=zev.start_date)`. Reverse: delete all grants. Lossless — the input is
exactly `Zev.owner`.

### 4.7 Transitional invariant: the owner holds a manager grant

`zev.access.sync_owner_grant(zev, previous_owner_id=None)` ensures `zev.owner`
has an active manager grant (creating an open one with `valid_from = today`,
`granted_by=None`, if missing; an active `viewer` grant is converted per the
role-change rule). When `previous_owner_id` differs from the current owner, the
previous owner's open manager grant is revoked — this preserves today's
behaviour where reassigning `Zev.owner` removed the old owner's access.

It is called from `Zev.save()` when the instance is being added or `owner_id`
changed (tracked with `__init__`-time `_loaded_owner_id`). That one hook covers
`create_zev_with_owner_setup`, `create_zev_for_existing_owner`,
`zev.transfer.importer`, `seed_demo`, `ZevSerializer.update` and every test
fixture that does `Zev.objects.create(owner=...)`. Bulk `QuerySet.update(owner=…)`
bypasses it; nothing in the codebase does that (pinned by a test that greps).

The invariant is not enforced afterwards: a manager may revoke the owner's grant
(a legal owner handing management to a Verwaltung). Phase 2 removes it together
with `Zev.owner`.

### 4.8 Backups and transfer archive

- `backups/registry.py`: `zev.ZevAccessGrant` joins the per-ZEV section after
  `zev.Zev` (the coverage test requires it).
- `backups/restore_zev.py`: grants are restored through the account transform
  (`_account_transform`) for `user_id` and `granted_by_id`; a grant whose user
  does not map is dropped, `granted_by` that does not map becomes null.
- ZEV transfer archive: grants are **not** exported (accounts never are). On
  import, the importing account becomes `Zev.owner`, and §4.7 gives it a manager
  grant. Recorded in `2026-08-zev-transfer-archive.md`.

## 5. Access helpers (`backend/zev/access.py`)

All functions treat an admin as allowed everywhere and an anonymous user as
allowed nowhere. Results per `(user, today)` are memoised on the user instance
(`user._zev_access_cache`), so one request performs at most one grant query and
one participant query; the cache is cleared by `invalidate(user)`, which the
grant API calls after writing.

| Function | Returns |
|---|---|
| `managed_zev_ids(user) -> frozenset[UUID]` | ZEVs with an active `manager` grant |
| `viewable_zev_ids(user) -> frozenset[UUID]` | ZEVs with an active `manager` or `viewer` grant |
| `participant_zev_ids(user, *, include_ended=False) -> frozenset[UUID]` | ZEVs of the account's participant rows (live rows only unless `include_ended`) |
| `can_manage(user, zev) -> bool` | admin, or `zev.pk in managed_zev_ids(user)` |
| `can_view(user, zev) -> bool` | admin, or `zev.pk in viewable_zev_ids(user)` |
| `active_grants(user)` | queryset of active grants (for `/auth/me`) |
| `sync_owner_grant(zev, previous_owner_id=None)` | §4.7 |
| `revoke(grant, *, today=None)` / `change_role(grant, role, *, by)` | §4.2 |
| `is_last_manager(grant) -> bool` | the grant is `manager`, active, and no other active manager grant exists on its ZEV |

A participant row is **live** when `valid_to is null or valid_to >= today`.
Future-dated rows count as live (unchanged from today, so onboarding before the
start date keeps working).

## 6. Scoping and permissions

### 6.1 `ZevScopedQuerySetMixin` (`backend/zev/scoping.py`)

Class attributes after the change:

| Attribute | Meaning |
|---|---|
| `zev_lookup: str` | ORM path from the model to its `Zev` (`""` for `ZevViewSet`). Declared directly; replaces `zev_owner_filter`, from which it used to be derived |
| `participant_path: str \| None` | ORM path from the model to `Participant` (e.g. `"participant"`, `"participants"`, `"assignments__participant"`, `""` for `ParticipantViewSet`). `None` = participants see nothing (owner-only resource). Replaces `participant_filter` (a path to the user) |
| `participant_distinct: bool` | unchanged |
| `participant_visible: Q \| None` | unchanged (#861); `InvoiceViewSet` sets `sent_to_participant()` |
| `participant_access_survives_end: bool = False` | when `True`, ended participant rows still grant access (subject to `participant_visible`). Only `InvoiceViewSet` sets it |
| `viewer_allowed_actions: frozenset[str] = frozenset()` | action names that are unsafe HTTP methods but reads, allowed for viewers (`InvoiceViewSet`: `{"download_pdfs"}`) |
| `scope_parent_path` | unchanged |

**Read rule** (`_scope_by_relation`, replaces `_scope_by_role`):

```
if user.is_admin: return qs
zev_ids = viewable_zev_ids(user)   # or managed_zev_ids(user) for writes, below
q = Q(**{f"{zev_lookup}__in" if zev_lookup else "pk__in": zev_ids})
if participant_path is not None:
    p = f"{participant_path}__" if participant_path else ""
    part = Q(**{f"{p}user": user}) & Q(**{f"{zev_lookup}__disabled_at__isnull" ...: True})
    if not participant_access_survives_end:
        part &= Q(**{f"{p}valid_to__isnull": True}) | Q(**{f"{p}valid_to__gte": today})
    if participant_visible is not None:
        part &= participant_visible
    q |= part
qs = qs.filter(q)
if participant_distinct: qs = qs.distinct()
```

The grant branch keeps today's owner behaviour for disabled ZEVs (visible,
read-only); the participant branch keeps excluding them. `participant_visible`
narrows only the participant branch: a manager who is also a participant of the
same ZEV sees every invoice through the grant branch.

**Write rule (default-deny).** For a request whose method is not in
`SAFE_METHODS` and whose `self.action` is not in `viewer_allowed_actions`, the
grant branch uses `managed_zev_ids(user)` and the participant branch is dropped.
So any unsafe request by a viewer or participant to a detail route resolves to
404 in `get_object()` before view code runs, including custom actions that
forgot an explicit check.

`assert_within_scope`: `target_zev.owner_id != user.pk` → `not can_manage(user, target_zev)`.
`assert_target_not_disabled`: unchanged.

`MeterReadingViewSet` keeps overriding the participant branch (assignment-window
matching) and adopts the same union: grant branch via `viewable_zev_ids`, its
existing participant query unchanged, ended participants excluded.

### 6.2 Permission classes

`zev.permissions.BaseZevScopedPermission`:

- `has_permission`: authenticated and (admin, or safe method and (viewable or
  participant ZEVs non-empty, when `allow_participant_safe_methods`), or unsafe
  method and `managed_zev_ids` non-empty).
- `has_object_permission`: admin → allow. Resolve the ZEV (`_get_zev`, unchanged).
  Disabled ZEV and unsafe method → admin only (unchanged). Unsafe → `can_manage`.
  Safe → `can_view`, or (`allow_participant_safe_methods` and a live participant
  link in that ZEV).
- `ZevManagementPermission`: POST stays admin-only.
- `ZevDisablePermission`: `can_manage(user, zev)` (was `zev.owner == user`).

`accounts.permissions.IsZevOwnerOrAdmin` is renamed `HasZevAccess` (§3); every
use is replaced.

### 6.3 Hand-written checks replaced

| Site | Old | New |
|---|---|---|
| `invoices/views.py` `destroy`, `generate`, `generate_all` | `is_zev_owner`, `zev.owner != request.user` | `can_manage` |
| `invoices/views.py` `_get_period_invoices` (shared by `approve_all`, `send_all`, `generate_pdfs_all`, `download_pdfs`) | `zev.owner != request.user` | new keyword `for_write=True`: `can_manage`; `download_pdfs` passes `for_write=False`: `can_view` |
| `invoices/views.py` `period_overview` | `zev.owner_id != request.user.id` | `can_view` |
| `invoices/views_readiness.py` `_resolve_zev` | `zev.owner_id != user.id` | `can_view` |
| `invoices/views_reports.py` `_get_authorised_zev` | `zev.owner != user` | `can_view` |
| `invoices/views_reports.py` `_is_self_service` | `role == PARTICIPANT` | caller has no `can_view` on the requested ZEV and has a live participant link (§7.8) |
| `exports/views.py` create, status, download, list | `zev.owner != user`, `zev__owner=user` | `can_view` / `zev_id__in=viewable_zev_ids` (exports are reads) |
| `tariffs/views_import.py` | `zev.owner_id != user.id` | `can_manage` |
| `tariffs/views.py` dynamic source `recheck`/`fetch` | `tariffs.filter(zev__owner=user)` | `tariffs.filter(zev_id__in=managed_zev_ids)` |
| `metering/views.py` imports, chart, raw, dashboard, hourly, quality, bulk-delete, `ImportLogViewSet` | `role == "zev_owner"`, `owner=user` | `viewable_zev_ids` for reads, `managed_zev_ids` for imports/bulk-delete |
| `metering/importers/csv_importer.py` `_meter_queryset_for_user` | `is_zev_owner`, `zev.owner_id == user.id` | `can_manage` |
| `feasibility/views.py` | `Zev.objects.filter(id=…, owner=user)` | `can_view` |
| `mcp_server/views.py` `_resolve_zev_for_audit` | `Zev.objects.filter(owner=user)` | `viewable_zev_ids` |
| `audit/views.py` `CanViewAuditEvents`, `_base_queryset` | `role == ZEV_OWNER`, `zev__owner=user` | viewable ZEVs non-empty; `zev_id__in=viewable_zev_ids` |
| `zev/views.py` `ParticipantViewSet._contract_pdf_access_denied` | `is_zev_owner` | GET: `can_view` or own participant; POST (issue): `can_manage` |
| `zev/views.py` `self_setup` | `is_zev_owner` | §7.6 |
| `zev/serializers.py` `ParticipantSerializer.validate` | `user.role != PARTICIPANT` | removed |
| `accounts/serializers.py` `SelfUserSerializer.validate_preferred_zev` | `value.owner_id != user.pk` | `can_view(user, value)` or a participant link in it |

### 6.4 Dashboard summary (`metering/views.py` `dashboard_summary`)

- `?zev_id=` given: `can_view` → owner summary for that ZEV; else live
  participant link in that ZEV → participant summary for that ZEV only; else 403.
- No `zev_id`: exactly one viewable ZEV → owner summary for it; none viewable and
  live participant links → participant summary across them (today's
  behaviour); otherwise 400 `zev_id query parameter is required.`

The response key `role` keeps its values `"zev_owner"` / `"participant"` until
PR 7, where it is renamed `summary_kind` with values `"zev"` / `"participant"`.

## 7. API contracts

### 7.1 Grants — `ZevAccessGrantViewSet`

Routes (registered in `zev/urls.py` with explicit `path()`s under the ZEV):

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/zev/zevs/{zev_id}/access/` | GET | `can_view(zev)` | List grants. Default: active and future grants; `?include_ended=true` adds ended ones. Ordered by role, then user email |
| `/api/v1/zev/zevs/{zev_id}/access/` | POST | `can_manage(zev)`, ZEV not disabled (admin exempt) | Body `{email, role, valid_to?}`. See below. 201 with the grant |
| `/api/v1/zev/zevs/{zev_id}/access/{id}/` | PATCH | `can_manage(zev)`, not disabled | Body `{role?, valid_to?}`. Role change per §4.2; `valid_to` sets a planned end (≥ `valid_from`). 200 |
| `/api/v1/zev/zevs/{zev_id}/access/{id}/` | DELETE | `can_manage(zev)`, not disabled | Revoke per §4.2. 204 |
| `/api/v1/zev/zevs/{zev_id}/access/{id}/resend-invitation/` | POST | `can_manage(zev)` | Only while the grantee's account is pending (`is_active=False` with an unconsumed `invitation` token); issues a new token and email. 202; 400 otherwise |

A ZEV the caller cannot view answers 404 on every route.

**Create.** `email` is normalised (strip, case-insensitive match on
`User.email`):

- matches an admin account → 400 `{"email": ["Admins already have access to every ZEV."]}`;
- matches an account with an open grant on this ZEV → 400 `{"email": ["This account already has access to this ZEV. Change its role instead."]}`;
- matches another account → grant created (`valid_from = today`, `granted_by = request.user`), notification email `zev_access_granted`;
- matches no account → invitation (§8): account created, grant created, `invitation` email.

**Refusals on PATCH/DELETE:** downgrading or revoking the last active manager → 400
`{"detail": "A ZEV needs at least one manager."}` (also when a manager revokes
themself). A planned `valid_to` on the last manager is refused the same way.

**Serializer `ZevAccessGrantSerializer`** — fields: `id`, `zev`, `role`,
`valid_from`, `valid_to`, `is_active`, `granted_by` (`{id, full_name}` or null),
`created_at`, `user` (`{id, email, first_name, last_name, pending_invitation}`);
read-only: everything except `role`, `valid_to`. `pending_invitation` = account
inactive with an unconsumed `invitation` token. Write-only on create: `email`.

**Audit** (`audit.services.record_audit_event`, category `governance`,
`target_type="zev.ZevAccessGrant"`, `zev` set): `zev_access.grant`,
`zev_access.invite`, `zev_access.change_role`, `zev_access.set_end`,
`zev_access.revoke`, `zev_access.resend_invitation`; refusals recorded as
`DENIED` like other governance denials. Metadata: `user_id`, `role`, and
`before`/`after` for changes.

### 7.2 Participant account link / unlink (`ParticipantViewSet`)

- `link-account` (admin only, unchanged): the role gate
  (`participant`/`guest` only) and `already_linked_elsewhere` are removed.
  Refused: target is an admin (400 `"Admin accounts cannot be linked to a participant."`),
  participant already linked to another account (400, unchanged).
- `unlink-account` (admin only): no longer touches `User.role`. The
  "cannot unlink the owner account from the owner participant" rule stays until phase 2.

### 7.3 `zev.services`

- `sync_participant_user_fields`: no longer writes `role`.
- `ensure_participant_account`: the password carve-out ("never touch the
  password of an owner or admin") becomes "of an admin, or an account with any
  grant"; it no longer reads or writes `role`. Newly created participant
  accounts get `role=user` (before PR 7: `participant`).
- `own_participant_for_user(user, zev=None)`: with `zev`, the live participant
  row in that ZEV; without, unchanged (first by ordering).

### 7.4 Impersonation (`accounts/views_impersonation.py`)

`IMPERSONATABLE_ROLES` is removed. `ImpersonateParticipantView` (name kept)
refuses only admins and inactive accounts (400). Audit metadata records
`is_admin=False` and the target's grant count and participant count instead of
`role`.

### 7.5 Two-factor policy

- `accounts.mfa.policy_applies(user)` → `app_settings.mfa_required`.
- `accounts.mfa.grace_deadline(user)` → `None` unless `mfa_required`.
- `accounts.authentication.enforce_mfa_enrolment` → returns early unless `mfa_required`.
- `AppSettingsSerializer`: `mfa_required` (bool) replaces `mfa_required_roles`.
  `PATCH /api/v1/auth/app-settings/` with `mfa_required` is admin-only as before;
  changing it or `mfa_grace_period_days` stamps `mfa_policy_changed_at` (unchanged).
- `AdminUserSerializer.mfa_compliance`: `null` when the policy is off.

### 7.6 Self-registration and self-setup

- `register` creates the pending account with `role=user` (before PR 7:
  `zev_owner`, so existing behaviour holds until the collapse),
  `may_create_zev=True`, and a `signup`-purpose token.
- `ZevViewSet.self_setup`: allowed when `user.may_create_zev` and the account
  has no active manager grant on a non-disabled ZEV (the same condition as
  today's "you already have a ZEV" guard, which counted only active owned ZEVs).
  403 `"This account cannot create a ZEV."` otherwise.
- OAuth auto-provisioning (`views_oauth.py`) creates `role=user`, `may_create_zev=False`.
- `create_zev_with_owner_setup` (admin wizard) creates the owner with `role=user`
  (`zev_owner` before PR 7) and `may_create_zev=False`; the grant comes from §4.7.

### 7.7 `/api/v1/auth/me/` and the admin accounts list

`_serialize_me` adds:

```json
"memberships": [
  {
    "zev": "<uuid>",
    "zev_name": "Sonnenhof",
    "zev_disabled": false,
    "access": "manager" | "viewer" | null,
    "participants": [{"id": "<uuid>", "valid_from": "2025-01-01", "valid_to": null, "live": true}]
  }
]
```

One entry per ZEV the account relates to through an active grant or any
participant row (ended rows included, so a former participant can still reach
their invoices); sorted by `zev_name` (case-insensitive), then `zev`. Admins get
the entries for their own participant rows only (normally `[]`).
`zev_name`/`zev_count` stay until PR 7, then are removed.

`AdminUserSerializer.get_memberships` returns the same shape built from stored
grants and participant rows, replacing the per-ZEV merge of `owned_zevs` and
`participations`. `AccountMembership` in the frontend changes accordingly (§9.6).

The admin accounts list `?role=` filter accepts `admin` and `user`
(`zev_owner`/`participant`/`guest` are rejected with 400 after PR 7).

### 7.8 Reports self-service (`invoices/views_reports.py`)

`AnnualStatementView` and `FinancialSummaryView`: when the caller can view the
requested `zev_id`, the manager branch (`participant_id` required for the
statement) applies. Otherwise the self-service branch picks the caller's live
participant row **in `zev_id`** when given, else the first live one
(`own_participant_for_user`). The statement keeps `sent_only=True` (#861).

### 7.9 JWT claims

`role` stays a claim (`admin`/`user` after PR 7). The frontend never decodes
tokens; it reads `/auth/me`.

## 8. Invitations

Triggered by a grant create whose email matches no account (§7.1):

1. Create `User(username=<from email, unique>, email=email, role=user,
   is_active=False, may_create_zev=False)` with `set_unusable_password()`.
2. Create the grant (`granted_by = request.user`).
3. Create `EmailVerificationToken(user, purpose="invitation", token=token_urlsafe(48))`.
4. Send email template `zev_access_invitation` (new `EMAIL_TEMPLATE_DEFAULTS`
   key, overridable like the others, in `de`/`fr`/`it`/`en`, language from the
   ZEV's `invoice_language`). Context: `zev_name`, `role_display`,
   `inviter_name`, `accept_url = {FRONTEND_URL}/verify-email?token=…`,
   `expires_days = 7`.

Accepting reuses `POST /api/v1/auth/verify-email/` (activates the account,
mints a session, MFA rules unchanged). Its response gains
`"purpose": "signup" | "invitation"`. The frontend `VerifyEmailPage` then asks
for a password (step `set-password`, existing) and, for `invitation`, skips the
`create-zev` step and lands on `/`.

An expired invitation leaves an inactive account holding a grant; it grants
nothing (inactive accounts cannot authenticate). `resend-invitation` issues a
fresh token. Revoking the grant of a never-activated invited account also
deletes the account when it has no other grant and no participant link.

Granting to an existing account sends `zev_access_granted` (same languages):
`zev_name`, `role_display`, `inviter_name`, `login_url`.

Both are sent synchronously the same way `register` sends
`email_verification` today (subject/body from `EMAIL_TEMPLATE_DEFAULTS`,
overridden by an `EmailTemplate` row with the same `template_key`); a send failure leaves the grant in place, returns 201
with `"email_sent": false`, and is audited as `FAILED` on
`zev_access.invite`/`zev_access.grant`.

## 9. Frontend

### 9.1 Types (`frontend/src/types/api.ts`)

```typescript
export type UserRole = 'admin' | 'user'            // PR 7; until then the old union plus 'user'
export type ZevAccessRole = 'manager' | 'viewer'

export interface MembershipParticipant {
    id: string
    valid_from: string
    valid_to: string | null
    live: boolean
}

export interface Membership {
    zev: string
    zev_name: string
    zev_disabled: boolean
    access: ZevAccessRole | null
    participants: MembershipParticipant[]
}

export interface User {
    // …existing fields…
    memberships: Membership[]
}

export interface ZevAccessGrant {
    id: string
    zev: string
    role: ZevAccessRole
    valid_from: string
    valid_to: string | null
    is_active: boolean
    granted_by: { id: number; full_name: string } | null
    created_at: string
    user: { id: number; email: string; first_name: string; last_name: string; pending_invitation: boolean }
}
```

`AccountMembership` (admin accounts list) is replaced by `Membership`.
`AppSettings.mfa_required_roles: UserRole[]` → `mfa_required: boolean`.

### 9.2 Community context (`frontend/src/lib/managedZev.tsx` → `lib/community.tsx`)

`CommunityProvider` replaces `ManagedZevProvider` (the old name is kept as an
alias export until PR 7).

- **Entries:** admin → every ZEV (`fetchZevs`), each with relation `admin`;
  everyone else → `user.memberships`, each with relation `manager` / `viewer` if
  `access` is set, else `participant` if any participant row is live, else
  `former`.
- **Selection** (`resolveCommunitySelection`, pure and unit-tested, replaces
  `resolveManagedSelection`): explicit in-session pick if still listed →
  `user.preferred_zev` if listed → first entry by name. Reset on account change
  (unchanged).
- **Switcher** shown when there is more than one entry; each option shows the
  ZEV name and the relation label (`nav.relation.manager` etc.).
- **`useCommunityAccess()`** → `{ zevId, relation, canManage, canView, isParticipantHere }`
  for the selected entry. `canManage` = admin or manager; `canView` = canManage or viewer.

`preferred_zev` may now name any ZEV the account relates to (backend §6.3).

### 9.3 Routes (`components/AppRoutes.tsx`, `components/ProtectedRoute.tsx`)

`ProtectedRoute` prop `requires`:

| `requires` | Passes when |
|---|---|
| `'admin'` | `user.role === 'admin'` |
| `'zevAccess'` | the selected entry's `canView` |
| `'participant'` | the selected entry's relation is `participant` or `former` (former: only `/me/invoices`) |

| Routes | Old `allowedRoles` | New `requires` |
|---|---|---|
| `/admin/**`, `/admin/system-settings` | `admin` | `admin` |
| `/participants`, `/zev-settings`, `/zev-settings/:tab`, `/metering/quality`, `/tariffs`, `/billing/periods`, `/billing/invoices`, `/billing/emails`, `/feasibility`, `/metering/imports` | `admin`, `zev_owner` | `zevAccess` |
| `/me/statement` | `participant` | `participant` (live only) |
| `/me/invoices` | `participant` | `participant` |
| `/reports` | `admin`, `zev_owner`, `participant` | any relation |

### 9.4 Navigation (`components/Layout.tsx`)

The sidebar follows the selected entry's relation: `admin`/`manager`/`viewer` →
the Setup and Billing groups (today's owner navigation); `participant` →
Dashboard, My invoices, Annual statement (today's participant navigation),
scoped to the selected ZEV through `zev_id` on their queries; `former` → My
invoices only. The Platform group stays admin-only. An account with exactly one
relationship sees today's sidebar unchanged.

`DashboardPage` reads `summary.role` (`summary_kind` after PR 7) as today; it
passes the selected `zev_id` for every relation.

### 9.5 Viewer read-only

Every write affordance is gated on `useCommunityAccess().canManage`, hidden (not
disabled) for viewers, following the action hierarchy of
`2026-04-frontend-management-page-design.md`:

- `features/invoices/useInvoiceActions.tsx` — generate, approve, mark sent/paid,
  cancel, delete, send, regenerate PDF, batch actions (PDF ZIP download stays).
- `ParticipantsPage` — create/edit/delete, onboarding links, contract issue
  (contract download stays).
- `MeteringPointsPage`, `MeteringChartPage` (import entry), imports pages —
  create/edit/delete/assign/import.
- `TariffsPage` — create/edit/delete, VSE import, dynamic source actions.
- `ZevSettingsPage` — all forms read-only; disable action hidden; Access section
  read-only (§9.6).
- `ReportsPage` — unchanged (all reads).

A viewer who reaches a write through a stale link gets the backend 404/403 and
the page's existing error state.

### 9.6 ZEV settings → Access (`features/zev/ZevAccessSection.tsx`, new)

Tab `access` on `/zev-settings/:tab`. Query
`queryKeys.zev.access(zevId)` → `fetchZevAccess(zevId)`.

- Table: name/email (with "Invitation pending" badge and a *Resend* action),
  role, since, until, granted by. Ended grants behind a "Show ended" toggle
  (`include_ended`).
- Primary action "Give access": form with email + role (`manager`/`viewer`) +
  optional end date → `createZevAccess`. Success toast distinguishes "Access
  granted" and "Invitation sent"; `email_sent: false` shows a warning.
- Row actions (managers/admins only): change role, set end date, revoke —
  revoke and downgrade through `ConfirmDialog`. The last-manager refusal shows
  the backend message.
- Viewers see the table without actions.
- On mutation success: invalidate `queryKeys.zev.access(zevId)` and, when the
  change affects the current user, `queryKeys.auth.me()`.

`features/accounts/AccountMemberships.tsx` / `AdminAccountsPage.tsx`: render
`Membership[]` (relation badge + participant rows); the role filter becomes
admin / non-admin.

`features/settings/MfaPolicySection.tsx`: one switch "Require two-factor
authentication for every account" plus the grace period.

`ParticipantsPage` link dialog: candidate accounts are all non-admin accounts.

`VerifyEmailPage`: §8.

### 9.7 API client (`frontend/src/lib/api/zev.ts`)

| Function | Method | Endpoint |
|---|---|---|
| `fetchZevAccess(zevId, { includeEnded })` | GET | `/zev/zevs/{zevId}/access/` |
| `createZevAccess(zevId, { email, role, valid_to })` | POST | `/zev/zevs/{zevId}/access/` |
| `updateZevAccess(zevId, id, { role, valid_to })` | PATCH | `/zev/zevs/{zevId}/access/{id}/` |
| `revokeZevAccess(zevId, id)` | DELETE | `/zev/zevs/{zevId}/access/{id}/` |
| `resendZevInvitation(zevId, id)` | POST | `/zev/zevs/{zevId}/access/{id}/resend-invitation/` |

### 9.8 i18n

New keys in all four locales (`frontend/src/i18n/locales/{de,fr,it,en}`):
`nav.relation.{admin,manager,viewer,participant,former}`,
`zevSettings.access.*` (title, table columns, actions, confirmations, toasts,
pending badge, errors), `auth.verify.invitation*`,
`admin.settings.mfa.requiredAll`. Removed: the per-role MFA checkbox labels.

## 10. Async and integration behavior

- No new Celery tasks. Invitation and notification emails send synchronously
  (§8), like `email_verification` today.
- MCP: tools call REST views in-process (ADR 0025), so they inherit the new
  scoping. `list_zevs` returns every viewable ZEV; a viewer's MCP session is
  read-only anyway.
- API keys inherit their owner's grants (unchanged principle); a `read_only`
  key is still refused unsafe methods before scoping.

## 11. Delivery

Each PR is green on its own; numbering follows the implementation plan.

| PR | Content |
|---|---|
| — | #861 fix (PR #863), prerequisite |
| 1 | This spec + ADR 0027 |
| 2 | Regression suite pinning today's behaviour (`zev/test_access_regression.py`), tests only |
| 3 | `ZevAccessGrant`, migration, `zev/access.py`, owner invariant, backups registry/restore — no behaviour change |
| 4 | Scoping/permissions/hand checks on grants; viewer; union; former participants; dashboard/reports `zev_id`; remove `is_zev_owner` |
| 5 | Grant API, invitations, link/unlink, impersonation, MFA switch, self-setup gate, `/auth/me` memberships |
| 6 | Frontend (§9) |
| 7 | Collapse `User.role` to `admin`/`user`; remove `zev_name`/`zev_count`, `ManagedZevProvider` alias, `summary.role`; test-suite role churn; `seed_demo` personas |

Baseline specs updated in the PR that changes their behaviour:
`2026-03-community-and-access.md`, `2026-03-admin-governance-and-settings.md`,
`2026-09-two-factor-authentication.md`, `2026-03-invoice-lifecycle-and-communication.md`,
`2026-08-zev-transfer-archive.md`, `2026-09-mcp-server.md`; user guide
`11-roles-and-permissions.md`, `02-zev-setup.md` (Access), `14-admin-console.md`
(2FA switch, accounts list).

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A rewritten read path leaks another ZEV's rows | High | PR 2 pins today's visible sets per endpoint before any change; union tests per relation; `?zev_id=` narrowing unchanged |
| A custom action lets a viewer write | High | Default-deny write queryset (§6.1); router-walking test asserts every unsafe route answers 403/404 for a viewer except `viewer_allowed_actions` |
| Owner loses access after migration | High | Migration creates a manager grant per `Zev.owner`; regression suite runs on migrated data; invariant on create/owner change |
| Per-request query cost of grant lookups | Medium | One grant query + one participant query per request, memoised (§5) |
| 2FA policy migration forces 2FA on accounts that never had it | Medium | Grace period restarts at migration; release notes |
| Invitation spam / account creation by managers | Medium | Only managers/admins can invite; invited accounts are inactive until accepted; audit trail; resend is per grant |
| Frontend drift between `requires` and backend rules | Medium | Backend is authoritative; frontend gating is UX only (ADR 0027 keeps ADR 0003's layering) |
| `Zev.owner` and grants diverge during the transition | Low | Intended (owner handing over to a Verwaltung); phase 2 removes `Zev.owner` |

## 13. Test plan

### Backend — `zev/test_access_regression.py` (PR 2; 17 tests, shipped)

World (`AccessWorldMixin.setUpTestData`): two communities built with
`zev.test_transfer.build_populated_zev` — Alpha (owner `acc_owner_a`, who is
also Alpha's participant "Olivia Owner") and Beta (owner `acc_owner_b`); a
tenant linked to Alpha's Bob (holder of `ALPHA-CONS-1`) with one sent and one
draft invoice; a draft invoice in Beta; an extra 100 kWh Beta production
reading so a leak of Beta's totals is visible; one import log and one audit
event per community; plus an admin and a guest. Expected sets are computed from
the database. Every write attempt runs in a rolled-back savepoint.

**`SingleRelationshipVisibilityMatrixTests`** (7):

| Test | Asserts |
|---|---|
| `test_list_matrix` | For admin/owner/tenant/guest on zevs, participants, metering points, assignments, tariffs, tariff periods, invoices, readings, import logs, audit events: admin = all rows, owner = Alpha's rows, tenant = their meter and their sent invoice (other lists 403), guest = empty meter/invoice lists (other lists 403) |
| `test_owner_cannot_open_another_communitys_rows` | Owner gets 404 on Beta's ZEV, participant, metering point, tariff and invoice detail |
| `test_tenant_opens_only_their_own_sent_invoice` | Own sent invoice 200; own draft and Alice's invoice 404 |
| `test_zev_scoped_reports_matrix` | Readiness and period overview: admin 200/200, owner 200 (Alpha) / 403 (Beta), tenant and guest 403 |
| `test_dashboard_summary_matrix` | Admin needs `zev_id` (400 without); owner gets the owner summary for Alpha, 403 for Beta; tenant/guest always get the participant summary and never Beta's totals |
| `test_self_service_statement_matrix` | Tenant self-service 200; guest 400 (not self-service, so `zev_id`/`participant_id` required); owner 200 for Alpha's participant, 403 for Beta's |
| `test_mcp_list_zevs_matrix` | Admin lists both ZEVs, owner only Alpha; tenant and guest are refused by the endpoint (403) |

**`SingleRelationshipWriteMatrixTests`** (10) — status per (admin, owner, tenant, guest):

| Test | Asserts |
|---|---|
| `test_zev_settings` | PATCH Alpha 200/200/403/403; PATCH Beta 200/404/403/403 |
| `test_participant_edit` | PATCH Alpha participant 200/200/403/403; Beta participant 200/404/403/403 |
| `test_create_metering_point` | POST under Alpha 201/201/403/403; under Beta 201/400/403/403 (field error) |
| `test_create_tariff` | Same shape as metering points |
| `test_invoice_workflow` | Approve Alpha draft 200/200/403/403, Beta draft 200/404/403/403; delete Alpha draft 204/204/404/404, Beta draft 204/404/404/404 |
| `test_export_job_creation` | Alpha 202/202/403/403; Beta 202/403/403/403 |
| `test_disable_zev` | Alpha 200/200/403/403; Beta 200/404/403/403 |
| `test_account_linking_is_admin_only` | 200/403/403/403 |
| `test_impersonation` | Admin may impersonate tenant and another owner (200), not a guest or an admin (400); owner always 403 |
| `test_self_setup_needs_an_owner_account` | Tenant and guest 403; owner with an active community 400 |

A deliberate mutation (owner branch of `_scope_by_role` returning every row)
fails the list, detail and MCP checks, so the suite discriminates.

### Backend — `zev/test_access.py` (PR 3)

**`ZevAccessGrantModelTests`**: constraints (one open grant, window check),
active-on-day, revoke sets `valid_to = yesterday`, revoke of a same-day grant
deletes it, role change creates a new row. **`AccessHelperTests`**: each helper
for admin/manager/viewer/participant/former/none, memoisation (query count),
future-dated grant inactive. **`OwnerGrantInvariantTests`**: create ZEV → grant;
owner change → old revoked, new granted; transfer import → importer granted;
migration creates one grant per ZEV.

### Backend — `zev/test_access_scoping.py` (PR 4)

**`MultiRelationshipScopingTests`**: tenant in two ZEVs; owner of A renting in
B (sees A wholly, own rows in B); manager of two ZEVs; manager + participant in
the same ZEV sees unsent invoices via the grant. **`ViewerTests`**: reads equal a
manager's; writes 403/404; `download_pdfs` and export creation allowed.
**`ViewerWriteRouterWalkTests`**: enumerates `router.registry` and custom
actions, asserts a viewer's unsafe requests fail except the allow-list.
**`FormerParticipantTests`**: sent invoices visible, everything else gone, ended
row + live row in another ZEV. **`DisabledZevTests`**: viewer/manager read-only,
participant invisible.

### Backend — PR 5

`zev/test_access_api.py` — **`ZevAccessGrantApiTests`** (list/create/patch/delete,
permissions per relation, last-manager refusals, admin email refused, duplicate
refused, disabled ZEV refused, audit events), **`ZevAccessInvitationTests`**
(account created inactive, token purpose and 7-day lifetime, verify returns
`purpose`, resend, revoke deletes never-activated account, email failure →
`email_sent: false`). `zev/tests.py` — link/unlink without role gate, admin
refused. `accounts/test_impersonation.py` — any non-admin. `accounts/test_mfa.py` —
`mfa_required` switch, migration mapping and grace restart.
`accounts/tests.py` — `/auth/me` memberships, self-setup gate.

### Frontend (PR 6)

`community.test.ts` (selection resolution, relation per entry, switcher
visibility), `protected-route.test.ts` (`requires`), `layout-nav.test.ts`
(navigation per relation, single-relationship accounts unchanged),
`zev-access-section.test.ts` (list, create/invite, role change, revoke,
last-manager error, viewer read-only), `viewer-readonly.test.ts` (write
affordances hidden on the pages in §9.5), `verify-email.test.ts` (invitation
skips the ZEV wizard), `mfa-policy.test.ts`. Plus `npm run lint`,
`lint:style`, hex check, `test:unit`, `build`.

### Acceptance criteria

- [ ] Every account with one relationship sees and can do exactly what it could before (PR 2 suite green from PR 3 on).
- [ ] One account can be a participant in two ZEVs, and a manager in one ZEV and a participant in another; each ZEV shows what that relation allows.
- [ ] A ZEV can have several managers and viewers; the last manager cannot be removed.
- [ ] A viewer sees everything a manager sees in that ZEV and every write is refused by the backend.
- [ ] A manager can invite an unknown email; the invitee sets a password and lands in the ZEV without the setup wizard.
- [ ] A former participant sees their sent invoices and nothing else of that ZEV.
- [ ] Admins can impersonate any non-admin account and see its full union.
- [ ] 2FA is one switch; turning it on gives every account the grace period.
- [ ] `User.role` holds only `admin`/`user` after PR 7, and nothing reads `is_zev_owner`.
