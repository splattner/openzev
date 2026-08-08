# OpenZEV Helm Chart

Deploys OpenZEV frontend, backend, and Celery worker on Kubernetes.

This chart README is the authoritative reference for installing and configuring
the chart. See [Example values](#example-values) for a complete production-oriented
configuration.

## Included resources

- Frontend `Deployment` + `Service`
- Backend `Deployment` + `Service`
- Worker `Deployment`
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
