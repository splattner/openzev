# ADR 0003: Role and ZEV-scope enforcement model

- Status: Accepted
- Date: 2026-03-24

## Context

OpenZEV is multi-tenant by ZEV and has multiple user roles (`admin`, `zev_owner`, `participant`, `guest`). Data safety depends on preventing cross-ZEV access while still allowing admins global visibility and owner workflows over their own ZEVs.

Backend APIs already scope querysets by user role, and the frontend applies route guards and selected-ZEV filtering for manager roles.

## Decision

Use layered authorization with backend as source of truth and frontend as UX guardrail.

- Enforce access in backend queryset/permission logic per role and ownership.
- Treat `admin` as globally scoped, `zev_owner` as owner-scoped, and `participant` as self-scoped.
- Keep frontend `ProtectedRoute` role checks and `ManagedZevProvider` selection to prevent accidental out-of-scope operations.
- Persist selected ZEV in local storage for manager UX continuity.

## Consequences

Positive:
- Defense in depth (backend enforcement + frontend guardrails).
- Clear tenant boundary around ZEV ownership.
- Better usability for admins/owners via stable selected-ZEV context.

Trade-offs:
- Some filters are duplicated between frontend and backend.
- Role/scoping logic must remain synchronized across pages and endpoints.

## Alternatives considered

1. Frontend-only access filtering.
   - Rejected because authorization must be server-enforced.
2. Backend-only strict scoping without selected-ZEV UX state.
   - Rejected due to poor operator experience in multi-ZEV workflows.
