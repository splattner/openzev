# AGENTS.md

## Purpose

This file gives coding agents the minimum project-specific context needed to work safely and efficiently in this repository.

## Repository Layout

- `backend/` — Django + Django REST Framework backend
- `frontend/` — React + TypeScript + Vite frontend
- `docker-compose.yml` — local full-stack setup with backend, frontend, db, redis, and celery worker

## Key Stack

- Backend: Django, DRF, pytest
- Frontend: React, TypeScript, TanStack Query, Vite
- Async jobs: Celery + Redis
- DB: PostgreSQL

## Local Development Commands

### Full stack

- `docker compose up -d --build`

### Backend

From `backend/`:

- Activate venv: `source ../.venv/bin/activate`
- Run tests: `python -m pytest metering/ accounts/ invoices/ -q`
- Run invoice tests only: `python -m pytest invoices/tests.py -q`

### Frontend

From `frontend/`:

- Build: `npm run build`

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
  - `2026-03-community-and-access.md` — users, roles, auth, JWT, permissions, ZEV scoping
  - `2026-03-metering-point-management.md` — participants, metering points, assignments
  - `2026-03-metering-import-and-quality.md` — SDAT/Excel/CSV import, data quality
  - `2026-03-tariffs-and-billing-engine.md` — tariffs, billing modes, invoice generation
  - `2026-03-invoice-lifecycle-and-communication.md` — invoice workflow, email, PDF rendering
  - `2026-03-admin-governance-and-settings.md` — AppSettings, VAT, admin dashboard, ZEV config

- When you create or modify a spec, link it in your PR using `.github/PULL_REQUEST_TEMPLATE.md`.

### Spec maintenance rules

When making code changes, follow these rules to keep specs accurate:

1. **Before coding:** Read the relevant baseline spec(s) to understand documented behavior.
2. **After coding:** If your change modifies behavior described in a baseline spec, update the affected sections of that spec in the same commit/PR.
3. **What to update:** Only the sections that changed — don't rewrite unrelated parts. Common updates include: adding/removing model fields, changing API endpoints or permissions, adding tests, modifying frontend components.
4. **Validation:** After updating a spec, verify every claim in the changed sections against the actual code. Check field names, types, defaults, permission classes, endpoint paths, serializer fields, test method names, and test counts.
5. **New features:** If a new feature doesn't fit any existing baseline spec, create a new spec using `docs/specs/TEMPLATE.md`. Use the same implementation-grade detail level as the baseline specs.
6. **Quality bar:** A spec is correct when someone could re-implement the described feature from the spec alone, without reading existing code.

For detailed guidance, see `docs/specs/README.md` and `docs/adr/README.md`.

## Invoicing Notes

- Invoice overview page is period-based and uses the selected global ZEV.
- Billing intervals: `monthly`, `quarterly`, `semi_annual`, `annual`.
- Email behavior is asynchronous via Celery; frontend may poll for updated email status.
- Metering completeness in period overview is strict daily completeness, respecting participant and metering point validity ranges.

## Validation Expectations

After relevant changes:

- Backend: run `python -m pytest metering/ accounts/ invoices/ -q`
- Frontend: run `npm run build`

## Safe Editing Guidance

- Check for unstaged local changes before assuming previous behavior came from git history.
- If restoring behavior, compare against current diff and existing UI components first.
- Reuse existing shared components and CSS utilities where possible.
- The frontend is translated with `react-i18next`. All language files are in `frontend/src/i18n/locales`. Make sure to use and extend it if necessary. No hardcoded user facing text in any language in the frontend, always use i18n.

## File Placement

- Put new backend tests near the affected app test module.
- Put shared frontend UI in `frontend/src/components/`.
- Put API contract types in `frontend/src/types/api.ts`.
