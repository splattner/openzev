# ADR 0007: Timezone policy for storage, queries, and display

- Status: Accepted
- Date: 2026-03-24

## Context

OpenZEV processes metering timestamps, billing period boundaries, chart aggregations, imports, and invoice rendering. Timezone ambiguity can create off-by-one-day errors, especially around midnight and DST transitions. The existing code already uses explicit UTC boundaries in critical query paths to avoid local timezone conversion side effects.

## Decision

Adopt UTC as the canonical backend timezone for storage and interval filtering, and keep locale-aware formatting in the frontend/UI layer.

- Persist metering timestamps in UTC.
- Build period/date filters with explicit UTC start/end bounds (inclusive start, exclusive end).
- Interpret invoice period dates as date-only business boundaries and convert to UTC datetime bounds in backend services.
- Keep import timestamps normalized to UTC before persistence.
- Use frontend/app settings for display formatting only (short/long/date-time format), without changing persisted timezone semantics.

## Consequences

Positive:
- Prevents timezone drift in metering and invoice calculations.
- Reduces DST and local-time boundary regressions.
- Keeps billing logic deterministic across environments.

Trade-offs:
- Developers must be careful to avoid implicit local-time ORM shortcuts (`__date`) in critical flows.
- User-facing local date/time expectations must be handled explicitly in presentation code.

## Alternatives considered

1. Store and compute in local timezone (e.g. Europe/Zurich).
   - Rejected due to DST complexity and portability issues.
2. Mixed timezone handling by feature area.
   - Rejected because it increases cognitive load and bug surface.
