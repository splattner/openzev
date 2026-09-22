# Getting Started with OpenZEV

This guide covers installation, quick setup, and first-time use of OpenZEV.

## Prerequisites

- Docker and Docker Compose installed on your system
- Basic familiarity with terminal/command line
- A modern web browser

## Quick Start with Docker

OpenZEV is designed to run in Docker for easy setup and deployment.

### Demo and local development

Keep frontend, backend, and worker separated for cleaner scaling and easier operations. To start the stack and seed the full demo dataset in one step:

```bash
scripts/start-demo-environment.sh
```

The script creates `backend/.env` from `backend/.env.example` (development
defaults) when it does not exist yet, and refuses to run when `backend/.env`
disables `DEBUG` (a production configuration) instead of seeding it.
For day-to-day development with live
reload, use the dev stack instead:

```bash
cd /path/to/openzev
docker compose -f docker-compose.dev.yml up -d --build
```

Wait a few seconds for services to start, then access:

- **Frontend (UI):** http://localhost:8080 (dev stack: http://localhost:5173)
- **Backend API:** http://localhost:8080/api/v1/ (dev stack: http://localhost:8001)
- **Database:** localhost:5432 (PostgreSQL, dev stack only)
- **Message Broker:** localhost:6379 (Redis, dev stack only)

To stop the dev stack:

```bash
docker compose -f docker-compose.dev.yml down
```

### Self-hosting

For a production-like deployment, copy the production template and configure
it for this host (leave `CORS_ALLOWED_ORIGINS` empty for same-origin
deployments where nginx proxies `/api/`):

```bash
cp backend/.env.production.example backend/.env
docker compose up -d --build
```

The stack requires `backend/.env` before starting. Only the frontend (`8080`)
is reachable from the host; the backend is not published and is reachable only
through the frontend's `/api/` proxy, while PostgreSQL and Redis talk over the
compose network only.

Configure the SMTP settings and sender address in `backend/.env` before using
registration, onboarding, invoice, or security emails; see the [Email
Configuration guide](10-email-configuration.md).

> **HTTPS is required for public access.** With `DEBUG=False` the auth and
> CSRF cookies are `Secure`, so browsers only send them over HTTPS — plain
> HTTP works for local loopback testing, but a public domain needs TLS
> termination (e.g. a reverse proxy in front of port `8080`). Set
> `ALLOWED_HOSTS` to the public hostname, `CSRF_TRUSTED_ORIGINS` and
> `FRONTEND_URL` to the public `https://` origin (even when
> `CORS_ALLOWED_ORIGINS` stays empty for same-origin deployments), and open
> the app at that `https://` URL.

The shipped nginx sanitizes `X-Forwarded-For` and the production stack keeps
`NUM_PROXIES=1`. If another proxy sits in front of it, audit and rate-limit
identity is therefore the immediate outer-proxy address; do not increase
`NUM_PROXIES` unless the entire proxy chain is deliberately sanitized and
configured to preserve client addresses.

> **`/media/` is never web-served in production** — invoice files are served
> only through authenticated API endpoints.

### Fullstack Container Mode (Single Container)

If you prefer running frontend and backend in a single container, copy and
fill the production checklist as above, then run:

```bash
cp backend/.env.production.example backend/.env
docker compose -f docker-compose.fullstack.yml up -d --build
docker compose -f docker-compose.fullstack.yml down
```

In fullstack mode:
- Frontend URL: http://localhost:8080
- Worker, database, and Redis run as separate services

## Demo Accounts

A demo dataset is available for testing. It is loaded by starting the stack
with `scripts/start-demo-environment.sh`, or by running `seed_demo` on an
already-running stack (see below). It contains two communities owned by the
same owner — the flagship **ZEV STWEG Sonnenhof** and the smaller
**ZEV Sonnenfirma AG** — so both sides of the community switcher have real
data to show. Credentials and the full list of what the seed creates are in
the root [`README.md`](../../README.md#seed-data--demo-accounts).

### Resetting Demo Data

To reload the demo dataset:

```bash
docker compose exec backend python manage.py seed_demo
```

This refreshes demo readings, invoices, import/email logs and audit events for
both communities. Issued contract snapshots are retained.

## First-Time Setup

### 1. Login

1. Navigate to http://localhost:8080
2. Login with admin credentials (or ZEV owner to manage a community)
3. Managers land on **Overview**; participants land on their personal dashboard

![Login page](screenshots/01-login.png)

### 2. Explore as Admin

If logged in as admin:
- Go to **Platform → Overview** to see system-wide KPIs
- View **ZEVs**, **Accounts**, **Invoices**, and **System Settings** (regional/VAT)
- To work inside a community: open **Platform → Overview → ZEVs** and click **Manage** on a row — this selects the ZEV and takes you to its operational Overview. (While under `/admin` the shell shows the **Platform administration** indicator instead of the switcher.)
- The sidebar ZEV switcher (top-left) selects the working community anywhere else; the selected community is shown above the page title on every page, so it stays visible even when the navigation scrolls, the sidebar is collapsed, or you are on mobile

### 3. Explore as ZEV Owner

If logged in as a ZEV owner:
- Go to **Overview** for setup guidance and billing work grouped by period
- Go to **Energy balance** to analyse production, consumption, self-consumption, and grid exchange for a period
- Go to **Settings** to configure your community parameters (General · Billing & payment · Documents & emails · Audit log · Export/transfer)
- Go to **Participants** to view member list
- Go to **Metering Points** to see participant meters
- Go to **Metering** for consumption charts, data quality, and import history
- Go to **Tariffs** to configure energy pricing
- Go to **Billing** to generate and manage invoices, inspect/retry email delivery, and download statements
- Go to **Reports** for annual statements and financial summaries

![Manager Overview](screenshots/02-dashboard.png)

![Manager Energy balance](screenshots/02c-energy-balance.png)

### 4. View as Participant

Login as a participant (Anna or Ben):
- **Dashboard** shows your energy consumption/production overview
- **My invoices** lists the invoices issued to you (details + PDF)
- **Annual statement** shows your yearly statement and financial summary

![Participant Dashboard](screenshots/02b-participant-dashboard.png)

![Account profile](screenshots/16-account-profile.png)

## API Access

OpenZEV provides a complete REST API for programmatic access:

- **Swagger UI:** http://localhost:8080/api/docs/
- **ReDoc:** http://localhost:8080/api/redoc/
- **API Base URL:** http://localhost:8080/api/v1/

Development stack (`docker-compose.dev.yml`) serves the API directly on port 8001.

The API is protected by JWT authentication. Demo credentials work for API access too.

## Prebuilt Container Images

If you prefer not to build locally, prebuilt images are available on GitHub Container Registry:

- `ghcr.io/splattner/openzev-backend:latest`
- `ghcr.io/splattner/openzev-frontend:latest`
- `ghcr.io/splattner/openzev-fullstack:latest`

Tag variants:
- `latest` — newest published release
- `vX.Y.Z` — specific release version
- `main` — latest development build (may be unstable)

### Reverse proxies and NUM_PROXIES

`NUM_PROXIES` defaults to `0`, so direct requests cannot choose their own
rate-limit or audit identity through `X-Forwarded-For`. The default and fullstack
Compose stacks use `1` behind nginx and expose the API through port 8080 only.
The development stack keeps `0` because its backend is directly accessible;
requests through Vite may share a rate-limit bucket. For custom proxies or
Kubernetes, follow the [proxy configuration guidance](../../charts/openzev/README.md#reverse-proxies-and-num_proxies)
before enabling trusted hops.

## What's Next?

- **Operators:** See [ZEV Setup and Configuration](02-zev-setup.md)
- **Data Management:** See [Metering Imports](05-metering-import.md)
- **Billing:** See [Tariff Configuration](07-tariff-configuration.md)
- **Understanding Roles:** See [Roles and Permissions](11-roles-and-permissions.md)

## Troubleshooting

### Services won't start

Check Docker logs:

```bash
docker compose logs
```

### Can't access frontend

- Ensure port 8080 is not in use: `lsof -i :8080`
- Check Docker container is running: `docker compose ps`

### Database connection errors

Verify PostgreSQL container is healthy:

```bash
docker compose logs db
```

### The database looks empty after switching compose files

All three compose files (`docker-compose.yml`, `docker-compose.dev.yml`,
`docker-compose.fullstack.yml`) share the `postgres_data` volume and mount it at
`/var/lib/postgresql/data`, with `PGDATA` pinned to the `pgdata` subdirectory —
so switching between them keeps one database.

Older revisions mounted that volume at different paths in different files, which
gave each stack a cluster the others could not see: starting one, then the
other, looked like the database had been wiped. If you are coming from such a
setup, the first start after upgrading initialises an empty cluster; see the
upgrade note in the [README](../../README.md#quick-start-docker) for how to
carry data across.

See [Troubleshooting](12-troubleshooting.md) for more help.

## Disclaimer

OpenZEV is built for personal use and self-hosting by tinkerers who enjoy running their own stack. **Please double-check your data and billing outputs**—we do not take responsibility for incorrect imports, calculations, invoices, or invoicing workflows.

Before using in production:
- Test thoroughly with sample data
- Verify all calculations match your tariff agreements
- Set up regular backups of your database **and** the invoice PDF files — see [Backups](18-backups.md)
- Review user roles and access controls
