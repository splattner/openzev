# ADR 0004: Asynchronous invoice email delivery with audit logs

- Status: Accepted
- Date: 2026-03-24

## Context

Invoice emails require PDF generation, template rendering, external SMTP delivery, retries, and user-visible status tracking. Doing this synchronously in request/response would increase latency and fail unpredictably on transient email issues.

The current system already uses Celery + Redis and keeps per-invoice email logs.

## Decision

Deliver invoice emails asynchronously via Celery tasks with persistent delivery audit trail.

- Queue `send-email` operations as background tasks.
- Ensure PDF exists before sending.
- Record each send attempt in `EmailLog` (`pending`/`sent`/`failed` with error details).
- Retry failed task execution up to configured task retry count.
- Reflect latest email status in invoice UI and allow explicit retry from failed logs.

## Consequences

Positive:
- Non-blocking API calls for email sends.
- Better resilience to transient SMTP issues.
- Clear operational observability through per-attempt logs.

Trade-offs:
- Eventual consistency between enqueue and visible final status.
- Extra infrastructure dependency on worker + broker health.

## Alternatives considered

1. Synchronous email sending inside invoice API endpoints.
   - Rejected due to latency and reliability concerns.
2. Fire-and-forget without delivery logs.
   - Rejected because operators need traceability and retryability.
