# ADR 0017: Async export jobs for whole-ZEV annual statements

Status: accepted. Supersedes the earlier subprocess-pool experiment for annual
statements — that experiment was never merged, and its record now lives in
[Alternatives considered](#alternatives-considered) below.

## Context

The whole-ZEV annual-statement download renders one PDF per eligible
participant and packs them into a ZIP. On large ZEVs that render takes minutes,
which collided with the web server's request timeout. An earlier experiment
rendered the batch in short-lived subprocess workers (up to four per serving
process) inside the request and stacked ever-higher timeouts around it
(pool 600 s < Gunicorn 610 s < nginx 620 s < ingress 660 s).

That design has structural costs:

- **A web request stays open for minutes.** The UI cannot tell the user
  anything beyond a spinner, reload loses the operation entirely, and every
  layer of the deployment must be tuned to tolerate a single request that long.
- **Parallelism is paid for with subprocess complexity.** Spawning, reaping,
  watchdog threads, and a pickled wire protocol exist only to keep the request
  under its deadline — complexity that vanishes once the request no longer has
  to finish the work.
- **The subprocess pool is process-local.** It serializes batches per serving
  process but cannot coordinate across replicas or dedicated workers.

Meanwhile the platform already has the machinery that fits this workload:
Celery workers with a Redis broker, a shared database, and — because invoice
PDFs and emails already need it — artifact storage that is mounted into both
the web service and the worker in every deployment shape (docker-compose
`backend_media` volume, the fullstack single container, and the Helm media PVC
shared by the backend and worker deployments).

## Decision

Whole-ZEV annual-statement exports are **asynchronous export jobs**: a small,
persistent `ExportJob` row (new `exports` app) records the operation, a Celery
task executes it off the request path, and the completed artifact is stored in
the shared media storage for a bounded retention window before the periodic
sweep deletes the file.

- **Lifecycle.** `queued → running → completed / failed`. Creation returns
  `202` with the persisted job and enqueues it after the row is committed; the
  frontend polls the job's status and offers a download when it completes. A
  repeat request while an identical job (same requester, ZEV and year) is still
  `queued` or `running` returns that job instead of scheduling a second render
  of the same data; the UI also disables the button while a create request is
  in flight.
- **Enqueue failures are surfaced, not swallowed.** If the task cannot be
  handed to the broker, the job is marked `failed` with a safe message and
  creation returns `503` — never a `202` for a job that will not run. The
  sweep's "never claimed" recovery is a backstop for tasks genuinely lost in
  the broker, not the expected path for a broker that is down.
- **Per-job time budget.** Each job carries the budget itself: the Celery task
  has a soft time limit at `EXPORT_RUNNER_TIMEOUT_S` (raised as
  `SoftTimeLimitExceeded`, recorded as a clean failure before the worker winds
  down) and a hard time limit a grace above it that terminates a render wedged
  inside native code. The periodic sweep only recovers what limits cannot: a
  `running` job whose worker died is failed once it is past the hard limit plus
  a further grace, and a `queued` job whose task was lost is failed only after
  it has waited far longer than any healthy backlog, so a backed-up queue is
  not misread as lost work. The sweep runs on the hourly beat schedule and
  opportunistically at the start of every job, so a deployment without a beat
  process still recovers stale jobs while jobs execute.
- **Snapshot on request.** Each export renders from the data at the time the
  job runs, and the result is frozen in a stored file. Corrected readings show
  up in a *newly generated* export; an already-completed ZIP stays as it was
  until it expires. Generation does **not** guarantee a transactionally
  consistent snapshot across concurrent data changes (same semantics as the
  former in-request render).
- **Serial rendering in the worker.** The job reuses the existing
  `generate_annual_statement_pdf` path and computes the ZEV-wide share map and
  per-timestamp community totals once per batch. No subprocess pool: Celery
  already removes the request-timeout constraint, and Celery's own concurrency
  runs jobs in parallel across workers. Parallelizing *one* job's documents is
  deliberately deferred — revisit only when a measured single-job render time
  becomes operationally unacceptable.
- **Artifact publishing.** The ZIP is written to configured Django storage only
  after it is fully built; a failure never leaves a partial file behind, and an
  orphaned file from a failed save or publish is deleted. Completion is a
  conditional `UPDATE` on the still-`running` row: a job the sweep already
  failed is never resurrected by a late render — its artifact is discarded and
  the job stays `failed`. The file name embeds the job pk. Download serves the
  stored file with `FileResponse` streaming, re-checking access and expiry.
- **Expiry and retention.** Retention starts **at completion**: `file_expires_at`
  is `completed_at` plus `EXPORT_RETENTION_HOURS` (default 24 h), so a long
  render does not eat into the download window. The sweep then deletes the
  file; job metadata rows are retained as part of the operation's audit story.
- **Failure semantics.** Individual statement failures omit only that statement
  and are recorded in an `omitted.txt` manifest inside the archive; the job
  completes with omission counts the UI shows. If every statement fails (or the
  shared yearly-data calculation fails), the job is `failed`, produces no
  download, and surfaces a safe error message — tracebacks stay in server logs.
  A completed job is retried by preparing a new export, never by silently
  re-rendering.
- **Delivery safety.** The task claims the job atomically (`queued → running`),
  so duplicate task delivery cannot render the same job twice.
- **Access.** Jobs are scoped to their requester, and list, status and download
  all re-check that the caller may still read the job's ZEV — a requester who
  lost ownership stops seeing their old jobs' metadata as well as their files.
- **Audit.** Job creation (`annual_statement_export.created`, status `queued`)
  and completion outcomes (`...completed` / `...failed`, including enqueue
  failures and sweep recoveries) are recorded on the existing audit stream with
  CELERY or API source, mirroring the invoice bulk generation events.
- **Shared PDF font configuration (supporting change).** Whole-ZEV batches
  render many documents back-to-back in one worker process, so
  `render_pdf()` reuses one lazily-created `FontConfiguration` per process
  instead of rescanning system fonts for every document. Access is serialized
  by a process-local lock because Pango's font map is not thread-safe — under
  the shipped pre-fork/sync web and worker shapes the lock is uncontended, and
  only threaded servers (gthread, the dev server) serialize on it. An
  admin-editable template that installs `@font-face` rules invalidates the
  shared configuration after that render, so one document's fonts and caches
  cannot leak into later renders.
- **Generic core.** The job lifecycle, endpoints, sweep, and storage handling
  live in a new `exports` app and are driven by a per-`export_type`
  validator/renderer registry. Annual statements are the first registered type;
  future exports (tariff overviews, transfer archives) reuse the lifecycle
  without duplicating it.

## Consequences

- No subprocess pool, worker module, or timeout-layering exists anywhere in the
  tree; web, nginx and ingress keep their ordinary timeouts.
- New exports require storage shared between the web service and Celery
  workers. That is already true in every deployment shape (compose media
  volume, fullstack container, Helm media PVC); no new infrastructure is
  needed, only documented sizing for transient artifact disk (bounded by
  concurrency × retention window).
- A job that is `queued` but whose broker never delivered the task fails only
  after the (deliberately long) queued window passes; operators see the
  failure rather than a stuck row, while a healthy backlog is not failed as
  lost.
- A wedged render is bounded by the task's hard time limit rather than the
  sweep; the sweep is the recovery for a dead worker, not the enforcement
  mechanism for a slow one.
- If a worker dies mid-render (e.g. OOM on a large ZEV), nothing updates the
  row — the job only *becomes eligible* for recovery once it is past the
  sweep's stale-running cutoff (hard limit plus grace: 2700 s + 900 s = 60 min
  at defaults). Actual recovery happens on the next sweep run: the hourly beat
  schedule, so up to nearly another hour, or — without a Beat process — only
  opportunistically at the start of the next export. That conservatism is
  deliberate (healthy long renders must not be failed as lost), but operators
  should expect "preparing" to linger well past the hour after the work is
  already dead. The card's own wall-clock polling backstop is also an hour.
- Real-PDF end-to-end coverage no longer spawns subprocesses; the slow test
  runs the renderer inside the worker task path instead.

## Alternatives considered

- **Keep rendering in the request, parallelized by a subprocess pool.** The
  experiment that preceded this ADR: annual-statement batches of at least four
  documents rendered in short-lived subprocess workers (default four, clamped
  to CPU count), with a pickled wire protocol, a watchdog thread per child,
  and a per-deployment timeout ladder (pool 600 s < Gunicorn 610 s < nginx
  620 s < ingress 660 s). Measured on a 16-CPU host with a 20-participant
  full-year fixture it roughly halved wall time (serial ≈ 68–73 s vs
  pool ≈ 27–30 s) at ~4× peak memory, and small batches were indistinguishable
  from serial. Those gains did not justify the structural costs above, and the
  numbers are recorded here so the single-job-parallelism question can be
  revisited against a concrete baseline (the deployment then keeps ordinary
  timeouts; the request is no longer the unit of work). Superseded.
- **Persist issued annual statements as permanent documents.** A different
  product decision about issuance, historical records, and invalidation;
  explicitly out of scope here and can build on this job flow later.
