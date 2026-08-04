# ADR 0011: Asynchronous bulk invoice and PDF generation

- Status: Accepted
- Date: 2026-06-26

## Context

`POST /invoices/generate-all/` and `POST /invoices/generate-pdfs-all/` ran the
full billing engine (or WeasyPrint PDF rendering) synchronously inside the
request/response cycle, once per participant. For a ZEV with many participants
and a year-long period this means thousands of meter-reading rows per
participant and multi-second PDF renders, risking gateway timeouts and tying up
web workers. Email delivery already runs asynchronously via Celery (ADR 0004).

## Decision

Run bulk generation asynchronously via Celery, mirroring the email pattern.

- `generate-all` validates input and permissions, then queues
  `generate_zev_invoices_task` and returns `202 Accepted` with
  `{detail, queued: true, participant_count}`.
- `generate-pdfs-all` queues `generate_zev_pdfs_task` and returns `202` with
  `{detail, queued: true, invoice_count}`.
- The view records a `queued` audit event; the task records a final
  `success`/`failed` audit event with `source = celery`, including counts and
  error details. Per-participant failures (e.g. locked invoices) are
  isolated: the batch continues, and the task's audit event reports
  generated/failed counts plus per-participant errors instead of an HTTP 409.
- The frontend shows a "generation started" toast and re-polls the period
  overview a few times so results appear without a manual reload.
- Single-invoice `generate/` stays synchronous: its latency is acceptable and
  immediate 409 feedback for locked invoices is valuable in the UI.

## Consequences

Positive:
- No request timeouts on large ZEVs/periods; web workers stay responsive.
- Operational visibility through queued/success/failed audit events.
- Consistent async architecture with email delivery.

Trade-offs:
- Results are eventually consistent; the UI relies on period-overview refresh
  rather than a direct response payload.
- Engine validation errors surface in the audit log, not as HTTP errors.
- **Partial success is audit-log-only.** A participant whose invoice failed is
  simply absent from that period's invoice overview — nothing in the UI points
  at the Audit Log entry that names them. This is deliberate isolation: the
  batch never blocks on a single bad participant. The operator discovers and
  repairs partial success by re-running `generate-all` (it generates exactly the
  missing invoices again) or by opening the Audit Log for the ZEV, whose final
  `invoice.generate_all` event carries generated/failed counts and per-participant
  errors.

## Alternatives considered

1. Keep synchronous generation with a higher gateway timeout.
   - Rejected: does not scale and blocks web workers.
2. Per-participant fan-out (one Celery task per invoice).
   - Rejected for now: complicates completion tracking; a single task per ZEV
     period is sufficient and keeps audit semantics simple.
3. Job-status polling endpoint.
   - Deferred: period-overview already reflects generated invoices; a generic
     job API can be added later if needed.
