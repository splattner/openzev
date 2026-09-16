# AGENTS.md

## Purpose

This file gives coding agents the minimum project-specific context needed to work safely and efficiently in this repository.

## Repository Layout

- `backend/` — Django + Django REST Framework backend
- `frontend/` — React + TypeScript + Vite frontend
- `docker-compose.dev.yml` — the development stack (backend with live reload, Vite dev server with HMR, Celery worker + beat, Postgres, Redis); this is the one used day to day
- `docker-compose.yml` — production-like local stack (built frontend behind nginx)
- `docs/specs/`, `docs/adr/` — feature specs and architecture decisions
- `docs/user-guide/` — end-user documentation
- `docs/release-notes/` — hand-written release notes for minor/major releases

## Key Stack

- Backend: Django, DRF, pytest
- Frontend: React, TypeScript, TanStack Query, Vite
- Async jobs: Celery + Redis
- DB: PostgreSQL
- Use the Node version pinned in `.node-version` for frontend commands and tests; verify with `node --version` before running them

## Local Development Commands

### Full stack (dev)

The container runtime may be Docker or Podman — check which is available (`command -v docker podman`) and use `docker compose` or `podman compose` accordingly. Before starting anything, check whether the stack is already running (`docker ps` / `podman ps`); it often is.

- Start: `docker compose -f docker-compose.dev.yml up -d --build` (or `podman compose ...`)
- Frontend (Vite, HMR): http://localhost:5173 — source is bind-mounted, so edits apply without a restart
- Backend API: http://localhost:8001/api/v1
- Seed demo data: `docker compose -f docker-compose.dev.yml exec backend python manage.py seed_demo` — demo admin is `admin@openzev.local` / `admin1234`
- If the backend starts failing with Postgres `too many clients already`, restart the backend container to release its connections.

### Backend

From `backend/`:

- Activate venv: `source ../.venv/bin/activate`
- Lint: `ruff check .`
- Run tests: `python -m pytest -q` (parallel; `-n 0` = serial, `-m "not slow"` = skip slow PDF tests; counts: `pytest -v | tail -2`, pipe masks exit code)
- Run invoice tests only: `python -m pytest invoices -q`

### Frontend

From `frontend/`:

- Lint: `npm run lint` and `npm run lint:style`
- Color-literal sweep: `node ../scripts/check-frontend-hex.mjs` — raw hex/rgb()/rgba() is rejected outside the design tokens; an alpha shadow/scrim needs its file added to `scripts/hex-migration-allowlist.json` with an `@alpha` suffix
- Unit tests: `npm run test:unit`
- Build: `npm run build`
- Screenshots against the running dev stack: `npm run shot` (one-off) or `npm run screenshots` (user-guide set). The Playwright config defaults to the production-like ports, so for the dev stack set `SCREENSHOT_BASE_URL=http://localhost:5173 SCREENSHOT_API_URL=http://localhost:8001/api/v1`. `npm run shot` renders in English (`SHOT_LANG`); other specs use the config's `de-CH` locale, so match button labels accordingly.

## Working Agreements

- Prefer small, targeted changes.
- Preserve existing style and naming.
- Do not reformat unrelated code.
- Update TypeScript types when backend response shapes change.
- When changing API behavior, update backend tests and frontend consumers together.
- For invoice workflow changes, verify both backend permissions/workflow rules and frontend action visibility.

## Spec-Driven Development

For larger or risky changes, consult or create specs and ADRs:

- **Specs** (`docs/specs/`) document feature changes and should be created for:
  - API behavior or response shape changes
  - Billing or tariff calculation logic changes
  - Invoice workflow state changes
  - Data model or migration changes
  - Async job, retry, or delivery guarantees
  - Security, auditability, or role/ZEV-scope changes

- **ADRs** (`docs/adr/`) document architecture decisions and should be created for:
  - High-impact decisions affecting multiple systems
  - Important decisions future maintainers should understand
  - Decisions worth revisiting during refactors

- **Baseline specs** describe the current implementation at field-level detail (models, API endpoints, serializers, frontend components, TypeScript types, test counts). They should be updated when those features change:
  - `2026-03-community-and-access.md` — users, roles, auth, JWT, permissions, ZEV scoping, navigation regroup, canonical routes + aliases, scope-aware shell, hubs and admin consolidation
  - `2026-03-metering-point-management.md` — participants, metering points, assignments
  - `2026-03-metering-import-and-quality.md` — SDAT/Excel/CSV import, data quality
  - `2026-03-tariffs-and-billing-engine.md` — tariffs, billing modes, invoice generation
  - `2026-03-invoice-lifecycle-and-communication.md` — invoice workflow, email, PDF rendering, readiness/attention cockpit, period overview, generation eligibility
  - `2026-03-admin-governance-and-settings.md` — AppSettings, VAT, admin dashboard, ZEV config
  - `2026-05-audit-log-and-operational-traceability.md` — audit event stream, scoped visibility, redaction
  - `2026-08-zev-transfer-archive.md` — whole-ZEV export/import archive
  - `2026-08-contract-pdf-redesign.md` — contract PDF design, context, shared PDF design base
  - `2026-08-ui-redesign-pdf-style.md` — UI design system, print parity, shared tokens, PDF previews

- **Reference specs** document reusable cross-cutting patterns that should guide future work even when no baseline feature spec changes directly:
  - `2026-04-frontend-management-page-design.md` — reference spec for frontend CRUD / management-page cleanup, action hierarchy, page grouping, icons, i18n discipline, and responsive layouts

- **Completed feature specs** describe shipped capabilities with their own implementation spec (`2026-08-shared-metering-points.md`, `2026-09-vse-tariff-import.md`, `2026-09-tariff-overview-pdf.md`, `2026-09-participant-invoice-access.md`, `2026-09-dynamic-tariffs.md`, `2026-09-bfe-reference-market-price.md`). Update the linked spec when the capability changes; they are not baselines.

- When you create or modify a spec, link it in your PR using `.github/PULL_REQUEST_TEMPLATE.md`.

### Spec maintenance rules

When making code changes, follow these rules to keep specs accurate:

1. **Before coding:** Read the relevant baseline spec(s) to understand documented behavior.
  For frontend CRUD / management-page cleanup work, also read `2026-04-frontend-management-page-design.md` before making layout or interaction changes.
2. **After coding:** If your change modifies behavior described in a baseline spec, update the affected sections of that spec in the same commit/PR.
3. **What to update:** Only the sections that changed — don't rewrite unrelated parts. Common updates include: adding/removing model fields, changing API endpoints or permissions, adding tests, modifying frontend components.
4. **Validation:** After updating a spec, verify every claim in the changed sections against the actual code. Check field names, types, defaults, permission classes, endpoint paths, serializer fields, test method names, and test counts.
5. **New features:** If a new feature doesn't fit any existing baseline spec, create a new spec using `docs/specs/TEMPLATE.md`. Use the same implementation-grade detail level as the baseline specs.
6. **Quality bar:** A spec is correct when someone could re-implement the described feature from the spec alone, without reading existing code.

For detailed guidance, see `docs/specs/README.md` and `docs/adr/README.md`.

## Validation Expectations

After relevant changes, run what CI runs for the side you touched:

- Backend: `ruff check .`, `python manage.py check`, `python -m pytest -q`
- Frontend: `npm run lint`, `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`, `npm run build`
- For user-facing frontend changes, also check the change in the running dev stack (screenshot it, check the console for errors), including a narrow (~400px) viewport.

## Documentation

- **User guide** (`docs/user-guide/`): when a change alters what a user sees or does, update the matching chapter in the same PR. Its screenshots are regenerated as a set with `npm run screenshots`, not edited one by one.
- **Release notes** (`docs/release-notes/`): written for minor and major releases only, using the `release-notes` skill. Don't write them per PR, and never hand-edit `CHANGELOG.md` — release-please regenerates it on every merge.

## Git and Pull Requests

- Never commit to `main`; branch off an up-to-date `origin/main`.
- PR titles follow Conventional Commits (`feat(scope): ...`, `fix(scope): ...`) — CI checks this.
- Fill in `.github/PULL_REQUEST_TEMPLATE.md` (linked spec, validation).
- **Before pushing follow-up commits to an existing PR branch, check the PR is still open** (`gh pr view <number> --json state`). If it was merged or closed in the meantime, do not push to that branch: create a new branch from `origin/main`, cherry-pick the new commits, and open a new PR.
- After pushing, check CI (`gh pr checks <number>`) rather than assuming it passes.

## Safe Editing Guidance

- Check for unstaged local changes before assuming previous behavior came from git history.
- If restoring behavior, compare against current diff and existing UI components first.
- Reuse existing shared components and CSS utilities where possible.
- The frontend is translated with `react-i18next`. All language files are in `frontend/src/i18n/locales`. Make sure to use and extend it if necessary. No hardcoded user facing text in any language in the frontend, always use i18n.

## File Placement

- Put new backend tests near the affected app test module.
- Put shared frontend UI in `frontend/src/components/`.
- Put API contract types in `frontend/src/types/api.ts`.
