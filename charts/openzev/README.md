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
- Redis deployment

## Install

```bash
helm upgrade --install openzev ./charts/openzev -n openzev --create-namespace
```

## Use as a Helm repo

After enabling GitHub Pages on the `gh-pages` branch, add this repository as a Helm repo:

```bash
helm repo add openzev https://splattner.github.io/openzev
helm repo update
helm install openzev openzev/openzev -n openzev --create-namespace
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
development; with `DEBUG` off, `manage.py check` warns (`accounts.W002`).
Changing `rpId` later orphans every passkey registered under the old one.
Passkeys need no encryption key — only TOTP does.

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

## Ingress

Default ingress routes:

- `/` to frontend
- `/api` and `/admin` to backend

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

If this is missing, Django may reject requests with `400 Bad Request`.

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
the frontend calls the API from the same origin.

### Reverse proxies and NUM_PROXIES

`backend.numProxies` controls DRF's `NUM_PROXIES` setting for per-IP rate limits. Set it to the number of trusted proxy-added addresses in `X-Forwarded-For`. Set `0` unless the backend is reachable only through proxies that prevent clients from controlling the selected entry. A value that is too low groups clients into one bucket; a value that is too high can let clients evade per-IP limits.

```yaml
backend:
  numProxies: 1  # ingress must overwrite XFF or append the actual client address
```

Count addresses retained after the last overwriting proxy, not simply the
number of proxies. The shipped nginx configurations overwrite the header, so
their backend uses `1` even if another proxy precedes nginx (in that case the
identity is that upstream proxy). To preserve client identities through more
hops, the edge must sanitise the header and subsequent trusted proxies must
append their peer addresses. Restrict backend access to those proxies before
enabling header trust; the chart does not enforce that network restriction.
The chart validates `backend.numProxies` (`values.schema.json`): it must be
an integer `>= 0` — empty, null, negative, and fractional values are rejected
at install/upgrade time instead of crashing the backend on startup.
Workers do not serve HTTP and do not need this setting.

## Email configuration

Set email-related values under `email` in `values.yaml`:

- `email.backend`
- `email.host`
- `email.port`
- `email.useTls`
- `email.hostUser`
- `email.defaultFromEmail`

Set frontend base URL used by backend-generated links and redirects at top-level:

- `frontendUrl`

`EMAIL_HOST_PASSWORD` can be loaded from an existing secret:

```yaml
email:
  existingSecret:
    name: openzev-mail-secret
    key: EMAIL_HOST_PASSWORD
```

## Redis

Redis is external to this chart (see [Not included](#not-included)). Point the
Celery broker at `redis.url`, and the cache database (e.g. geocoding results —
kept on a separate logical Redis DB so cache keys never collide with Celery's
broker) at `redis.cacheUrl`:

```yaml
redis:
  url: redis://redis.example.svc.cluster.local:6379/0
  cacheUrl: redis://redis.example.svc.cluster.local:6379/1
```

## Example values

A complete production-oriented example covering external database and Redis,
secrets, email, and ingress:

```yaml
frontendUrl: https://openzev.example.com

database:
  existingSecret:
    name: openzev-db-secret
    key: DATABASE_URL

redis:
  url: redis://redis.example.svc.cluster.local:6379/0
  cacheUrl: redis://redis.example.svc.cluster.local:6379/1

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
        - /admin
```

Apply a values file with:

```bash
helm upgrade --install openzev openzev/openzev -n openzev --create-namespace -f values-prod.yaml
```
