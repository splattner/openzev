# Feature Spec: Production hardening

- Spec ID: SPEC-2026-09-production-hardening
- Status: In Progress
- Scope: Minor
- Type: Change
- Owners: contributors
- Created: 2026-09-22
- Target Release: unreleased
- Related Issues: Helm chart maturity row in `docs/ROADMAP.md`
- Impacted Areas: backend | docs | infra

## 1. Outcome

Production deployments use HTTPS, omit query strings and Referer from access
logs, and run containers as UID/GID 10001. Helm rejects empty values and known
development defaults unless `debug: true`.

## 2. Transport settings and proxy trust

### Django (`backend/config/settings.py`)

| Setting | Default and behavior |
|---|---|
| `NUM_PROXIES` | Env integer, default `0`; negative values fail startup. Also used by DRF throttling and `config.client_ip` hop counting. |
| `SECURE_PROXY_SSL_HEADER` | `("HTTP_X_FORWARDED_PROTO", "https")` only when `NUM_PROXIES > 0`; otherwise unset. |
| `SECURE_SSL_REDIRECT` | Env boolean, default `not DEBUG`. |
| `SECURE_HSTS_SECONDS` | Env integer, default `0` in debug, otherwise `31536000`. |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | Env boolean, default `false`. |
| `SECURE_HSTS_PRELOAD` | `false`. |
| `SESSION_COOKIE_SECURE` / `SESSION_COOKIE_SAMESITE` | `not DEBUG` / `Lax`; CSRF settings unchanged. |

### Deployment boundaries

- **Production Compose and fullstack:** publish `127.0.0.1:8080:8080` for a
  host-installed TLS proxy; a containerized proxy instead uses a private
  network with no app port published. The separate backend has no published
  port. Bundled nginx overwrites `X-Forwarded-For` with `$remote_addr`, and
  Django trusts one retained address (`NUM_PROXIES=1`). The outer proxy must
  overwrite `X-Forwarded-Proto` with the external scheme. The nginx map accepts
  `https`; otherwise it uses `$scheme`.
- **Helm:** `backend.numProxies` defaults to `0`. Redirect and HSTS render
  exactly as configured, irrespective of debug or proxy count. Set
  `numProxies: 1` behind an ingress that sanitizes forwarded headers;
  local HTTP needs explicit `secureSslRedirect: false` and `hstsSeconds: 0`.
- **Dev Compose and direct local use:** `NUM_PROXIES=0`; forwarded headers
  cannot claim HTTPS.

Both entrypoints load `/app/gunicorn.conf.py`, which disables Gunicorn's
independent scheme inference with `secure_scheme_headers = {}`. Django alone
decides forwarded HTTPS trust, even for loopback peers; legacy forwarded-scheme
headers have no effect. The shared file also holds access-log settings and
`GUNICORN_FORWARDED_ALLOW_IPS` (default `127.0.0.1`). This allowlist controls
Gunicorn's forwarded WSGI headers, not Django's acceptance of forwarded HTTPS.
Its control socket is `/tmp/gunicorn.ctl`, keeping runtime writes outside
root-owned `/app`.

### Logging

Gunicorn's access format uses `%(U)s` (path) and omits `%(f)s` (Referer).
All three nginx configs use `access_log /dev/stdout no_query` with
`$request_method $log_path $server_protocol`, status, and response size.
`$log_path` redacts `/signin/` path tokens case-insensitively, even when
`index.html` is missing; other paths use `$uri`. Query strings and Referer are omitted.

Nginx errors remain enabled for ordinary requests. The Compose proxy configs
suppress errors on `/api/v1/public/invoices/` and
`/api/v1/auth/oauth/callback/` because upstream failures include the original
URI. Body-only public token endpoints retain diagnostics.
All three configs suppress errors on token entry pages (`/i/`, `/join/`,
`/signin/`, `/verify-email`, `/reset-password`, `/confirm-email-change`,
`/oauth/callback`), matching React Router case-insensitively. These serve
`index.html` directly, return 404 if it is missing, and set
`Referrer-Policy: no-referrer`. Failed requests still appear
in the access log. External ingress and TLS-terminator logs need separate
configuration.

## 3. Containers

| Image | User and writable paths | Port |
|---|---|---|
| Backend (`backend/Dockerfile`) | UID/GID 10001; `/app/media` writable | 8000 |
| Fullstack (`Dockerfile.fullstack`) | UID/GID 10001; media and nginx cache/log/lib directories writable | 8080 |
| Frontend (`frontend/Dockerfile`) | UID/GID 10001; `/var/cache/nginx` and `/var/log/nginx` writable | 8080 |

Nginx uses `/tmp/nginx.pid`; fullstack removes the Debian default site. Code,
static assets, and nginx configuration stay root-owned. Python images use
`XDG_CACHE_HOME=/tmp/openzev-cache` for rendering caches. Backend startup runs
migrations before Gunicorn; direct-image SQLite use needs a writable DB path.

## 4. Helm chart

- Outside debug, `templates/validation.yaml` rejects empty/whitespace or
  placeholder `secretKey.value` unless `secretKey.existingSecret.name` is set;
  empty/whitespace or local-default `database.url` unless
  `database.existingSecret.name` is set; and empty/whitespace or
  `http://localhost:5173` frontend origins. Django checks the rest of the
  production configuration.
- `values.schema.json` requires boolean `debug` and
  `backend.secureSslRedirect`, and non-negative integer `backend.numProxies`
  and `backend.hstsSeconds`.
- Backend receives `DEBUG`, `FRONTEND_URL`, `NUM_PROXIES`,
  `SECURE_SSL_REDIRECT`, and `SECURE_HSTS_SECONDS`. Worker and beat receive
  `DEBUG` too. HSTS uses Helm's `int` filter to produce a decimal integer.
  Chart-managed transport names are rejected in `backend.extraEnv`, even in
  debug, to prevent duplicate environment entries.
- Every workload defaults to `runAsNonRoot`, `runAsUser: 10001`,
  `fsGroup: 10001`, `seccompProfile: RuntimeDefault`,
  `allowPrivilegeEscalation: false`, and dropped `ALL` capabilities.
  `readOnlyRootFilesystem: false` permits runtime caches. Partial overrides
  retain other defaults; `null` removes a security-context or resource map,
  while `{}` retains its defaults.
- Frontend Service port stays 80 and targets the named container port on 8080.
- CPU/memory requests → limits: backend `100m/256Mi` → `1/1Gi`;
  worker `100m/512Mi` → `1/2Gi`; beat and frontend `50m/128Mi` → `500m/512Mi`.
  Interactive PDF regeneration also runs in the backend; size for real workloads.

## 5. Upgrade and validation

The [Docker upgrade guide](../user-guide/01-getting-started.md#6-back-up-and-update)
covers container ports, loopback publication, ownership migration to
`10001:10001`, and the one-year HSTS default. Verify HTTPS with HSTS disabled
before enabling the persistent browser policy. PVC guidance is in the
[chart README](../../charts/openzev/README.md#media-pvc).

Regression coverage:

- `config/test_settings_guards.py`: isolated settings imports check disabled
  and enabled forwarded HTTPS trust.
- `config/test_transport_behavior.py`: redirects, HSTS, spoofed headers, and
  real Gunicorn parsing into Django middleware, including legacy conflicts.
- `config/test_proxy_trust_boundary.py`: Compose publication, proxy headers,
  CORS precedence, and Helm proxy defaults/schema.
- `scripts/check-helm-render.py`: structured routing/transport assertions,
  independent negative cases, debug/production, and map override/removal.
- `scripts/check-production-images.py`: three built images as UID/GID 10001,
  immutable code/config, fresh and migrated media/PDF writes, buffered uploads,
  redirects/HSTS, and token-safe success/failure logs for canonical and mixed-case
  token routes. Backend and fullstack images also start Celery worker and database
  beat as UID/GID 10001 against the smoke database/broker; beat initializes its
  schedule and each worker executes an OAuth-token cleanup task.

CSP, NetworkPolicy, read-only root filesystems, and object-store smoke tests
are outside this change. Network policies depend on the deployment's actual
ingress, database/Valkey, SMTP, and egress requirements.
