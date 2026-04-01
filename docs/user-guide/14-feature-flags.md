# Feature Flags

This guide explains how to control OpenZEV functionality with feature flags.

## What Feature Flags Are

Feature flags are runtime switches that allow you to enable or disable specific functionality without changing code.

In OpenZEV, feature flags can be controlled by:

1. Code defaults (defined in backend code)
2. Environment variable overrides
3. Admin Console toggles

The backend and frontend both read the same feature flag state.

## Current Feature Flags

| Flag name | Default | Purpose |
| --- | --- | --- |
| `zev_self_registration_enabled` | `true` | Allows self-registration from the login page |

## How State Is Resolved

For each flag, OpenZEV resolves the final state in this order:

1. Environment variable `FEATURE_<FLAG_NAME_IN_UPPERCASE>`
2. Value stored in database (set via Admin Console)
3. Code default
4. `false` fallback

For `zev_self_registration_enabled`, the environment variable key is:

```dotenv
FEATURE_ZEV_SELF_REGISTRATION_ENABLED=true
```

## Admin Console Usage

Admins can manage flags in:

- **Admin Console -> Features**

Each flag has:

- Name
- Description
- Toggle switch (On/Off)

When you toggle a flag, OpenZEV applies the new value immediately.

## Environment Variable Override

Use environment variables when you want an ops-level override that should win over UI settings.

Example:

```dotenv
FEATURE_ZEV_SELF_REGISTRATION_ENABLED=false
```

After changing environment variables, restart the backend service (and frontend if needed):

```bash
docker compose restart backend frontend
```

## Example: Disable ZEV Self Registration

If `zev_self_registration_enabled` is disabled:

- The login page hides the "New to OpenZEV" panel.
- The registration button/modal is not shown.
- `POST /api/v1/auth/register/` is blocked by the backend (HTTP 403).

This ensures the feature is disabled in both UI and API layers.

## API Access

### Read feature flags

- `GET /api/v1/auth/feature-flags/`
- Public read access (used by login page)

### Update a feature flag

- `PATCH /api/v1/auth/feature-flags/<id>/`
- Admin only

Payload example:

```json
{
  "enabled": false
}
```

## Developer Usage

Feature flags are registered in backend code and synchronized to the database.

Add a new flag in `backend/accounts/models.py`:

```python
FeatureFlag.register(
    "my_new_feature",
    default=False,
    description="Explain what this feature controls.",
)
```

Check a flag in backend code:

```python
if FeatureFlag.is_enabled("my_new_feature"):
    # feature-on path
    ...
```

Frontend code can read current states via `GET /api/v1/auth/feature-flags/`.

## Best Practices

- Use descriptive flag names in `snake_case`.
- Keep descriptions short and specific.
- Always enforce critical flags in backend code, not only in frontend UI.
- Use environment overrides for production emergency controls.
- Remove stale flags after full rollout to keep the system clean.
