# Feature Specifications

This directory contains feature and change specifications used for spec-driven development in OpenZEV.

The process is inspired by GitHub Spec Kit and adapted to this repository.

## When a spec is required

Create or update a spec for changes that are large, risky, or cross-cutting, especially when they affect:

- API behavior or response shape
- Billing or tariff calculation logic
- Invoice workflow states or permissions
- Data model or migrations
- Async jobs, retries, or delivery guarantees
- Security, auditability, or role/ZEV-scope enforcement

You can usually skip a full spec for small bugfixes, copy updates, or isolated UI polish.

## Quality standard

Specs should contain **implementation-grade detail** — enough that a developer could re-implement the described feature from the spec alone, without reading the existing code. This means:

- **Data models:** Field-level tables with types, defaults, constraints, and validation logic
- **API contracts:** Exact endpoint paths, HTTP methods, permission classes, request/response shapes
- **Serializers:** Field lists and read-only designations
- **Frontend:** Page component names, file paths, route paths, TanStack Query keys, mutation flows
- **TypeScript types:** Exact interface definitions matching backend response shapes
- **Test plan:** Test class names, individual test method names, what each test asserts, and test counts

The baseline specs serve as reference for the expected detail level.

## Workflow

1. Copy `TEMPLATE.md` into a new file named `YYYY-MM-short-title.md`
2. Fill in all sections — see the template's HTML comments for guidance
3. Link related ADRs and issues
4. Reference the spec in the pull request
5. Update the spec when implementation decisions change

## Updating baseline specs

Baseline specs describe the current implementation. They must be kept in sync:

- **When to update:** Any PR that changes behavior described in a baseline spec must update that spec in the same PR.
- **What to update:** Change only the affected sections. Don't rewrite unrelated parts.
- **How to validate:** After updating, verify every claim against the actual code (model fields, view logic, serializer shapes, frontend components, test counts). Fix any inaccuracies found.
- **Scope mapping:** Use the table below to identify which baseline spec to update.

| Change area | Baseline spec to update |
|---|---|
| User model, roles, auth, JWT, permissions | `2026-03-community-and-access.md` |
| Participant, MeteringPoint, MeteringPointAssignment models | `2026-03-metering-point-management.md` |
| MeteringData import, SDAT/Excel/CSV parsing, data quality | `2026-03-metering-import-and-quality.md` |
| Tariffs, TariffPeriod, billing engine, invoice generation | `2026-03-tariffs-and-billing-engine.md` |
| Invoice workflow, email sending, PDF rendering, EmailLog | `2026-03-invoice-lifecycle-and-communication.md` |
| AppSettings, VatRate, admin dashboard, PDF template, ZEV config | `2026-03-admin-governance-and-settings.md` |

## Conventions

- Keep specs concise and implementation-oriented
- Put exactly one coherent initiative in each spec
- Prefer explicit acceptance criteria over vague goals
- For architecture-level decisions, create or update an ADR in `docs/adr/`

## Baseline specs

These specs describe the current major product capabilities and should be updated when those capabilities are changed:

- `2026-03-community-and-access.md`
- `2026-03-metering-point-management.md`
- `2026-03-metering-import-and-quality.md`
- `2026-03-tariffs-and-billing-engine.md`
- `2026-03-invoice-lifecycle-and-communication.md`
- `2026-03-admin-governance-and-settings.md`
