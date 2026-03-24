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

- User model with role-based access (`admin`, `zev_owner`, `participant`,
  `guest`)
- Authentication (JWT via SimpleJWT), self-registration, email verification,
  password management, impersonation
- ZEV CRUD and owner lifecycle (creation wizard, self-setup, owner transfer)
- Participant master data CRUD and account lifecycle (auto-creation, invitation,
  link/unlink)
- Metering point and assignment CRUD (covered in depth in
  `2026-03-metering-point-management.md`)
- Frontend route protection and navigation visibility
- Global ZEV selector for admin / owner scoping (ManagedZevProvider)

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
| `role` | `CharField(20)` choices `UserRole` | `admin`, `zev_owner`, `participant`, `guest` (default `participant`) |
| `must_change_password` | `BooleanField` (default `False`) | Set `True` on admin-created or invitation-created accounts |
| `is_active` | `BooleanField` | `False` until email verification for self-registered users |

**Computed properties:**

| Property | Logic |
|---|---|
| `is_admin` | `role == 'admin'` OR `is_superuser` |
| `is_zev_owner` | `role in ('admin','zev_owner')` OR `is_superuser` |

### 3.2 UserRole enum

| Value | Label |
|---|---|
| `admin` | Admin |
| `zev_owner` | ZEV Owner |
| `participant` | Participant |
| `guest` | Guest |

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
| `owner` | FK → `User` (`PROTECT`) | The owning user account |
| `start_date` | `DateField` | Community start date |
| `zev_type` | `CharField(10)` | `zev` or `vzev` |
| `billing_interval` | `CharField(20)` | `monthly`, `quarterly`, `semi_annual`, `annual` |
| `created_at` | `DateTimeField` (auto) | |
| `updated_at` | `DateTimeField` (auto) | |

**Ordering:** `["name"]`.

### 3.5 Participant

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `zev` | FK → `Zev` (`CASCADE`) | Parent community |
| `user` | FK → `User` (`SET_NULL`, nullable) | Linked user account (optional) |
| `title` | `CharField(10)` choices `Title` | `mr`, `mrs`, `ms`, `dr`, `prof`, or blank |
| `first_name` | `CharField(100)` | |
| `last_name` | `CharField(100)` | |
| `email` | `EmailField` (blank OK) | Required at API validation level |
| `phone` | `CharField(30)` | |
| `address_line1` | `CharField(200)` | |
| `address_line2` | `CharField(200)` | |
| `postal_code` | `CharField(10)` | |
| `city` | `CharField(100)` | |
| `valid_from` | `DateField` | Start of participation |
| `valid_to` | `DateField` (nullable) | End of participation (open = active) |
| `notes` | `TextField` | |
| `created_at` | `DateTimeField` (auto) | |
| `updated_at` | `DateTimeField` (auto) | |

**Ordering:** `["last_name", "first_name"]`.

**Computed property:** `full_name` → `"{title_display} {first_name} {last_name}"` (stripped).

### 3.6 MeteringPoint and MeteringPointAssignment

Covered in `2026-03-metering-point-management.md`. Relevant to access:
- MeteringPoint has FK → Zev (CASCADE).
- MeteringPointAssignment links a metering point to a participant with
  `valid_from`/`valid_to` range.
- Assignments are constrained within the participant's own validity window.
- Only one active assignment per metering point at a time.

---

## 4. Roles and permission classes

### 4.1 Role hierarchy

```
admin  →  global access, all CRUD, configuration, impersonation
zev_owner  →  own-ZEV scoped management (participants, metering, tariffs, invoices, imports)
participant  →  self-scoped read access (own metering points, own invoices, dashboard, profile)
guest  →  authenticated but no domain access (transitional state after unlink)
```

### 4.2 Backend permission classes

Defined in `accounts/permissions.py` and `zev/permissions.py`.

| Class | Location | Logic |
|---|---|---|
| `IsAdmin` | `accounts` | `user.is_authenticated AND user.is_admin` |
| `IsZevOwnerOrAdmin` | `accounts` | `user.is_authenticated AND user.is_zev_owner` (note: `is_zev_owner` is true for both admin and zev_owner roles) |
| `IsParticipantOrAbove` | `accounts` | `user.is_authenticated` |
| `BaseZevScopedPermission` | `zev` | Base class for ZEV-tenant-aware permissions; checks `has_permission` (role gate) and `has_object_permission` (ZEV ownership check) |
| `ZevManagementPermission` | `zev` | Extends `BaseZevScopedPermission`; POST restricted to admin only |
| `ParticipantManagementPermission` | `zev` | Extends `BaseZevScopedPermission`; no participant safe-method override |
| `MeteringPointPermission` | `zev` | Extends `BaseZevScopedPermission`; `allow_participant_safe_methods = True` |
| `MeteringPointAssignmentPermission` | `zev` | Extends `BaseZevScopedPermission`; no participant safe-method override |

### 4.3 BaseZevScopedPermission detail

**`has_permission(request, view)`:**
1. Not authenticated → deny.
2. `admin` or `zev_owner` → allow.
3. If `allow_participant_safe_methods` and method is safe → allow.
4. Else → deny.

**`has_object_permission(request, view, obj)`:**
1. `admin` → allow.
2. Resolve `zev` from the object graph (Zev, Participant, MeteringPoint,
   MeteringPointAssignment).
3. `zev_owner` and `zev.owner == user` → allow.
4. If `allow_participant_safe_methods` and method is safe → allow if
   `zev.participants.filter(user=user).exists()`.
5. Else → deny.

---

## 5. Authentication and account lifecycle

### 5.1 JWT authentication

**Token endpoint:** `POST /api/v1/auth/token/`

Custom `TokenObtainPairSerializer` embeds in the token:

| Claim | Value |
|---|---|
| `role` | `user.role` |
| `email` | `user.email` |
| `full_name` | `user.get_full_name()` |
| `must_change_password` | `user.must_change_password` |

**Token refresh:** `POST /api/v1/auth/token/refresh/` (standard SimpleJWT).

**Frontend storage:** `localStorage` keys `openzev.access` and `openzev.refresh`.
Axios interceptor attaches `Authorization: Bearer {access}` to all API requests.

### 5.2 Self-registration (zev_owner)

**Endpoint:** `POST /api/v1/auth/register/` (AllowAny)

**Payload:** `{ username, email }`

**Flow:**
1. Validate uniqueness of `username` and `email` (case-insensitive for email).
2. Create `User` with `role=zev_owner`, `is_active=False`,
   `must_change_password=True`, unusable password.
3. Generate `EmailVerificationToken` (48-byte `token_urlsafe`).
4. Send verification email with link `{FRONTEND_URL}/verify-email?token={token}`.
5. Return `201` with `"Verification email sent."`.

### 5.3 Email verification

**Endpoint:** `POST /api/v1/auth/verify-email/` (AllowAny)

**Payload:** `{ token }`

**Flow:**
1. Look up `EmailVerificationToken` by token value.
2. Validate not consumed and within 24h expiry.
3. Mark token as consumed (`consumed_at = now`).
4. Activate user (`is_active = True`).
5. Issue JWT tokens (access + refresh) for auto-login.

### 5.4 Initial password set

**Endpoint:** `POST /api/v1/auth/me/set-initial-password/` (IsAuthenticated)

**Payload:** `{ new_password }`

**Guard:** only allowed if `must_change_password == True` or user has no usable
password. Otherwise returns 400 ("Use the change-password endpoint instead.").

**Flow:**
1. Validate password via Django password validators.
2. Set password, clear `must_change_password` flag.
3. Return fresh JWT tokens.

### 5.5 Password change

**Endpoint:** `POST /api/v1/auth/me/change-password/` (IsAuthenticated)

**Payload:** `{ old_password, new_password }`

Validates old password, sets new password, clears `must_change_password`.

### 5.6 Profile (me)

**Endpoint:** `GET | PATCH /api/v1/auth/me/` (IsAuthenticated)

- GET → returns `UserSerializer` of current user.
- PATCH → partial update of own profile fields (name, email). Role change
  validation: admin cannot change own role; non-admin cannot change role at all.

### 5.7 Impersonation

**Endpoint:** `POST /api/v1/auth/users/{user_id}/impersonate/` (IsAuthenticated)

**Permission:** admin only (`request.user.is_admin`).

**Allowed targets:** users with role `participant` or `zev_owner`. Attempting to
impersonate an admin returns 400.

**Flow:**
1. Generate a new JWT refresh token for the target user.
2. Embed `impersonated_by = request.user.id` in the token claims.
3. Return `{ access, refresh, impersonated_user, impersonator }`.

**Frontend flow (`AuthContext.startImpersonation`):**
1. Save current tokens to `openzev.impersonation.original_*` localStorage keys.
2. Store impersonator user in `openzev.impersonation.impersonator`.
3. Replace active tokens with the impersonated user's tokens.
4. Re-fetch `/auth/me/` to update the UI context.

**Stop impersonation:** restore original tokens, clear impersonation keys,
re-fetch `/auth/me/`.

### 5.8 Forced password change redirect

`ProtectedRoute` checks: if `user.must_change_password` is true and the user is
not impersonating and the current path is not `/account`, redirect to
`/account` with `state.forcePasswordChange = true`.

---

## 6. User management (admin)

### 6.1 User list

**Endpoint:** `GET /api/v1/auth/users/` (IsAuthenticated)

**Queryset scoping:**
- `admin` → all users, ordered by username.
- `zev_owner` → only `participant` role users that are active.
- Other roles → 403 (PermissionDenied).

### 6.2 User create

**Endpoint:** `POST /api/v1/auth/users/` (IsAuthenticated; admin only in view logic)

**Payload:** `{ username, email, first_name, last_name, password, password2, role }`

Admin only. Passwords must match. Created via `User.objects.create_user()`.

### 6.3 User detail

**Endpoint:** `GET | PATCH | DELETE /api/v1/auth/users/{id}/` (IsAdmin)

- PATCH: `UserSerializer` partial update. Role-change safety:
  - Admin cannot change own role away from admin.
  - Non-admin cannot change any role.
- DELETE: blocked if user has linked participant records
  (`instance.participations.exists()` → 403 "Linked participant accounts
  cannot be deleted.").

---

## 7. ZEV management

### 7.1 ZEV viewset

**URL prefix:** `/api/v1/zev/zevs/`
**Permission:** `[IsAuthenticated, ZevManagementPermission]`

**Queryset scoping:**
- `admin` → all ZEVs.
- `zev_owner` → ZEVs where `owner == user`.
- `participant` → ZEVs where user is linked to any participant in that ZEV.

**Create (POST):** admin only (enforced in `create()` and
`ZevManagementPermission.has_permission`).

**Serializer:** `ZevSerializer` (all fields). Retrieve uses `ZevDetailSerializer`
which nests `participants` (via `ParticipantSerializer`, many=True, read-only).

**Owner assignment on create:** if `owner` not in validated data, defaults to
`request.user`.

**Owner transfer on update:** `ZevSerializer.update()` syncs roles:
- If new owner is not already admin or zev_owner → promote to `zev_owner`.
- If previous owner no longer owns any ZEV and is not superuser → demote to
  `participant`.

### 7.2 Create-with-owner wizard

**Endpoint:** `POST /api/v1/zev/zevs/create-with-owner/` (admin only)

**Payload:** `ZevCreateWithOwnerSerializer`:
```json
{
  "name": "...",
  "start_date": "...",
  "zev_type": "vzev",
  "billing_interval": "monthly",
  "grid_operator": "...",
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

**Service:** `create_zev_with_owner_setup()` (atomic transaction):
1. Generate unique username (email-local → full-name → first-name fallback, suffix if taken).
2. Create `User` with `role=zev_owner`, `must_change_password=True`, temporary password.
3. Create `Zev` with that user as owner.
4. Create owner `Participant` with `valid_from = zev.start_date`.
5. Create each `MeteringPoint` → create `MeteringPointAssignment` to owner participant.
6. Return `{ zev: {id, name}, owner: {id, username, temporary_password}, owner_participant_id, metering_points: [{id, meter_id}] }`.

### 7.3 Self-setup

**Endpoint:** `POST /api/v1/zev/zevs/self-setup/` (IsAuthenticated, zev_owner only)

For self-registered users who have completed email verification and password
setup. Creates a ZEV + owner Participant in one step.

**Guards:**
- User must be `zev_owner`.
- User must not already own a ZEV.

**Service:** `create_zev_for_existing_owner()` → creates Zev + Participant.

---

## 8. Participant management

### 8.1 Participant viewset

**URL prefix:** `/api/v1/zev/participants/`
**Permission:** `[IsAuthenticated, ParticipantManagementPermission]`

**Queryset scoping:**
- `admin` → all participants (with prefetched assignments).
- `zev_owner` → participants where `zev.owner == user`.
- `participant` → only own record(s) where `user == request.user`.

### 8.2 Participant create

**Serializer:** `ParticipantSerializer` with auto-account creation.

On create:
1. Validate `email` is present (required at serializer level).
2. Reject if `user` field is passed directly (accounts are created
   automatically).
3. Call `ensure_participant_account()`:
   - Generates unique username from participant name/email.
   - Creates `User` with `role=participant`, `must_change_password=True`,
     temporary 12-char password.
   - Links user to participant.
4. Return participant data including `account_username` and `initial_password`.

On update:
1. Sync linked user's `email`, `first_name`, `last_name`, `role` via
   `sync_participant_user_fields()`.

### 8.3 Participant actions

| Action | URL | Method | Permission | Description |
|---|---|---|---|---|
| Send invitation | `/{id}/send-invitation/` | POST | admin + zev_owner | Reset password, send invitation email |
| Contract PDF | `/{id}/contract-pdf/` | GET | authenticated (self or admin/owner) | Generate and stream participation contract PDF |
| Link account | `/{id}/link-account/` | POST | admin only | Link existing user account (participant or guest role only, not already linked elsewhere) |
| Unlink account | `/{id}/unlink-account/` | POST | admin only | Unlink account, demote user to `guest` role. Blocked if user is the ZEV owner. |
| Create account | `/{id}/create-account/` | POST | admin only | Create new user account and link to participant |

### 8.4 Invitation email flow

`send_participant_invitation()` (atomic):
1. Ensure account exists via `ensure_participant_account()`.
2. Generate new temporary password (12 chars).
3. Set `must_change_password = True`.
4. Send email with username + temporary password to participant email.
5. Return `(username, temporary_password)`.

---

## 9. Frontend routing and access control

### 9.1 ProtectedRoute component

`ProtectedRoute({ children, allowedRoles? })`:
1. If loading → show loading indicator.
2. If not authenticated → redirect to `/login`.
3. If `must_change_password` and not impersonating and not on `/account` →
   redirect to `/account`.
4. If `allowedRoles` specified and user role not in list → redirect to `/`.
5. Otherwise → render children.

### 9.2 Route → role mapping

| Route | Allowed roles | Page component |
|---|---|---|
| `/` | any authenticated | `DashboardPage` |
| `/account` | any authenticated | `AccountProfilePage` |
| `/admin` | `admin` | `AdminDashboardPage` |
| `/admin/settings/regional` | `admin` | `AdminRegionalSettingsPage` |
| `/admin/settings/vat` | `admin` | `AdminVatSettingsPage` |
| `/admin/pdf-templates` | `admin` | `AdminPdfTemplatesPage` |
| `/admin/accounts` | `admin` | `AdminAccountsPage` |
| `/admin/zevs` | `admin` | `ZevListPage` |
| `/participants` | `admin`, `zev_owner` | `ParticipantsPage` |
| `/zev-settings` | `admin`, `zev_owner` | `ZevSettingsPage` |
| `/metering-points` | any authenticated | `MeteringPointsPage` |
| `/metering-data` | any authenticated | `MeteringChartPage` |
| `/tariffs` | `admin`, `zev_owner` | `TariffsPage` |
| `/invoices` | `admin`, `zev_owner` | `InvoicesPage` |
| `/invoices/:invoiceId` | any authenticated | `InvoiceDetailPage` |
| `/imports` | `admin`, `zev_owner` | `ImportsPage` |
| `/login` | public | `LoginPage` |
| `/verify-email` | public | `VerifyEmailPage` |

### 9.3 Navigation visibility

The sidebar (`Layout.tsx`) shows sections conditionally:

| Section | Condition |
|---|---|
| Dashboard | always |
| Manage (v)Zev group (participants, metering points, metering data, ZEV settings) | `canManage` = `role == 'admin' \|\| role == 'zev_owner'` |
| Tariffs | `canManage` |
| Invoices | `canManage` |
| Imports | `canManage` |
| Admin Console group (overview, ZEV list, accounts, regional settings, VAT, PDF templates) | `role == 'admin'` |

### 9.4 ManagedZevProvider (global ZEV context)

`ManagedZevProvider` provides the active ZEV context for all management pages.

**Behaviour:**
- Fetches ZEV list only if `canManageZev` (admin or zev_owner).
- `admin` → all ZEVs; can switch via dropdown (`isSelectable = true`).
- `zev_owner` → only owned ZEVs; auto-selects first owned ZEV
  (`isSelectable = false`).
- `participant` / `guest` → empty list, no selection.
- Persists selected ZEV ID in `localStorage` key `openzev.selectedZevId`.
- Auto-fallback: if stored ID is no longer valid, select first available ZEV.

---

## 10. API endpoint summary

### 10.1 Auth endpoints (`/api/v1/auth/`)

| Method | URL | Permission | Description |
|---|---|---|---|
| POST | `/token/` | AllowAny | JWT login (returns access + refresh tokens) |
| POST | `/token/refresh/` | AllowAny | JWT token refresh |
| POST | `/register/` | AllowAny | Self-register a zev_owner account |
| POST | `/verify-email/` | AllowAny | Consume verification token, activate user |
| GET / PATCH | `/me/` | IsAuthenticated | View/update own profile |
| POST | `/me/change-password/` | IsAuthenticated | Change password (requires old password) |
| POST | `/me/set-initial-password/` | IsAuthenticated | Set password for first time (verification flow) |
| GET / POST | `/users/` | IsAuthenticated (create: admin only) | List users (scoped by role) / Create user |
| GET / PATCH / DELETE | `/users/{id}/` | IsAdmin | User detail (delete blocked if linked) |
| POST | `/users/{user_id}/impersonate/` | IsAuthenticated (admin only) | Impersonate participant/owner |
| GET / PATCH | `/app-settings/` | IsAuthenticated (update: admin only) | Application settings singleton |
| GET / POST | `/vat-rates/` | IsAdmin | VAT rate management |
| GET / PATCH / DELETE | `/vat-rates/{id}/` | IsAdmin | VAT rate detail |

### 10.2 ZEV endpoints (`/api/v1/zev/`)

| Method | URL | Permission | Description |
|---|---|---|---|
| GET / POST | `/zevs/` | IsAuthenticated, ZevManagementPermission (create: admin only) | List/create ZEVs |
| GET / PATCH / PUT / DELETE | `/zevs/{id}/` | IsAuthenticated, ZevManagementPermission | ZEV detail (retrieve uses ZevDetailSerializer with nested participants) |
| POST | `/zevs/create-with-owner/` | IsAuthenticated, ZevManagementPermission (admin only) | Wizard: create ZEV + owner + metering points |
| POST | `/zevs/self-setup/` | IsAuthenticated | Self-setup: create ZEV for self-registered owner |
| GET / POST | `/participants/` | IsAuthenticated, ParticipantManagementPermission | List/create participants |
| GET / PATCH / PUT / DELETE | `/participants/{id}/` | IsAuthenticated, ParticipantManagementPermission | Participant detail |
| POST | `/participants/{id}/send-invitation/` | admin + zev_owner | Send invitation email |
| GET | `/participants/{id}/contract-pdf/` | IsAuthenticated | Download participation contract PDF |
| POST | `/participants/{id}/link-account/` | admin only | Link user account to participant |
| POST | `/participants/{id}/unlink-account/` | admin only | Unlink user account from participant |
| POST | `/participants/{id}/create-account/` | admin only | Create + link user account |
| GET / POST | `/metering-points/` | IsAuthenticated, MeteringPointPermission | List/create metering points |
| GET / PATCH / PUT / DELETE | `/metering-points/{id}/` | IsAuthenticated, MeteringPointPermission | Metering point detail |
| GET / POST | `/metering-point-assignments/` | IsAuthenticated, MeteringPointAssignmentPermission | List/create assignments |
| GET / PATCH / PUT / DELETE | `/metering-point-assignments/{id}/` | IsAuthenticated, MeteringPointAssignmentPermission | Assignment detail |

---

## 11. Queryset scoping matrix

All domain viewsets enforce tenant scoping at the queryset level. This is the
backend's primary access control mechanism.

| Resource | admin | zev_owner | participant | guest |
|---|---|---|---|---|
| Zev | all | `owner == user` | ZEVs where user is a linked participant | — |
| Participant | all | `zev.owner == user` | `user == request.user` | — |
| MeteringPoint | all | `zev.owner == user` | assigned via MeteringPointAssignment | — |
| MeteringPointAssignment | all | `metering_point.zev.owner == user` | `participant.user == user` | — |
| User (list) | all | active participants only | PermissionDenied | PermissionDenied |
| ImportLog | all | `zev.owner == user` OR `imported_by == user` | PermissionDenied | PermissionDenied |
| MeterReading | all | ZEV-scoped meters | assigned meters | PermissionDenied |
| Invoice | all | `zev.owner == user` | `participant.user == user` | — |

---

## 12. RBAC endpoint access matrix (tested)

The `RbacEndpointMatrixTests` test class verifies this matrix:

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
`must_change_password`, `is_active`, `date_joined`.
**Read-only:** `id`, `date_joined`.

**Role-change validation:**
- Admin cannot change own role (from admin to anything else).
- Non-admin cannot change any role at all.

### 13.2 UserCreateSerializer

**Fields:** `username`, `email`, `first_name`, `last_name`, `password`,
`password2`, `role`.
**Validation:** passwords must match; password validated via Django validators.

### 13.3 ParticipantSerializer

**Fields:** all model fields plus computed:
- `account_username` (read-only, from linked user)
- `initial_password` (read-only, only present when account is first created)
- `full_name` (read-only)
- `metering_points` (read-only, nested `MeteringPointSerializer`)
- `has_metering_point_assignment` (read-only, boolean)

**Validation:**
- `user` field cannot be set directly ("Participant accounts are created
  automatically.").
- `email` is required (even though the model allows blank).
- If user is already linked, their role must be `participant`.

### 13.4 ZevSerializer / ZevDetailSerializer

`ZevSerializer`: all model fields. Owner assignment defaults to `request.user`.
Owner validation: non-admin cannot assign a different owner.

`ZevDetailSerializer`: extends `ZevSerializer`, adds nested `participants`
(ParticipantSerializer, many=True, read-only).

### 13.5 ZevCreateWithOwnerSerializer

Composite serializer for the creation wizard. Nested:
- `owner`: `ZevOwnerAccountSerializer` (username, name, contact details)
- `metering_points`: `OwnerMeteringPointInputSerializer[]` (min_length=1)

### 13.6 CustomTokenObtainPairSerializer

Extends SimpleJWT's `TokenObtainPairSerializer`. Adds custom claims:
`role`, `email`, `full_name`, `must_change_password`.

---

## 14. Frontend TypeScript types

Key types in `frontend/src/types/api.ts`:

```typescript
type UserRole = 'admin' | 'zev_owner' | 'participant' | 'guest'

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
interface SelfSetupZevInput { name: string; start_date: string; zev_type: 'zev'|'vzev'; billing_interval: string; grid_operator?: string }

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
| `Zev` | `ZevAdmin` | ParticipantInline. List: name, zev_type, owner, billing_interval. Filter: zev_type, billing_interval. Search: name, grid_operator |
| `Participant` | `ParticipantAdmin` | MeteringPointAssignmentInline. List: full_name, zev, email, validity. Filter: zev. Search: name, email |
| `MeteringPoint` | `MeteringPointAdmin` | List: meter_id, zev, meter_type, is_active. Filter: meter_type, is_active. Search: meter_id |

---

## 16. Test plan

### 16.1 Backend test classes

**`accounts/tests.py`** (528 lines, 7 test classes):

| Class | Tests | Description |
|---|---|---|
| `UserModelTests` | 1 | Role helper properties (`is_admin`, `is_zev_owner`) |
| `PasswordChangeFlagTests` | 1 | `must_change_password` cleared on password change |
| `ImpersonationTests` | 4 | Admin can impersonate participant/owner; non-admin blocked; admin cannot impersonate admin |
| `LinkedAccountSafetyTests` | 5 | Admin can edit linked account; cannot delete linked; can delete unlinked; cannot change own role (via both detail and me endpoints) |
| `AppSettingsTests` | 3 | Authenticated user reads settings; admin updates; non-admin cannot update |
| `VatRateSettingsTests` | 4 | Admin CRUD; non-admin blocked; overlap rejection; valid_to validation |
| `RbacEndpointMatrixTests` | 6 | Full list/create/update/action-delete/unauthenticated matrix across all endpoints |

**`zev/tests.py`** (554 lines, 6 test classes):

| Class | Tests | Description |
|---|---|---|
| `ParticipantEndpointRestrictionTests` | 7 | Participant cannot access ZEV/participant lists; can list own metering points; cannot create/update/delete metering points; cannot access assignments |
| `ZevCreationWizardTests` | 2 | Non-admin cannot create ZEV; admin wizard creates ZEV + owner + participant + assignments |
| `ParticipantAccountLifecycleTests` | 3 | Create participant auto-creates account with initial password; update saves contact details; invitation resets password and sends email |
| `ParticipantAccountLinkingTests` | 5 | Admin can link/unlink accounts; rejects double-linking; admin can create-and-link; non-admin cannot link/create |
| `ZevOwnerRoleSyncTests` | 1 | Owner transfer promotes new owner, demotes previous |
| `MeteringPointAssignmentValidationTests` | 9 | Unique assignment, no overlaps, historical OK, open-end blocks future, dates within participant window, self-update OK |

### 16.2 Frontend

- `npm run build` verifies type-safety and route correctness.
- `ProtectedRoute` handles loading, unauthenticated, forced password change,
  and role gating.

---

## 17. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope leakage across ZEV boundaries | High | Backend queryset scoping per role; `BaseZevScopedPermission` object-level checks; regression test matrix |
| UI-only enforcement drift | High | Backend always enforces permissions; frontend guards are UX convenience only (ADR 0003) |
| Assignment validity edge cases | Medium | Date-boundary tests; serializer + model double validation; ADR 0001 rules |
| Impersonation abuse | High | Admin-only guard; cannot impersonate other admins; impersonation state tracked in JWT claims and localStorage |
| Self-registration spam | Medium | Email verification required; unusable password until verified |
| Linked account deletion | Medium | Delete blocked if `participations.exists()`; `SET_NULL` FK prevents cascade |

---

## 18. Acceptance criteria

1. User model supports `admin`, `zev_owner`, `participant`, `guest` roles with
   correct `is_admin` / `is_zev_owner` computed properties.
2. JWT tokens embed `role`, `email`, `full_name`, `must_change_password`.
3. Self-registration creates inactive `zev_owner`, sends verification email,
   and auto-logs in on verification.
4. `must_change_password` flag redirects to profile; cleared on password change
   or set-initial-password.
5. Admin can impersonate participants/owners but not other admins.
6. All domain viewsets scope querysets by role and ZEV ownership.
7. `BaseZevScopedPermission` enforces object-level ZEV ownership checks.
8. Participant creation auto-provisions a linked user account with temporary
   password.
9. Account linking is admin-only; unlink demotes to `guest`; delete blocked for
   linked accounts.
10. ZEV creation wizard atomically creates ZEV + owner user + owner participant
    + metering points + assignments.
11. Owner transfer promotes new owner and demotes previous owner if they no
    longer own any ZEV.
12. Frontend `ProtectedRoute` enforces role-based route access; navigation
    visibility matches role capabilities.
13. `ManagedZevProvider` scopes all management pages to the selected ZEV.
14. Full RBAC matrix (list, create, update, delete, unauthenticated) is covered
    by automated tests.
