# OpenZEV Helm Chart

Deploys OpenZEV frontend, backend, Celery worker, and Celery Beat scheduler on Kubernetes.

This chart README is the authoritative reference for installing and configuring
the chart. See [Example values](#example-values) for a complete production-oriented
configuration.

## Included resources

- Frontend `Deployment` + `Service`
- Backend `Deployment` + `Service`
- Worker `Deployment`
- Single-replica Beat `Deployment` for periodic tasks
- Shared media `PersistentVolumeClaim` (for `/app/media`)
- `Ingress`

## Not included

- PostgreSQL deployment
- Valkey (or Redis) deployment

## Production hardening

Production renders reject empty values and known development defaults for
the secret, database URL, and frontend origin. Django checks the remaining
production configuration. See [Example values](#example-values).

Transport values render exactly as configured, including in debug and with
`numProxies: 0`. See [proxy configuration](#reverse-proxies-and-num_proxies)
before enabling redirects or HSTS. Booleans must be unquoted; HSTS seconds
must be a non-negative integer. Set chart-managed transport settings through
`debug` and `backend` values, not `backend.extraEnv`.

Every workload runs as UID 10001 with the RuntimeDefault seccomp profile,
privilege escalation disabled, dropped capabilities, and bounded CPU/memory
(the frontend container listens on 8080; its Service remains on port 80).

Partial security-context and resource overrides retain the other defaults;
`{}` does not clear them. To omit a context or resource map, explicitly set
that component's `podSecurityContext`, `securityContext`, or `resources` to
`null`. Size memory limits for representative PDF workloads, including
interactive invoice regeneration in the backend.

See the [hardening spec](../../docs/specs/2026-09-production-hardening.md) for logging boundaries and upgrade requirements.

## Install

Local HTTP experiments need debug mode and disabled transport settings:

```bash
helm upgrade --install openzev ./charts/openzev -n openzev --create-namespace \
  --set debug=true --set backend.secureSslRedirect=false --set backend.hstsSeconds=0
```

A production install must use a values file containing real secrets and the
public HTTPS origin; the default non-debug values intentionally fail closed.

## Use as a Helm repo

After enabling GitHub Pages on the `gh-pages` branch, add this repository as a Helm repo:

```bash
helm repo add openzev https://splattner.github.io/openzev
helm repo update
helm install openzev openzev/openzev -n openzev --create-namespace -f values-prod.yaml
```

## Database credentials via existing secret

If your secret already contains `DATABASE_URL`:

```yaml
database:
  existingSecret:
    name: openzev-db-secret
    key: DATABASE_URL
```

This overrides `database.url`.

## Django secret key

Set `secretKey.value` in `values.yaml` to the Django `SECRET_KEY` value used by backend and worker.

You can also load `SECRET_KEY` from an existing secret:

```yaml
secretKey:
  existingSecret:
    name: openzev-django-secret
    key: SECRET_KEY
```

If `secretKey.existingSecret.name` is set, it overrides `secretKey.value`.

## Two-factor encryption key

Two-factor (TOTP) secrets are encrypted at rest with a Fernet key that is
deliberately independent of `SECRET_KEY` (ADR 0021). Until one is set, users
cannot enrol a second factor and the backend logs a system-check warning.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set it as `mfaEncryptionKeys.value`, or load it from an existing secret:

```yaml
mfaEncryptionKeys:
  existingSecret:
    name: openzev-mfa-secret
    key: MFA_ENCRYPTION_KEYS
```

The value may hold several comma-separated keys, newest first: new secrets are
encrypted with the first, and all are tried on decrypt, so a key can be rotated
without locking anyone out. Losing every key makes enrolled authenticator apps
unusable — back it up like `SECRET_KEY`. The key is only needed by the backend.

## Integration encryption key

Credentials for third-party integrations, today a participant's Solar Manager
API key, are encrypted at rest with keys that are independent of `SECRET_KEY`,
the two-factor key and the backup key (ADR 0031). Until one is set, pull sources
cannot be connected (push and file import keep working). Both the backend and
the worker need it.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set it as `integrationEncryptionKeys.value`, or load it from an existing secret:

```yaml
integrationEncryptionKeys:
  existingSecret:
    name: openzev-integration-secret
    key: INTEGRATION_ENCRYPTION_KEYS
```

The value may hold several comma-separated keys, newest first: new credentials
are encrypted with the first and all are tried on decrypt. Rotate by prepending
the new key, running `python manage.py rotate_integration_key`, then dropping the
old one. A lost key costs a re-connect per participant, not an outage. Backups
carry the ciphertext, never the key.

## Backup encryption key

Backup archives and stored backup-destination secrets are encrypted with keys
that are independent of `SECRET_KEY` and the two-factor key (ADR 0024). A
backup holds password hashes, personal data and invoices, so set one. The
chart runs with `DEBUG` off, so `BACKUP_REQUIRE_ENCRYPTION` defaults to true:
with no key configured, backup creation is refused. Keys must be at least 32 characters:

```bash
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Set it as `backupEncryptionKeys.value`, or load it from an existing secret:

```yaml
backupEncryptionKeys:
  existingSecret:
    name: openzev-backup-secret
    key: BACKUP_ENCRYPTION_KEYS
```

If `backupEncryptionKeys.existingSecret.name` is set, it overrides
`backupEncryptionKeys.value`. The value may hold several comma-separated keys,
newest first: the first encrypts and all are tried on decrypt, so a key can be
rotated. Keep a copy off the cluster — without it an encrypted backup cannot be
opened. The key is passed to the backend and the worker (which runs backup
jobs), not to beat.

There is no dedicated value for the creation policy: to keep creating
unencrypted backups deliberately, set `BACKUP_REQUIRE_ENCRYPTION=False` through
`extraEnv` on the backend and the worker (and the same environment for
administrative CLI runs), then restart the affected processes:

```yaml
backend:
  extraEnv:
    BACKUP_REQUIRE_ENCRYPTION: "False"
worker:
  extraEnv:
    BACKUP_REQUIRE_ENCRYPTION: "False"
```

## Passkeys

Passkeys (WebAuthn) are bound to the domain users open OpenZEV on, so the
relying-party identity must match it:

```yaml
webauthn:
  rpId: zev.example.ch          # bare domain: no scheme, no port
  origin: https://zev.example.ch
  rpName: OpenZEV               # optional, shown by the authenticator
```

Left empty, the backend uses `localhost`, which only works for local
development; with `DEBUG` off, `manage.py check` fails (`accounts.E008` and
`accounts.E009`), so a production deployment must set both. A non-empty value
that is not a public HTTPS origin only warns (`accounts.W002`).
Changing `rpId` later orphans every passkey registered under the old one.
Passkeys need no encryption key — only TOTP does.

## Django admin

Django admin defaults to `DEBUG` (`DJANGO_ADMIN_ENABLED`); its separate session
login bypasses the JWT MFA flow, so any production use needs a private backend
hostname and an ingress allowlist. Keep public `/admin/...` routes pointed at
the frontend for the platform pages.

## OAuth upgrades

After upgrading, new OAuth accounts require `email_verified: true`. For a trusted
provider that verifies email ownership but omits the claim, an admin can enable
**Allow missing email-verification claim** under **Platform → Settings → OAuth**.
This exception applies only to new accounts with an absent claim; it never
permits false/null/non-boolean claims or email-based matching to existing accounts.
Already-linked identities do not need this provisioning exception.

Production token/userinfo endpoints must use HTTPS and their final URLs because
redirects are refused. Private endpoints need an explicit opt-in, available
through the existing environment passthrough:

```yaml
backend:
  extraEnv:
    OAUTH_ALLOW_PRIVATE_HOSTS: "True"
```

This setting applies to every provider and still requires HTTPS. URL/DNS checks
do not bind the connection to the checked address; environment proxies may also
resolve the destination independently. Restrict egress and use only trusted
proxies where this is a security boundary.

## Celery Beat

The chart enables one Beat scheduler by default (`beat.enabled: true`) using
the `django_celery_beat` database scheduler. Keep `beat.replicaCount: 1`:
running multiple schedulers would enqueue every periodic task more than once.
Set `beat.enabled: false` only when the release uses an external scheduler.

## Media PVC

By default, the chart creates a PVC and mounts it to `/app/media` in backend and worker.

Use an existing claim instead:

```yaml
media:
  pvc:
    existingClaim: openzev-media
```

When upgrading root-owned media, `fsGroup: 10001` grants group access on
storage drivers that support it. If the driver does not apply `fsGroup`, stop
the backend and worker and use a temporary maintenance pod mounting this
claim to run `chown -R 10001:10001 /app/media` as root before restarting them.

## Ingress

Default ingress routes:

- `/` to frontend
- `/api` to backend

Configure hosts/paths in `values.yaml` under `ingress.hosts`.

TLS can be enabled with `ingress.tls` (a standard list of Ingress TLS entries), e.g.:

```yaml
ingress:
  tls:
    - hosts:
        - openzev.example.com
      secretName: openzev-tls
```

When exposing OpenZEV via a domain, also set Django `ALLOWED_HOSTS`:

```yaml
backend:
  allowedHosts: "openzev.example.com"
```

If this is missing, Django may reject requests with `400 Bad Request`. With
`DEBUG` off it is mandatory: `manage.py check` fails (`accounts.E003`) unless
it names a non-development host.

### Trusted origins

Since 1.8.0 the backend enforces CSRF on cookie-authenticated writes. A domain
deployment must tell Django which origin the browser sends, or write requests
(imports, edits) fail with `CSRF Failed: Origin checking failed`:

```yaml
backend:
  csrfTrustedOrigins: "https://openzev.example.com"
```

The value is the full origin — scheme and host, no path. When left empty it
falls back to `backend.corsAllowedOrigins`, so setting that alone is enough if
the frontend calls the API from the same origin. With `DEBUG` off, leave
neither empty: `manage.py check` fails (`accounts.E005`) unless the effective
origins are public HTTPS.

### Reverse proxies and NUM_PROXIES

`backend.numProxies` is the number of proxy-added addresses retained in
`X-Forwarded-For` for per-IP rate limits and audit identity. A positive value
also enables Django's `X-Forwarded-Proto` HTTPS detection. Set `0` unless the
backend is reachable only through a proxy that sanitizes the selected entry
and scheme. A value that is too low groups clients into one bucket; a value
that is too high can let clients evade per-IP limits.

```yaml
backend:
  numProxies: 1  # ingress must overwrite XFF or append the actual client address
```

Count addresses retained after the last overwriting proxy, not simply the
number of proxies. The shipped nginx configurations overwrite the header, so
their backend uses `1` even if another proxy precedes nginx (in that case the
identity is that upstream proxy). To preserve client identities through more
hops, the edge must sanitize the header and subsequent trusted proxies must
append their peer addresses. Restrict backend access to those proxies before
enabling header trust; the chart does not enforce that network restriction.
The chart validates `backend.numProxies` (`values.schema.json`): it must be
an integer `>= 0` — empty, null, negative, and fractional values are rejected
at install/upgrade time instead of crashing the backend on startup.
Workers do not serve HTTP and do not need this setting.

The backend connection from an ingress uses HTTP. Before enabling
`backend.secureSslRedirect`, configure HTTPS at the ingress, make it overwrite
`X-Forwarded-Proto` with the external scheme, and set `backend.numProxies`
accordingly. Otherwise HTTPS requests can loop through redirects. Keep
`backend.hstsSeconds: 0` until the public HTTPS origin works; the default
`31536000` tells browsers to require HTTPS for one year after a secure response.

## Email configuration

Set email-related values under `email` in `values.yaml`:

- `email.backend`
- `email.host`
- `email.port`
- `email.useTls`
- `email.hostUser`
- `email.defaultFromEmail`

Set frontend base URL used by backend-generated links and redirects at top-level:

- `frontendUrl` (with `DEBUG` off it must be a public HTTPS origin —
  `accounts.E004`)

The chart default email backend is the console backend, which only prints
mail to the container log: with `DEBUG` off, `manage.py check` fails
(`accounts.E006`) until a real delivery backend such as SMTP is configured.

`EMAIL_HOST_PASSWORD` can be loaded from an existing secret:

```yaml
email:
  existingSecret:
    name: openzev-mail-secret
    key: EMAIL_HOST_PASSWORD
```

## Valkey

Valkey is external to this chart (see [Not included](#not-included)). Any
Redis-compatible server works: Valkey speaks the Redis protocol, so the URLs
keep the `redis://` scheme. Point the Celery broker at `valkey.url`, and the
cache database (e.g. geocoding results — kept on a separate logical DB so
cache keys never collide with Celery's broker) at `valkey.cacheUrl`:

```yaml
valkey:
  url: redis://valkey.example.svc.cluster.local:6379/0
  cacheUrl: redis://valkey.example.svc.cluster.local:6379/1
```

All backend replicas must share this cache for registration reservations and
throttles; a process-local cache does not coordinate workers.

### Upgrading from `redis.*`

Earlier chart versions configured this under `redis.url` and `redis.cacheUrl`.
Those values are deprecated but still honoured: when set they take precedence
over `valkey.*`, so an existing install that overrides them keeps pointing at
its current server (Redis or Valkey) with no change. Move the values to
`valkey.*` when convenient. The chart default now points at a host named
`valkey`; installs that relied on the old default host `redis` must set
`valkey.url` / `valkey.cacheUrl` (or keep `redis.*`).

## Example values

A complete production-oriented example covering the required Django host,
trusted-origin and passkey settings, external database and Valkey, secrets,
email, and ingress. This block is kept in sync with the `DEBUG=False`
production system checks by `backend/config/test_helm_example.py`:

```yaml
frontendUrl: https://openzev.example.com

backend:
  allowedHosts: "openzev.example.com"
  csrfTrustedOrigins: "https://openzev.example.com"
  # See "Reverse proxies and NUM_PROXIES" above.
  numProxies: 1
  secureSslRedirect: true
  hstsSeconds: 31536000

webauthn:
  rpId: openzev.example.com
  origin: https://openzev.example.com

database:
  existingSecret:
    name: openzev-db-secret
    key: DATABASE_URL

valkey:
  url: redis://valkey.example.svc.cluster.local:6379/0
  cacheUrl: redis://valkey.example.svc.cluster.local:6379/1

secretKey:
  existingSecret:
    name: openzev-django-secret
    key: SECRET_KEY

email:
  backend: django.core.mail.backends.smtp.EmailBackend
  host: smtp.example.com
  port: 587
  useTls: true
  hostUser: openzev@example.com
  defaultFromEmail: openzev@example.com
  existingSecret:
    name: openzev-mail-secret
    key: EMAIL_HOST_PASSWORD

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: openzev.example.com
      frontendPaths:
        - /
      backendPaths:
        - /api
```

Apply a values file with:

```bash
helm upgrade --install openzev openzev/openzev -n openzev --create-namespace -f values-prod.yaml
```
