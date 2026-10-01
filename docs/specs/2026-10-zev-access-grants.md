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

**Admin (`zev/admin.py`):** `ZevAccessGrantAdmin` — `list_display = (zev, user, role, valid_from, valid_to, granted_by)`, `list_filter = (role,)`, `search_fields = (zev__name, user__email, user__username)`, `raw_id_fields = (user, granted_by)`; for support.

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

`zev/migrations/0031_zev_access_grant.py`: create the model, then
`RunPython(grant_owners, drop_grants)` — for every `Zev`:
`ZevAccessGrant(zev=zev, user_id=zev.owner_id, role="manager",
valid_from=<local date of zev.created_at>)`. The creation date, not
`start_date`: a ZEV planned to start in the future would otherwise lock its owner
out until then. Reverse: delete all grants. Lossless — the input is exactly
`Zev.owner`.

### 4.7 Transitional invariant: the owner holds a manager grant

`zev.access.sync_owner_grant(zev, previous_owner_id=None)` ensures `zev.owner`
has an active manager grant (creating an open one with `valid_from = today`,
`granted_by=None`, if missing; an active `viewer` grant is converted per the
role-change rule). When `previous_owner_id` differs from the current owner, the
previous owner's open manager grant is revoked — this preserves today's
behaviour where reassigning `Zev.owner` removed the old owner's access.

It is called from `Zev.save()` when the instance is being added or `owner_id`
changed (tracked as `_loaded_owner_id`, set in `Zev.from_db`; an instance loaded
with `owner` deferred triggers a harmless no-op sync). That one hook covers
`create_zev_with_owner_setup`, `create_zev_for_existing_owner`,
`zev.transfer.importer`, `seed_demo`, `ZevSerializer.update` and every test
fixture that does `Zev.objects.create(owner=...)`. Bulk `QuerySet.update(owner=…)`
bypasses it; nothing in the codebase does that (pinned by a test that greps).

The invariant is not enforced afterwards: a manager may revoke the owner's grant
(a legal owner handing management to a Verwaltung). Phase 2 removes it together
with `Zev.owner`.

### 4.8 Backups and transfer archive

- `backups/registry.py`: new per-ZEV section `access_grants`
  (`ZevPart("zev.ZevAccessGrant", "zev")`) right after `zev` (the coverage test
  requires every model to be listed). An instance restore loads it like any
  other section.
- `backups/restore_zev.py`: `access_grants` is a **kept** section
  (`_KEPT_SECTIONS = {"audit_events", "access_grants"}`): a per-ZEV restore rolls
  data back, not who may act on the community today, just as it never writes
  accounts. After loading, `zev.access.ensure_a_manager(zev)` gives the owner a
  manager grant when the community has no active manager at all — the case of a
  deleted community being recreated, whose grants were deleted with it.
  Restoring an archive from before grants existed needs the database migrated
  back first (`check_migrations`); migrating forward again runs §4.6.
  Recorded in `2026-09-backup-and-restore.md` (decision 18a).
- ZEV transfer archive: grants are **not** exported (accounts never are). On
  import, the importing account becomes `Zev.owner`, and §4.7 gives it a manager
  grant. Recorded in `2026-08-zev-transfer-archive.md`.

## 5. Access helpers (`backend/zev/access.py`)

`can_manage`/`can_view` treat an admin as allowed everywhere; the id-set
helpers return only what the account itself holds, so callers filtering by
them check `user.is_admin` first. An anonymous user is allowed nowhere.
Results are memoised on the user instance (`user._zev_access_cache`), so one
request performs at most one grant query and one participant query. The memo
is keyed by the civil day and by a module generation counter that
`bump_generation` increments on every `post_save`/`post_delete` of a
`ZevAccessGrant` or `Participant` (connected in `zev.apps.ZevConfig.ready`), so
a user object that outlives one request (a test client's forced user, a task)
never answers from stale rows; `invalidate(user)` drops it outright. Bulk
`QuerySet.update`/`delete` on those models bypass the signals — call
`bump_generation()` after them.

| Function | Returns |
|---|---|
| `managed_zev_ids(user) -> frozenset[UUID]` | ZEVs with an active `manager` grant |
| `viewable_zev_ids(user) -> frozenset[UUID]` | ZEVs with an active `manager` or `viewer` grant |
| `participant_zev_ids(user, *, include_ended=False) -> frozenset[UUID]` | ZEVs of the account's participant rows (live rows only unless `include_ended`) |
| `can_manage(user, zev) -> bool` | admin, or `zev.pk in managed_zev_ids(user)` |
| `can_view(user, zev) -> bool` | admin, or `zev.pk in viewable_zev_ids(user)` |
| `active_grants(user)` | queryset of active grants (for `/auth/me`) |
| `live_participant_q(prefix="") -> Q` | participant rows that are still current (see below) |
| `sync_owner_grant(zev, previous_owner_id=None)` | §4.7 |
| `ensure_a_manager(zev)` | `sync_owner_grant(zev)` only when the ZEV has no active manager grant at all (§4.8) |
| `revoke(grant, *, today=None)` / `change_role(grant, role, *, by=None)` | §4.2; `revoke` leaves an already-ended grant alone |
| `is_last_manager(grant) -> bool` | the grant is `manager` and no other active manager grant exists on its ZEV |
| `invalidate(user)` | drop the per-request memo after a write |

`zev` arguments accept a `Zev`, a `UUID` or an id string (as query parameters
carry it); anything that is not a UUID is treated as no access.

A participant row is **live** when `valid_to is null or valid_to >= today`.
Future-dated rows count as live (unchanged from today, so onboarding before the
start date keeps working).

## 6. Scoping and permissions

### 6.1 `ZevScopedQuerySetMixin` (`backend/zev/scoping.py`)

Class attributes after the change:

| Attribute | Meaning |
|---|---|
| `zev_lookup: str` | ORM path from the model to its `Zev` (`""` for `ZevViewSet`). Declared directly; replaces `zev_owner_filter`, from which it used to be derived |
| `participant_path: str \| None` | ORM path from the model to `Participant` (e.g. `"participant"`, `"assignments__participant"`, `""` for `ParticipantViewSet`). `None` = a participant link reveals nothing (manager-only resource). Replaces `participant_filter` (a path to the user). `ZevViewSet` sets `None`: a ZEV record (settings, bank details, templates) is readable only through a grant — participants were always refused there, and an account that manages one ZEV and rents in another must not read the other's record through its link |
| `participant_distinct: bool` | unchanged |
| `participant_visible: Q \| None` | unchanged (#861); `InvoiceViewSet` sets `sent_to_participant()` |
| `participant_access_survives_end: bool = False` | when `True`, ended participant rows still grant access (subject to `participant_visible`). Only `InvoiceViewSet` sets it |
| `viewer_allowed_actions: frozenset[str] = frozenset()` | action names that are unsafe HTTP methods but reads, allowed for viewers (`InvoiceViewSet`: `{"download_pdfs"}`) |
| `scope_parent_path` | unchanged |

**Read rule** (`_scope_by_relation`, replaces `_scope_by_role`):

```
if user.is_admin: return qs
if is_write_request():            # unsafe method, action not in viewer_allowed_actions
    return filter(_zev_in(managed_zev_ids(user)))
condition = _zev_in(viewable_zev_ids(user))
participant = _participant_q(user)  # None when participant_path is None
if participant is not None:
    condition |= participant
return filter(condition)            # .distinct() when participant_distinct

_participant_q(user):
    p = f"{participant_path}__" if participant_path else ""
    q = Q(**{f"{p}user": user}) & _not_disabled_q()
    if not participant_access_survives_end:
        q &= live_participant_q(p)
    if participant_visible is not None:
        q &= participant_visible
    return q
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

`MeterReadingViewSet` overrides `_scope_by_relation` only to alias
`reading_day` (`TruncDate("timestamp", tzinfo=business_tz())`) and
`_participant_q` to return its assignment-window `Exists` (holder, both window
bounds on the same assignment, current participant row) and the disabled-ZEV
exclusion; the grant branch and the union come from the mixin. Its
`participant_path` (`"metering_point__assignments__participant"`) only marks
the resource as reachable by participants.

### 6.2 Permission classes

`zev.permissions.BaseZevScopedPermission`:

- `has_permission`: authenticated and (admin, or `may_hold_management_access`,
  or safe method and (`allow_participant_safe_methods` or viewable ZEVs
  non-empty), or unsafe method and `managed_zev_ids` non-empty). As before,
  `allow_participant_safe_methods` admits safe methods without a participant row
  (an account with nothing gets an empty list from `MeteringPointViewSet`).
- `has_object_permission`: admin → allow. Resolve the ZEV (`_get_zev`, unchanged).
  Disabled ZEV and unsafe method → admin only (unchanged). Unsafe → `can_manage`.
  Safe → `can_view`, or (`allow_participant_safe_methods` and a live participant
  link in that ZEV).
- `ZevManagementPermission`: POST stays admin-only.
- `ZevDisablePermission`: `can_manage(user, zev)` (was `zev.owner == user`).

`accounts.permissions.IsZevOwnerOrAdmin` is renamed `HasZevAccess` (§3); every
use is replaced. `HasZevReadAccess` (a `HasZevAccess` that treats every request
as a read) guards the MCP endpoint, which is POST-only but read-only (ADR 0025),
so a viewer may use it.

**Transitional role gate.** `accounts.permissions.may_hold_management_access(user)`
is `role == "zev_owner"`. It lets such an account pass the coarse gates
(`HasZevAccess`, `BaseZevScopedPermission.has_permission`, `CanViewAuditEvents`,
the dashboard resolver, the reports self-service rule, `self_setup`) before it
holds a grant — a self-registered owner who has not finished setup gets empty
lists, not 403s, exactly as before. It never widens which rows are visible
(those are scoped by grants) and disappears with the role collapse (step 7).

### 6.3 Hand-written checks replaced

| Site | Old | New |
|---|---|---|
| `invoices/views.py` `destroy`, `generate`, `generate_all` | `is_zev_owner`, `zev.owner != request.user` | `can_manage` |
| `invoices/views.py` `_get_period_invoices` (shared by `approve_all`, `send_all`, `generate_pdfs_all`, `download_pdfs`) | `zev.owner != request.user` | its existing `require_active` flag already separates the batch writes (`True`) from the one read, `download_pdfs` (`False`): `can_manage` for the former, `can_view` for the latter |
| `invoices/views.py` `period_overview` | `zev.owner_id != request.user.id` | `can_view` |
| `invoices/views_readiness.py` `_resolve_zev` | `zev.owner_id != user.id` | `can_view` |
| `invoices/views_reports.py` `_get_authorised_zev` | `zev.owner != user` | `can_view` |
| `invoices/views_reports.py` `_is_self_service` / `_own_participant` | `role == PARTICIPANT` | `_self_service(request) -> (bool, participant)`, §7.8 |
| `exports/views.py` create, status, download, list | `zev.owner != user`, `zev__owner=user` | `can_view` / `zev_id__in=viewable_zev_ids` (exports are reads) |
| `tariffs/views_import.py` | `zev.owner_id != user.id` | `can_manage` |
| `tariffs/views.py` `DynamicTariffSourceViewSet._require_source_reader` (price history) | `tariffs.filter(zev__owner=user)` | `tariffs.filter(zev_id__in=viewable_zev_ids)` (a read; source writes stay admin-only) |
| `metering/views.py` `_resolve_import_target_zev` (import, preview) | `zev.owner != user` | `can_manage` |
| `metering/views.py` `dashboard_summary`, `hourly_profile` | `role == "zev_owner"`, `owner=user` | `_resolve_dashboard_scope`, §6.4 |
| `metering/views.py` `data_quality_status` | `is_zev_owner`, `zev__owner=user` | meters of viewable ZEVs ∪ meters assigned to a current own participant row |
| `metering/views.py` `ImportLogViewSet.get_queryset` | `zev__owner=user` OR `imported_by=user` | reads: viewable ZEVs OR `imported_by=user`; deletes (incl. bulk): managed ZEVs OR own logs without a ZEV |
| `metering/importers/csv_importer.py` `_meter_queryset_for_user` | `is_zev_owner`, `zev.owner_id == user.id` | `can_manage` |
| `feasibility/views.py` | `Zev.objects.filter(id=…, owner=user)` | `can_view` |
| `mcp_server/views.py` `_resolve_zev_for_audit` | `Zev.objects.filter(owner=user)` | `can_view` |
| `mcp_server/views.py` `McpView.permission_classes` | `IsZevOwnerOrAdmin` | `HasZevReadAccess` |
| `audit/views.py` `CanViewAuditEvents`, `_base_queryset` | `role == ZEV_OWNER`, `zev__owner=user` | admin, `may_hold_management_access`, or viewable ZEVs non-empty; `zev_id__in=viewable_zev_ids` |
| `zev/views.py` `ParticipantViewSet._contract_pdf_access_denied` | `is_zev_owner` | GET: `can_view` or own participant; POST (issue): `can_manage` |
| `zev/views.py` `self_setup` | `is_zev_owner`; `Zev.objects.filter(owner=user, disabled_at__isnull=True)` | until step 5: admin or `may_hold_management_access`; "already have a ZEV" = an active manager grant on a non-disabled ZEV. §7.6 from step 5 |
| `zev/services.py` `own_participant_for_user(user, zev_id=None)` | first participant row | first **current** row, in `zev_id` when given |
| `zev/serializers.py` `ParticipantSerializer.validate` | `user.role != PARTICIPANT` | unchanged in step 4; removed in step 5 with the link/unlink rework |
| `accounts/serializers.py` `SelfUserSerializer.validate_preferred_zev` | `is_zev_owner`, `value.owner_id != user.pk` | `can_view(user, value)` or any participant row (current or past) in it; message "You can only set a community you belong to as the default." |
| `accounts/models.py` `User.is_zev_owner` | property | removed |

### 6.4 Dashboard summary (`metering/views.py` `dashboard_summary`)

Both `dashboard_summary` and `hourly_profile` decide through
`_resolve_dashboard_scope(user, zev_id)` (`metering/views.py`), where "manages"
means admin, a manager or viewer grant anywhere, or `may_hold_management_access`:

- `?zev_id=` given: `can_view` → community (owner) summary for that ZEV; else a
  current participant row in that ZEV → participant summary for that ZEV only;
  else, for an account that manages anything → 403 `Permission denied for
  selected ZEV.`; for an account that only participates → its participant
  summary across all its current rows, `zev_id` notwithstanding (as before —
  pinned by the regression suite, and it never reveals another ZEV's totals).
- No `zev_id`: an account that manages anything gets the community summary
  when it can see exactly one ZEV (admin: when exactly one exists), else 400
  `zev_id query parameter is required.`; any other account gets its
  participant summary across all its current rows.

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

`AnnualStatementView` and `FinancialSummaryView` decide through
`_self_service(request) -> (is_self_service, participant)`:

1. The caller can view the requested `zev_id` → manager branch
   (`participant_id` required for the statement).
2. The caller manages or views anything (admin, a grant, or
   `may_hold_management_access`) → self-service only when it names a `zev_id`
   in which it holds a current participant row (that row); otherwise the
   manager branch, where naming a ZEV it cannot view is a 403.
3. Any other account is self-service: its current row in the named `zev_id`,
   else — as before per-ZEV grants, when a participant's ids were simply
   ignored — its first current row (`own_participant_for_user`). With no
   current row, a `participant`-role account gets 404 and any other account is
   served by the manager branch (400 without ids); that distinction rests on
   the old role until step 7.

Self-service statements keep `sent_only=True` (#861).

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

Shipped with 25 tests (plus 2 in `backups/test_restore_zev.py`,
`AccessGrantRestoreTests`).

**`ZevAccessGrantModelTests`** (7): one open grant per account and ZEV; a closed
and an open grant may coexist; the window may not end before it starts; revoke
ends the window yesterday; revoking a grant that never took effect deletes it;
revoking an ended grant changes nothing; a role change ends one row and opens
another.

**`AccessHelperTests`** (10): manager/viewer/stranger answers; ids given as
strings work and garbage is refused; an admin may do everything with no grant;
anonymous may do nothing; the id sets; inclusive window bounds and inactive
future grants; `participant_zev_ids` skips ended rows unless asked; future
participant rows count as current; one query per memoised user; `is_last_manager`.

**`OwnerGrantInvariantTests`** (7): creating a ZEV makes its owner manager;
saving without an owner change adds nothing; moving ownership moves the
manager grant; a new owner who was a viewer is promoted; the owner's grant can be
revoked afterwards; `ensure_a_manager` acts only when nobody manages; a
transfer import makes the importer manager.

**`GrantMigrationTests`** (1, `TransactionTestCase`): migrating forward from
`0030` grants every owner, from the creation date even when `start_date` is in
the future.

### Backend — `zev/test_access_scoping.py` (PR 4; 14 tests, shipped)

World: the regression world (`AccessWorldMixin`) plus `acc_viewer` (viewer of
Alpha) and `acc_viewer_manager` (viewer of Alpha, manager of Beta).

**`ViewerTests`** (6): a viewer's lists equal the manager's for every list in
the regression suite; readiness/period overview of its ZEV only, and the
community dashboard; it cannot file a row under Alpha (403 at the gate for a
pure viewer, 400 on the payload for one that manages Beta); `download-pdfs`
(200) and export creation (202) are open to it; it may use the MCP server
(`list_zevs` = Alpha); a disabled Alpha stays readable, refuses writes (viewer
and manager 403) and disappears for its participants.

**`ViewerWriteRouterWalkTests`** (1): walks the URL configuration (every
`api/v1/` route except `auth/`, `public/`, `backups/`, and the declared
read-only POSTs `invoice-download-pdfs`, `export-job-create`,
`feasibility-calculate`, `mcp`) and tries every unsafe method with an empty
body, in a rolled-back savepoint, as both accounts. Alpha's rows (ZEV,
participants, meters, assignments, tariffs, periods, invoices, readings, import
logs, grants) must be unchanged after every attempt, and the pure viewer must
never get a 2xx. More than 100 attempts. With the write rule disabled it fails
on tariff edits/deletes, reading deletes and invoice approve/cancel/PDF/send.

**`MultiRelationshipScopingTests`** (4): a tenant in two ZEVs sees both
ZEVs' sent invoices and meters; an owner of Alpha who rents in Beta sees all of
Alpha plus its own Beta invoice (not Beta's draft), only Alpha's ZEV record, no
Beta tariffs, cannot write its Beta participant row (404), gets the participant
dashboard for `zev_id=Beta` and its own Beta statement (`sent_only=True`); a
manager of two ZEVs sees and edits both and must name one on the dashboard
(400); a manager who is also a participant of the same ZEV sees its unsent
invoices through the grant.

**`FormerParticipantTests`** (3): with the row ended yesterday the tenant keeps
its sent invoice (list and detail) and loses meters, community dashboard totals
and the self-service statement (404); a current row elsewhere keeps that ZEV.

Existing tests adjusted in PR 4: `zev/test_scoping.py` (new attribute names,
fake request carries a method); `accounts/tests.py` `test_user_role_helpers`
and `testing/test_factories_smoke.py` (no `is_zev_owner`; the factory owner can
manage its ZEV); `exports/tests.py` "lost ownership" changes `owner` through
`save()` so the grant moves; two time-travel tests
(`invoices/test_dynamic_tariff_pricing.py`, `tariffs/test_dynamic_source_link_api.py`)
backdate the owner grant before patching "today" into the past.

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
