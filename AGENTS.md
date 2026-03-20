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

## File Placement
- Put new backend tests near the affected app test module.
- Put shared frontend UI in `frontend/src/components/`.
- Put API contract types in `frontend/src/types/api.ts`.
