# ADR 0039: Analytics goes through a scoped dataset API, never direct database access

- Status: Accepted
- Date: 2026-10-17

## Context

[#1058](https://github.com/splattner/openzev/issues/1058) asks for self-service analytics: managers
and participants should explore their metering data (self-sufficiency over two years, a load
duration curve, "when do I use the most energy") without exporting to Excel, and without
OpenZEV building a BI tool. Two kinds of off-the-shelf tooling suggest themselves, and both
reach for the database:

- **Grafana (or Metabase, Superset) on PostgreSQL.** A database user sees every ZEV. The
  per-ZEV grants of [ADR 0027](0027-per-zev-access-grants.md) and the participant scoping that
  hides a neighbour's profile would have to be re-implemented as row-level security in a second
  place, and would drift from the first.
- **Free SQL in the app.** The same problem, plus load and injection risk.

A second reason is independent of access: the numbers people ask about are **not stored**. A
`metering_meterreading` row is kWh per meter and direction. The local / grid / feed-in split
that invoices and dashboards show is computed per timestamp in Python by the allocation read
model ([ADR 0013](0013-shared-allocation-service.md)) from the physical community totals, the
assignment windows (including community-mode weights) and the pool arithmetic. A tool reading
the table can show raw consumption, never "how much of it was local", and any reimplementation
of the split is a second billing formula.

Finally, the data is bucketed by Swiss civil time ([ADR 0026](0026-swiss-civil-time-for-billing.md)),
which a generic tool does not know about (23- and 25-hour days).

## Decision

**Analytics reads one server-computed, scoped, tidy dataset. No analytics tool gets SQL or
database credentials.**

1. **One endpoint, `GET /api/v1/analytics/series/`**, returns long-format rows
   (`bucket_start`, `metering_point`, `participant`, `direction`, `total_kwh`, `local_kwh`,
   `grid_kwh`, `feed_in_kwh`, `source`) as JSON or CSV. Slicing, pivoting and charting is the job
   of tools consuming it (Recharts, a pivot engine, Grafana's Infinity datasource); the server
   only answers "what may this caller see, at which granularity".
2. **The rows are built from `allocation.read_model`**, the module the invoice engine and the
   PDF statistics use, so a sum over the dataset reproduces the invoice and dashboard numbers.
   The dataset module contains no allocation arithmetic of its own.
3. **Visibility is decided in one function** (`analytics.scope.resolve_visibility`) on top of
   `zev.access`: an admin, manager or viewer sees the whole ZEV; a participant sees only the
   rows attributed to their own live participant records. A community-mode share of a meter held
   by somebody else is reported without naming the meter. ZEV-wide totals are shown to a
   participant only when at least *k* participants (default 5, `ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE`)
   shared the ZEV on every day of the range, because with fewer, "ZEV total minus me" is
   somebody else's load profile.
4. **Tools that cannot hold a session use a scoped token**, not a database login and not a
   whole-account API key. An `AnalyticsToken` (`oza_…`, hashed like `ApiKey`, revocable,
   expiring, audited) is limited to one ZEV, or to one participant of it, and to this one
   endpoint. It never exceeds its creator: each request re-checks that the creator can still see
   what the token is scoped to. Creating tokens is behind the feature flag
   `analytics_tokens_enabled` (default off), because it lets data leave the instance.
5. **Cost is bounded explicitly.** The dataset is computed live; the number of readings scanned,
   the span per granularity and the output rows are capped, and a request over a cap is refused
   with a message telling the caller what to narrow. An hourly allocation fact table that lifts
   the caps is a separate, measured decision (spec §9); `analytics.dataset.build_series` is the
   seam it would replace.
6. **Supplementary (behind-the-meter) data is not in the dataset.** It is not billing input
   ([ADR 0030](0030-supplementary-energy-data-is-not-billing-input.md)) and it is more personal
   than metering data. The `source` column exists (`metering` today) so it can be added as its own
   source, with its own visibility rule, without changing the shape.

Grafana on PostgreSQL stays unsupported: it is possible for a self-hoster who accepts that it
bypasses scoping and has no allocation split, and the documentation says so.

## Consequences

Positive:
- "What may this user see" stays in one place; a new analytics client cannot widen it.
- Numbers reconcile with invoices by construction.
- Any HTTP-capable tool works (Grafana Infinity, spreadsheets, n8n, scripts), with no
  Grafana-specific server code.

Trade-offs:
- Live computation is Python-speed: about 50,000 readings per second measured on SQLite, so the
  default cap of 300,000 readings keeps a request near six seconds. A 25-meter ZEV can therefore
  query roughly four months at once until the fact table exists.
- The endpoint is a second path to the same data as the dashboards; both must stay on the read
  model (a parity test compares them).
- A token is a long-lived credential. It is narrower than an API key, but it is still one more
  thing to expire and revoke.

## Alternatives considered

1. **Grafana/Metabase/Superset on the database.** Rejected: bypasses scoping, no allocation
   split (see Context).
2. **Compute the split in SQL / a database view.** Rejected: a second implementation of the
   billing formula, and community-mode weights per day are not expressible simply.
3. **Reuse the API key for Grafana.** Works today and stays possible, but a key carries the whole
   account; the token narrows it to one ZEV or participant and to reads of this dataset.
4. **Add the dataset to the MCP server only.** Rejected as the foundation: MCP answers questions
   for assistants, not for dashboards; it may reuse this module later.
