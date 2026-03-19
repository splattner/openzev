# OpenZEV

Open source platform for operating and billing (v)ZEV energy communities.

OpenZEV gives operators one place to manage participants, metering points, tariffs, imports, and invoicing. It is built to support day-to-day operations from data import to payment tracking with role-based access for admins, owners, and participants.

## Disclaimer

- Built for personal use and self-hosting tinkerers who enjoy running their own stack.
- Shipped as-is, with no warranty (yes, even when it looks great in the dashboard).
- Please double-check your data and billing outputs: we do not take responsibility for incorrect imports, calculations, invoices, or invoicing workflows.
- 100% vibe coded.

## Product Overview

- Built for Swiss ZEV/vZEV operating models
- End-to-end workflow from metering import to paid invoice
- Transparent invoice lifecycle with clear status tracking
- Open and extensible architecture for long-term adoption

## Main Features

### Community & User Management

- Manage ZEVs with clear role boundaries (`admin`, `zev_owner`, `participant`)
- Keep participant and metering point data organized
- Use role-aware dashboards for operational visibility

### Metering & ImportsConfiguration of ZEV details, billing preferences, and invoice email templates

- Import metering data from CSV/Excel with configurable column mapping
- Support SDAT-CH imports for utility-oriented workflows
- Validate with import preview and detailed import protocol
- Analyze consumption and production via chart views

### Tariffs & Billing

- Configure tariffs and tariff periods per ZEV
- Run timestamp-level billing allocation and calculations
- Process invoices through draft/approved/sent/paid/cancelled states
- Generate Swiss-ready PDF invoices with QR bill support

### Invoice Communication

- Send invoice emails asynchronously for reliable delivery
- Track email history and retry failed sends
- Customize invoice email templates per ZEV with sensible defaults

### Product Experience

- Multilingual frontend (EN/DE/FR/IT)
- Built-in API docs via Swagger and ReDoc
- Admin overview with operational metrics and status insights

## Screenshots

### Login

![Login](docs/screenshots/login.png)

### Dashboard

![Dashboard](docs/screenshots/dashboard.png)

Overview of KPIs, invoice status, and operational health.

### Metering Points

![ZEV Settings](docs/screenshots/meteringpoints.png)

### Metering Data

![Metering Data](docs/screenshots/meteringdata.png)

### Invoices

![Invoices](docs/screenshots/invoices.png)

Invoice lifecycle management, PDF generation, and email tracking.

### Metering Import Wizard

![Metering Import Wizard](docs/screenshots/import-wizard.png)

Step-by-step import flow with mapping, preview, and validation feedback.

## Architecture & Stack

- Backend: Django, Django REST Framework, SimpleJWT
- Frontend: React, TypeScript, Vite, React Query, i18next
- Async jobs: Celery with Redis broker
- Database: SQLite (default), PostgreSQL, MariaDB via `DATABASE_URL`
- Runtime/deploy: Docker and docker compose

## Quick Start (Docker)

Recommended default: keep frontend, backend, and worker separated for cleaner scaling and easier operations.

```bash
docker compose up -d --build
```

Services:

- Frontend: <http://localhost:8080>
- Backend API: <http://localhost:8000>
- PostgreSQL: localhost:5432
- Redis: localhost:6379

To stop:

```bash
docker compose down
```

## Optional: Fullstack Container Mode

If you prefer a single application container (frontend + backend together), use:

```bash
docker compose -f docker-compose.fullstack.yml up -d --build
```

In this mode:

- `app` serves the frontend and proxies API requests to Django inside the same container.
- `worker`, `db`, and `redis` remain separate services.
- Frontend URL: <http://localhost:8080>

To stop:

```bash
docker compose -f docker-compose.fullstack.yml down
```

## Prebuilt Container Images

Prebuilt images are published to GitHub Container Registry (GHCR), the current image names are:

- `ghcr.io/splattner/openzev-backend`
- `ghcr.io/splattner/openzev-frontend`
- `ghcr.io/splattner/openzev-fullstack`

Available image variants:

- `openzev-backend`: Django API application
- `openzev-frontend`: static frontend served with Nginx
- `openzev-fullstack`: frontend assets + backend in one container for simpler test deployments

Available tags:

- Release tags such as `v1.2.3`
- `latest` for the newest published release
- `main` for the newest build from the `main` branch
- `main-<short-sha>` for a specific `main` branch commit build

### Stability Note for `main` Images

Images tagged `main` are intended for testing and preview deployments before a formal release.

- They are rebuilt on every commit pushed to `main`
- They may contain unfinished changes or breaking behavior
- They should be considered unstable and not be treated like a versioned release artifact

If you need reproducible deployments, prefer a release tag such as `v1.2.3` instead of `main`.

### SBOMs and Signatures

- Release images are published with signed container manifests and signed SBOM attestations
- `main` branch images are also pushed, signed, and accompanied by generated SBOMs
- Release SBOM files are attached to the GitHub release
- `main` branch SBOM files are uploaded as workflow artifacts in the `Container Build Check` workflow run
- SBOM verification is performed through the signed attestation bound to the image, not through a separate detached signature on the raw `.spdx.json` file

### Verify an Image Signature

Install `cosign` locally, then verify an image with GitHub OIDC keyless signatures:

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/splattner/openzev/.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/splattner/openzev-backend:main
```

For a release image, replace the tag with the release version, for example `:v1.2.3`.

### Verify the SBOM Attestation

You can verify the signed SBOM attestation attached to an image:

```bash
cosign verify-attestation \
  --certificate-identity-regexp "https://github.com/splattner/openzev/.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  --type spdxjson \
  ghcr.io/splattner/openzev-backend:main
```

To inspect the attested predicate after verification, add `| jq '.payload | @base64d | fromjson'` or download the generated `.spdx.json` artifact directly from the workflow or release.

## Local Development Setup

### 1) Backend

```bash
cd backend
cp .env.example .env
python -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Optional admin user:

```bash
python manage.py createsuperuser
```

### 2) Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Frontend dev URL: <http://localhost:5173>

### 3) Celery worker (required for async emails)

```bash
cd backend
source ../.venv/bin/activate
celery -A config worker -l info
```

## Seed Data & Demo Accounts

Use seeded data for quick local testing of flows.

```bash
cd backend
source ../.venv/bin/activate
python manage.py seed_demo
```

Seeded demo users:

- Admin: `admin` / `admin1234`
- ZEV Owner: `zev_owner` / `owner1234`
- Participant: `alice` / `alice1234`
- Participant: `bob` / `bob1234`

The seed command also creates sample ZEV data, participants, metering points, tariffs, and readings.

## API & Developer Docs

- Swagger UI: <http://localhost:8000/api/docs/>
- ReDoc: <http://localhost:8000/api/redoc/>
- Base API prefix: `/api/v1/`

## Development Notes

- Default local database uses SQLite; production should use PostgreSQL or MariaDB.
- Async email features require Redis + Celery worker running.
- Use `.env.example` as baseline for environment configuration.
- Keep migrations up to date when changing models:

```bash
cd backend
source ../.venv/bin/activate
python manage.py makemigrations
python manage.py migrate
```

- Run backend tests from repository root:

```bash
pytest
```

- Build frontend before release:

```bash
cd frontend
npm run build
```

## Release Workflow (GitHub)

- Conventional Commit style is enforced for PR titles.
- Release Please manages SemVer tagging and changelog generation.
- Pull requests run lint/check/test and container build checks without pushing images.
- Commits pushed to `main` build and publish preview images to GitHub Container Registry, generate SBOMs, and sign images plus SBOM attestations.
- Published releases build and push versioned container images to GitHub Container Registry:
  - `ghcr.io/<owner>/openzev-backend`
  - `ghcr.io/<owner>/openzev-frontend`
  - `ghcr.io/<owner>/openzev-fullstack`
- Release image pipeline generates SBOMs, signs images with Cosign (keyless OIDC), attests SBOMs, and uploads SBOM files as release assets.
- Renovate is configured to keep npm/pip/GitHub Action dependencies up to date.
