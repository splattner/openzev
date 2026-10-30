# Feature Spec: Tokens & keys — one place to see and manage credentials

- Spec ID: SPEC-2026-tokens-and-keys
- Status: In Progress
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-17
- Target Release: 1.27
- Related Issues: follow-up to [#1058](https://github.com/splattner/openzev/issues/1058) (analytics tokens had no UI)
- Related specs: [analytics dataset API](2026-10-analytics-dataset-api.md), [supplementary energy data](2026-10-supplementary-energy-data.md), [admin governance](2026-03-admin-governance-and-settings.md), [community and access](2026-03-community-and-access.md)
- Related ADRs: [ADR 0039](../adr/0039-analytics-through-a-scoped-dataset-api.md), [ADR 0031](../adr/0031-integration-credentials-encrypted-under-a-dedicated-key.md)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

OpenZEV has three kinds of bearer credential, each with its own model, prefix and screen (or none):

| | API key | Energy data (push) token | Analytics token |
|---|---|---|---|
| Prefix | `ozv_` | `ozs_` | `oza_` |
| Acts as | the user, with their permissions | one source (anonymous), delivers readings | the creator, narrowed to one ZEV or participant |
| Access | read, or read and write (`read_only` narrows) | write only: readings into one metering point | read only: the analytics series |
| Lifecycle | standalone | bound 1:1 to a `SupplementarySource`; issued with it, rotated, dropped by disconnect | standalone |
| Expiry, last used | yes, yes | no, no | yes, yes |
| UI before this spec | Account → API keys; admin list | inside the source card | none (API only) |

A user cannot answer "which credentials of mine exist, what can each do, which did I forget?" without visiting
three places, and analytics tokens have no screen at all.

Outcome: one **Tokens & keys** tab on the account page lists all three kinds with the same columns, status and
revoke action, and creates API keys and analytics tokens. Energy data tokens are listed there, but are
created with their source, because a token cannot exist without a metering point and a provider. The admin
console gets the same overview across users. The three models stay as they are.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Aggregator | `GET /api/v1/auth/me/credentials/` (own) and `GET /api/v1/auth/credentials/` (admin: all users), normalized rows (§5) |
| Energy token metadata | `push_token_created_at`, `push_token_last_used_at` on `SupplementarySource`; new action `revoke-push-token` (§4, §6) |
| Analytics token privacy | an analytics token is visible to its creator only (and, for oversight, to admins); managers no longer see participants' tokens (§3) |
| Account UI | tab `api-keys` becomes `tokens` ("Tokens & keys"), unified list, filter chips, create forms for API key and analytics token, shared one-time secret panel (§7) |
| Admin UI | the "API keys" tab of the Accounts hub becomes "Tokens & keys", all three kinds, user/type/status filters (§7.4) |
| Docs | user guide (16, 20, 21), baseline and feature specs (§10) |

### Out of scope

- Merging the three models or prefixes, or one creation wizard (an energy token needs its source).
- Expiry for energy push tokens (`null` is shown as "no expiry"). Devices already pushing must not start failing.
- Managers or admins creating tokens for others in the UI (the analytics API still allows a manager to create a
  participant-scoped token; the UI offers own tokens only).
- Listing other people's tokens to managers. A manager still sees *sources* of their ZEVs in the energy data UI.
- Changing how any token authenticates.

## 3. Actors, permissions, and visibility

| Actor | Own list (`/auth/me/credentials/`) | Admin list (`/auth/credentials/`) |
|---|---|---|
| any signed-in account (session) | the account's API keys, the analytics tokens it created, the push tokens of sources whose participant is linked to the account, and, for a manager, the push tokens of ZEV-held sources in the ZEVs they manage (SPEC-2026-live-energy-data §3) | `403` |
| `admin` | same as above | every API key, analytics token and push token, with owner |
| API key, analytics token, push token | `401`: only a session authenticates (`CookieJWTAuthentication` is the one authentication class), so a credential cannot enumerate credentials | same |

**Analytics tokens are private to their creator.** `AnalyticsTokenViewSet.get_queryset` returns the caller's own
non-revoked tokens, or all non-revoked tokens for an admin. The earlier rule that a ZEV manager sees and
revokes tokens of their ZEV is removed: a participant's token is their own business, and a manager has no need
for it (a manager can already read everything in the ZEV, and an account losing its access takes its tokens
with it, SPEC-2026-analytics-dataset-api §8). Admin oversight is kept, as for API keys.

Creating a credential is unchanged *for an ordinary session*: API key by any session, analytics
token by the rules of `analytics.scope.can_create_token`, push token with a source. An
impersonation session is refused all three (`403`): each one outlives the impersonation
(`SPEC-2026-10-account-creation-and-sign-in` §5.10). Revocation remains available for all three kinds.

## 4. Data model

### 4.1 `metering.SupplementarySource` (migration `metering/00xx`)

| Field | Type | Default | Meaning |
|---|---|---|---|
| `push_token_created_at` | DateTime, null | `None` | when the current push token was issued; set by `issue_push_token()`, cleared with the token. Existing tokens stay `null` (shown as "—") |
| `push_token_last_used_at` | DateTime, null | `None` | last accepted authentication of the token, rewritten at most every `API_KEY_LAST_USED_RESOLUTION` (as `ApiKeyAuthentication._touch`) |

`SupplementarySourceSerializer` gains both as read-only fields. New method `revoke_push_token()` (not saving)
clears `push_token_prefix`, `push_token_hash` and both timestamps; `clear_credential()` and `issue_push_token()`
keep them consistent.

No other model changes. The `ApiKey` and `AnalyticsToken` models are untouched.

### 4.2 Aggregated row (not stored)

```jsonc
{
  "kind": "api_key" | "analytics" | "energy_push",
  "id": "<uuid>",
  "name": "…",                       // api_key/analytics: name; energy_push: source label or "Energy data <meter id>"
  "prefix": "ozv_3f9a1c04b7e2",      // namespace + prefix, never the secret
  "access": "read_write" | "read_only" | "read" | "write_readings",
  "held_by": "account" | "zev",      // zev: push token of a ZEV-held energy data source (no participant)
  "scope": {                         // all keys always present, null when not applicable
    "zev": "<uuid>" | null, "zev_name": "…" | null,
    "participant": "<uuid>" | null, "participant_name": "…" | null,
    "metering_point": "<uuid>" | null, "meter_id": "…" | null
  },
  "created_at": "<iso>" | null,
  "expires_at": "<iso>" | null,
  "last_used_at": "<iso>" | null,
  "status": "active" | "expired",
  "actions": ["revoke"] | ["rotate", "revoke"],
  "manage_url": "/…" | null          // frontend path where the owner manages the thing behind the credential
}
```

`access`: API key `read_only` → `read_only`, else `read_write` (it acts with the owner's permissions);
analytics → `read`; energy push → `write_readings`. `status`: `expired` when `expires_at` has passed; revoked
credentials are not listed.

The admin list adds `owner: {id, username, email}` to each row; it is `null` for a ZEV-held push token, which
belongs to the ZEV rather than to one account, and a `user` filter leaves such rows out.

## 5. API

### 5.1 `GET /api/v1/auth/me/credentials/`

`accounts.views_credentials.MyCredentialsView`, `CookieJWTAuthentication` only, `IsAuthenticated`, route name
`credential-list` (absent from `ACCOUNTS_API_KEY_ALLOWLIST`, so an API key is refused). Response (not paginated):

```json
{
  "credentials": [<row>, …],
  "can_create": {"api_key": true, "analytics": false}
}
```

During impersonation both `can_create` flags are false and each credential offers only `revoke`.

`credentials` is sorted by `created_at` descending, rows without one last, then `kind`, `id`. Sources:

- API keys: `ApiKey` of the account, not revoked.
- Analytics tokens: `AnalyticsToken` with `created_by` = account, not revoked, only while the flag is on.
- Energy push tokens: `SupplementarySource` with a `push_token_prefix` and either `participant__user` = account,
  or `held_by = zev` in a ZEV the account manages (`zev.access.managed_zev_ids`; an admin without a grant sees
  those only in the admin list), only while the energy data feature is on
  (`metering.supplementary.permissions.feature_enabled()`). `manage_url` is `/me/metering-points` for a
  participant's source and `/metering/points` for a ZEV-held one; a ZEV-held row's `name` falls back to the
  meter id, or the ZEV name for the grid connection point. The managers rotate and revoke it through the
  source's own actions, on which they hold owner rights.

`can_create.analytics` requires the feature flag and a live participant link or viewable ZEV.
`can_create.api_key` is true for an ordinary session. Both are false during impersonation.

### 5.2 `GET /api/v1/auth/credentials/` (admin)

`AdminCredentialsView`, admin only (`403` otherwise). Query parameters: `user` (id), `kind`, `status`
(`active`|`revoked`|`expired`; default all, revoked included, as the existing admin key list). Not paginated: an
instance has tens of credentials, not thousands. Response `{"credentials": [<row>, …]}`; rows add `owner` and `revoked_at`, and
`status` may be `revoked`. Replaces the admin page's use of `GET /auth/api-keys/` (which stays for compatibility).

### 5.3 Actions reuse existing endpoints

| Kind | Revoke | Rotate |
|---|---|---|
| `api_key` | `DELETE /auth/me/api-keys/{id}/` (admin: `DELETE /auth/api-keys/{id}/`) | – |
| `analytics` | `DELETE /analytics/tokens/{id}/` (admin allowed, §3) | – |
| `energy_push` | **new** `POST /metering/supplementary/sources/{id}/revoke-push-token/` | `POST …/rotate-push-token/` (exists) |

`revoke-push-token`: holder or admin (the rule of `rotate_push_token`, `viewer_allowed_actions`), push sources
only (`400` otherwise), a ZEV that is disabled refuses it (`_refuse_if_zev_disabled`), audited
`supplementary_source.revoke_push_token` with the prefix. It drops the token and leaves the source and its readings
in place; the source stops receiving until a new token is issued with rotate, which also re-enables it (existing
behaviour).

`SupplementaryPushAuthentication` touches `push_token_last_used_at` after a successful token check.

## 6. Backend structure

- `accounts/credentials.py`: `list_credentials(user=None)`, building rows from the three querysets; imports
  `analytics` and `metering` lazily to keep `accounts` free of app-load cycles.
- `accounts/views_credentials.py`: `MyCredentialsView`, `AdminCredentialsView`; routes in `accounts/urls.py`
  (`me/credentials/`, `credentials/`).
- `analytics/views.py`: queryset change (§3).
- `metering/supplementary/`: model fields, `revoke_push_token()`, action, authentication touch, serializer fields.
- OpenAPI: `extend_schema` on both views.

## 7. Frontend

### 7.1 Account tab

`features/account/accountTabs.ts`: `AccountTab` = `'profile' | 'security' | 'tokens'`; `resolveAccountTab` also maps
the old `?tab=api-keys` to `tokens`, so existing links keep working. `AccountProfilePage` shows the tab
"Tokens & keys" (`account.tabs.tokens`) with `TokensSection`.

### 7.2 `features/account/TokensSection.tsx` (replaces `ApiKeysSection.tsx`)

- Query `queryKeys.auth.credentials()` → `fetchMyCredentials()`.
- Header, one-time secret panel, "New" buttons, filter chips (`FilterTabs`: `All`, `API key`, `Analytics token`,
  `Energy data token`; a chip appears only when it narrows the list, so an account with one kind sees none), the list.
- A row shows: name; type badge; scope line (ZEV, participant and/or meter as present); access badge (`Read-only`,
  `Read and write`, `Read`, `Delivers readings`); `prefix…`; created; last used (or "never used"); expiry (or "no
  expiry"); "expired" / "expires soon" badge as `apiKeyStatus` does today (reused for any row with `expires_at`).
- Row actions by `actions`: **Revoke** (confirmation dialog, danger) calling the endpoint of §5.3; **Rotate** for
  energy tokens (confirmation, opens the secret panel with the new token); a "Manage source" link for energy tokens.
- "New" buttons: **API key** (shown when `can_create.api_key`; name, expiry, read-only), **Analytics token** (shown when
  `can_create.analytics`), and **Connect energy data**, a link to the energy data page (`/me/metering-points`) with a hint that an
  energy token is created with a source.
- During impersonation, both "New" buttons and energy-token **Rotate** remain visible but disabled
  with the `account.impersonationRestrictions` tooltip, matching connect/rotate on the energy-data
  page. Revocation stays enabled. Ordinary sessions still use the capability flags and row actions.
- Analytics form: name; scope select built by `analyticsScopeOptions(memberships, allZevs?)`: "Whole community:
  <zev>" for each membership with `access` or a managing role, "Only my data: <zev>" for each live participant
  record, a disabled community offers none; an **administrator** also gets every enabled community
  (`fetchZevs`, queried only for admins), because the backend lets an admin create a token for any ZEV;
  expiry select as for keys. The selected scope is derived from the current options, so a list that grows after
  first render (the admin's communities) still has a valid choice.
  Posts `{name, zev, participant?, expires_at}`. The secret panel shows the token and a ready-to-copy
  `curl` line for the series endpoint.
- Shared `components/SecretReveal.tsx`: warning banner, token in a `<code>`, Copy and Dismiss, extra children.
  Used by the account section and by `PushTokenPanel` (which keeps its endpoint and column hints as children), so
  the "shown once" behaviour and styling exist once.

### 7.3 Types and API client

`types/api.ts`: `CredentialKind`, `CredentialAccess`, `CredentialScope`, `AccessCredential`,
`MyCredentialsResponse`, `AdminAccessCredential`, `AnalyticsToken`, `AnalyticsTokenInput`,
`AnalyticsTokenWithSecret`; `SupplementarySource` gains `push_token_created_at`/`push_token_last_used_at`.
`lib/api/credentials.ts`: `fetchMyCredentials`, `fetchAllCredentials`, `createAnalyticsToken`,
`revokeAnalyticsToken`, `revokeCredential(row)` (dispatch by kind). `lib/api/supplementary.ts`:
`revokeSupplementaryPushToken`. `queryKeys.auth.credentials()` and `allCredentials(...)`; creating, revoking or
rotating invalidates both prefixes and the supplementary sources query.

### 7.4 Admin console

`AdminAccountsHubPage`: the second tab becomes `tokens` (label `pages.adminAccounts.tabs.tokens`, "Tokens & keys");
route `admin/accounts/tokens`, with `admin/accounts/api-keys` and `admin/api-keys` as aliases
(`AliasNavigate`). `AdminApiKeysPage` becomes `AdminCredentialsPage`: stat cards (active, expiring soon,
revoked) unchanged in meaning; filters user, **type**, status; the table gains type, scope and owner; Revoke per
row through the kind's admin endpoint (energy tokens: `revoke-push-token`).

### 7.5 i18n and accessibility

All text through `react-i18next`, added to `en`, `de`, `fr`, `it` (`account.tokens.*`, `account.tabs.tokens`,
`pages.adminAccounts.tabs.tokens`, `pages.adminCredentials.*`; existing `account.apiKeys.*` strings are reused where
they still fit). The list is a semantic list (not a div table) that wraps on a 400 px viewport; the chips are a
labelled group of buttons with `aria-pressed`; revoke buttons name the credential.

## 8. Tests

Backend (near the affected modules):

| Module | Count | Covers |
|---|---|---|
| `accounts/test_credentials.py` | 24 | `MyCredentialsTests` (12): the three kinds in one row shape, no secret or hash listed, newest first, revoked excluded and expired flagged, push token created/last-used, a revoked push token leaves the list, flags off hide analytics and energy rows, only the account's own credentials appear, a manager sees no participant's tokens, `can_create`, impersonation offers revocation only, anonymous 401 and an API key or analytics token cannot list; `AdminCredentialsTests` (5): non-admin 403, every kind of every owner with the owner, revoked included and filterable, `kind`/`user` filters, bad filters 400; `ZevHeldPushTokenTests` (7): a manager of the ZEV sees the token in their own list with `held_by = zev` and the metering-points link, gains no participant's tokens, participants/viewers/strangers do not see it, an admin without a grant sees it only in the admin list with `owner = null`, the `user` filter leaves it out, participant-held rows say `account`, the manager rotates and revokes it |
| `analytics/test_tokens.py` | 31 | updated: `test_a_manager_neither_sees_nor_revokes_a_participants_token` replaces the manager-sees-ZEV-tokens test, `test_a_manager_sees_the_tokens_they_made_themself` added; admin still sees all; impersonation refuses and audits creation but allows attributed revocation |
| `metering/test_supplementary_api.py` | +9 | `RevokePushTokenTests`: creation time on issue, holder revokes and keeps source and readings, the token stops working, rotate issues a new one afterwards, revoking twice 400, admin only besides the holder, audited without the secret, solar manager source 400, a disabled ZEV hides the source from its participant |
| `metering/test_supplementary_ingest.py` | +1 | `push_token_last_used_at` set on first use and not rewritten within the window |
| `zev/test_transfer.py` | – | `SchemaParityTests` lists the two new fields as excluded from the archive (transfer archives carry no credentials) |

Frontend (`frontend/tests/`):

| File | Count | Covers |
|---|---|---|
| `tokens-section.test.ts` | 17 | list rows with type, access, scope and prefix; filter chips; expiring badge; empty state; rotate and manage link only on energy tokens; revoke through confirmation and the kind's endpoint; rotate shows the new token once; create API key and analytics token (scope options, participant scope, ready-made command); an administrator can pick any community and an ordinary account triggers no community lookup; impersonation shows disabled creation/rotation with explanatory tooltips, including stale creation capabilities, and preserves revocation; link to the energy data page; a ZEV-held push token is marked as operated by the community |
| `credentials-helpers.test.ts` | 6 | counts and filters; `analyticsScopeOptions` for grants, roles, participant records, ended rows, disabled communities, the administrator's extra communities, no memberships |
| `secret-reveal.test.ts` | 3 | shows, copies and dismisses; copy failure; caller wording and test id |
| `admin-credentials-page.test.ts` | 5 | every kind with owner and counts; a ZEV-held push token shows the community as owner; revoke only for non-revoked; revoke as admin through the kind after confirmation; type filter reaches the server |
| `account-tabs.test.ts` (14) | – | `tokens` tab, the old `?tab=api-keys` still opens it; `route-guard-matrix.test.ts` gains `/admin/accounts/tokens` |

Validation: backend `ruff check .`, `manage.py check`, `makemigrations --check`, `pytest -q`; frontend `npm run lint`,
`lint:style`, hex sweep, `test:unit`, `build`; the tab in the running dev stack at desktop and ~400 px, console clean.

## 9. Risks

| Risk | Mitigation |
|---|---|
| The aggregator drifts from the three sources of truth | it only reads; each kind's mutations stay on its own endpoint; tests cover each kind |
| Revoking a push token silently stops a device | confirmation text names the consequence; the source card shows "no token" and offers rotate |
| Admin oversight of private analytics tokens | admin only, read and revoke, same as API keys; documented |
| `accounts` importing app models | lazy imports inside `list_credentials` |

## 10. Documentation and spec updates

- User guide: `16-api-keys.md` (the tab is now Tokens & keys), `20-energy-data.md` (revoke and last used),
  `21-analytics-and-grafana.md` (create the token in the UI; remove "created through the API for now").
- `2026-10-analytics-dataset-api.md`: §8 list visibility (own only, admin all), §2 out-of-scope token UI struck,
  §13 follow-up 2 updated.
- `2026-10-supplementary-energy-data.md`: new fields, action `revoke-push-token`, `last used`.
- `2026-03-community-and-access.md`: the credentials endpoints; `2026-03-admin-governance-and-settings.md`: the admin tab.
- `2026-05-audit-log-and-operational-traceability.md`: `supplementary_source.revoke_push_token`.
- `AGENTS.md`: list this spec under completed feature specs.
- Screenshots: `16c-account-api-keys.png` shows the old tab; regenerate the user-guide set with `npm run screenshots`
  when a dev stack is available, otherwise flag it in the PR.

## 11. Follow-ups

1. Optional expiry for push tokens once there is a way to warn a device's owner.
2. A manager overview of *sources* (not tokens) with token age, for stale-credential hygiene.
3. Notify a user by email shortly before a token or key they have used recently expires.
