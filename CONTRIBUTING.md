# Contributing to OpenZEV

Thanks for taking an interest. OpenZEV grew out of billing a real ZEV, and
contributions are welcome. For anything larger than a small fix, open an issue
first so we can agree on the direction before you spend time on it.

- **Found a bug or have an idea?** [Open an issue](https://github.com/splattner/openzev/issues).
- **Found a vulnerability?** Do not open an issue; follow [SECURITY.md](SECURITY.md).
- **Want to know what is planned?** See the [roadmap](docs/ROADMAP.md).

## Repository layout

- `backend/`: Django + Django REST Framework
- `frontend/`: React + TypeScript + Vite
- `docs/user-guide/`: end-user documentation, published at <https://www.openzev.ch/docs/>
- `docs/specs/`, `docs/adr/`: feature specs and architecture decisions
- `charts/openzev/`: Helm chart

## Development setup

### With containers (recommended)

The dev stack runs the backend with live reload, the Vite dev server with HMR, a
Celery worker and Beat scheduler, PostgreSQL and Valkey. It works with Docker or
Podman (`podman compose` instead of `docker compose`).

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml exec backend python manage.py seed_demo
```

- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8001/api/v1/>, with Swagger UI at `/api/docs/` and ReDoc at `/api/redoc/`
- Demo admin: `admin@openzev.local` / `admin1234`. The other demo accounts and what the seed creates are listed in the [Getting Started guide](docs/user-guide/01-getting-started.md#demo-accounts).

If the backend starts failing with Postgres `too many clients already`, restart
the backend container.

To run the production-like stack (built frontend behind nginx, with demo data)
use `scripts/start-demo-environment.sh` instead.

### Without containers

Backend (SQLite by default, see `backend/.env.example`):

```bash
cd backend
cp .env.example .env
python -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo   # optional
python manage.py runserver
```

Frontend, with the Node version pinned in `.node-version`:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Async work (invoice emails, PDF generation, dynamic-tariff refreshes) needs
Valkey or Redis, a Celery worker and exactly one Beat scheduler:

```bash
cd backend
celery -A config worker -l info
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Cookie sessions need the frontend and API to share an origin or a host. The
`localhost:5173` → `localhost:8001` split works with `CORS_ALLOWED_ORIGINS` and
`CSRF_TRUSTED_ORIGINS`; two different hostnames do not (JavaScript cannot read a
cross-origin `csrftoken` cookie), so use a same-origin reverse proxy there.

## Checks before you open a pull request

Run what CI runs for the side you touched.

Backend, from `backend/` with the venv active:

```bash
ruff check .
python manage.py check
python -m pytest -q          # parallel; -n 0 for serial, -m "not slow" skips the PDF tests
```

CI also runs the tests on PostgreSQL. To do the same locally, prefix the command
with `DATABASE_URL=postgres://openzev:openzev@localhost:5432/openzev` (the dev
stack's database).

Frontend, from `frontend/`:

```bash
npm run lint
npm run lint:style
node ../scripts/check-frontend-hex.mjs   # raw colours belong in the design tokens
npm run test:unit
npm run build
```

Keep migrations in step with model changes (`python manage.py makemigrations`).
For user-facing frontend changes, also look at the result in the running dev
stack, including a narrow (~400 px) viewport. All user-facing text goes through
`react-i18next`; the language files are in `frontend/src/i18n/locales`.

## Specs and ADRs

Larger or riskier changes are documented before or with the code:

- **Specs** (`docs/specs/`) for changes to API behaviour, billing or tariff logic,
  invoice workflow, data models and migrations, async jobs, or security and
  role/ZEV-scope rules. If your change alters behaviour a baseline spec
  describes, update that spec in the same PR. Process and index:
  [`docs/specs/README.md`](docs/specs/README.md).
- **ADRs** (`docs/adr/`) for high-impact architecture decisions that future
  maintainers should understand. Process and index:
  [`docs/adr/README.md`](docs/adr/README.md).

Link any spec or ADR you touched in the pull request, using the template in
`.github/PULL_REQUEST_TEMPLATE.md`.

## Documentation

When a change alters what a user sees or does, update the matching chapter in
`docs/user-guide/` in the same PR. Preview it with:

```bash
pip install -r scripts/site/requirements-docs.txt
mkdocs serve            # mkdocs build --strict must pass; CI checks it
```

The user-guide screenshots are regenerated as a set with `npm run screenshots`
(against the dev stack, with `SCREENSHOT_BASE_URL=http://localhost:5173` and
`SCREENSHOT_API_URL=http://localhost:8001/api/v1`), not edited one by one. The
README collage is composed by `scripts/readme-collage.py`; its docstring lists
the captures it needs.

The public landing page in `docs/site/` is generated: edit
`scripts/site/template.html` and `scripts/site/lang/*.json`, run
`python scripts/site/build.py`, and commit the output.

## Pull requests

- Branch off an up-to-date `main`; never commit to `main` directly.
- Keep changes small and targeted, and match the surrounding style. Do not
  reformat unrelated code.
- Titles follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat(scope): ...`, `fix(scope): ...`). CI checks this, and Release Please
  builds the changelog from it. Never edit `CHANGELOG.md` by hand.
- Update backend tests and frontend consumers together when an API changes, and
  keep `frontend/src/types/api.ts` in step with the response shapes.
- Fill in the pull request template.

## Using AI coding agents

Agents working in this repository should read [`AGENTS.md`](AGENTS.md), which
holds the working agreements and spec-maintenance rules. A large share of
OpenZEV was written with AI assistance. That is fine for contributions too, as
long as you have read and tested what you submit.

## How releases work

Releases are automated through GitHub Actions (see `.github/workflows/`):

- Pull requests run lint, checks and tests, plus a container build without pushing.
- Commits to `main` build, sign and push preview images (`main`, `main-<sha>`).
- Release Please manages SemVer tags and the changelog. A published release builds
  and pushes the versioned images to GHCR and attaches the deployment files.
- Renovate keeps npm, pip and GitHub Action dependencies up to date.

## Licence

By contributing you agree that your contribution is licensed under the
[AGPL-3.0](LICENCE.md), like the rest of the project.
