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
- Retry a **failed SMTP send** up to configured task retry count. Retrying
  resends the message, so nothing past that point may trigger it — see
  "Post-delivery bookkeeping is not part of the retried step" below.
- Reflect latest email status in invoice UI and allow explicit retry from failed logs.

### Post-delivery bookkeeping is not part of the retried step (#576)

The SMTP send and everything after it (`EmailLog` → `sent`, the invoice's
`approved` → `sent` transition, the success audit event) originally shared
one exception handler, so a failure in any of those bookkeeping writes was
indistinguishable from the send itself failing: the log was marked `failed`
and the task retried, resending an email the recipient had already
received. A `failed` `EmailLog` is also what the explicit-retry action
checks for, so the mislabelling could additionally let an operator trigger a
second manual resend.

The send is now its own try/except; nothing after it can retry the task or
mark the `EmailLog` `failed`. A bookkeeping failure there is logged and
recorded as its own `FAILED` audit event (still naming the delivery as
having happened, via `metadata.delivered = true`) instead, leaving a visible
gap an operator resolves with the existing "Mark sent" action rather than a
resend.

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
