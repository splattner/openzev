# OpenZEV Helm Chart

Deploys OpenZEV frontend, backend, and Celery worker on Kubernetes.

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
helm upgrade --install openzev ./helm/openzev
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

## Email configuration

Set email-related values under `email` in `values.yaml`:

- `email.backend`
- `email.host`
- `email.port`
- `email.useTls`
- `email.hostUser`
- `email.defaultFromEmail`
- `email.frontendUrl`

`EMAIL_HOST_PASSWORD` can be loaded from an existing secret:

```yaml
email:
  existingSecret:
    name: openzev-mail-secret
    key: EMAIL_HOST_PASSWORD
```
