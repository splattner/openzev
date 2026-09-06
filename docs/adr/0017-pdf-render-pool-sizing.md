# ADR 0017: Annual-statement subprocess rendering

- Status: Accepted
- Date: 2026-09-06
- Related specs: [`2026-03-invoice-lifecycle-and-communication`](../specs/2026-03-invoice-lifecycle-and-communication.md) (§8.1)
- Related ADRs: none

## Context

Invoice batches and annual-statement ZIPs spend most of their time in the
single-threaded WeasyPrint pipeline: WeasyPrint's native font map is
serialized behind a process lock (`pdf_render.py`), so threads add no
rendering parallelism. Subprocess fan-out uses `subprocess.Popen` rather
than `multiprocessing`.

Invoice batches remain serial because benchmarks showed no benefit from
subprocesses, while annual statements nearly halved. The pool
therefore serves annual-statement ZIPs only; invoice PDFs always render
serially in the serving process.

## Decision

1. Annual-statement batches of at least `_MIN_BATCH_FOR_POOL` (4) documents
   use up to `PDF_POOL_MAX_WORKERS` subprocess workers (default 4, clamped
   to CPU count and document count). Smaller batches, single documents, and
   one-CPU processes render serially. Invoice PDF batches always render
   serially via `_render_pdfs`, regardless of size.
2. Workers are short-lived per batch: created for the batch, render their
   chunk, return `(participant_id, pdf_bytes, error)` rows, and are reaped
   before the batch returns. A process-local gate serializes pooled
   batches within each serving process; the `PDF_POOL_TIMEOUT_S` deadline
   (default 600 s) starts before the gate is acquired, so queue time counts
   against the budget. Timeouts above it are per deployment: nginx 620 s
   over Gunicorn 610 s (Compose/fullstack), ingress 660 s (Helm chart).
   The endpoint's own error path usually wins the race — not a guarantee:
   the deadline cannot interrupt a native render in the serial path, and a
   larger nginx timeout only removes a competing timeout rather than
   turning a Gunicorn-killed request into a controlled response.
3. The wire protocol is one trusted pickle `(worker, chunk)` on stdin and one
   result pickle `(status, result)` on stdout (`ok` / `error` / startup
   failure); the child duplicates fd 1 for the protocol pipe before
   redirecting stdout to stderr, so neither Python-level nor native output
   can corrupt it. The child logs the original traceback before the
   exception travels.
4. Failure policy — no serial retry after any abort: any spawn
   failure, crash, deadline expiry, or uncaught worker error kills and
   reaps all children and propagates as a generic `500`. Retrying
   in-process could re-run a document that crashed a child inside the
   serving process, and a late failure leaves no budget for a second full
   batch. Small batches and one-worker configurations render serially
   without ever spawning.
5. A watchdog thread in each child polls `os.getppid()` every 0.5 s and exits
   if the serving process was SIGKILL'd (portable; best-effort while native
   rendering holds the GIL).

## Measured behavior

`scripts/benchmark-pdf-batches.py` on this host (16 CPUs), fixture of 20
participants with full-year 15-minute readings.

**Annual statements — controlled comparison.** Serial
(`--workers 1`) versus parallel (`--workers 4`) on copies of one fixture,
alternating run order across two rounds, `runs+1` samples per run:

| Round | Serial first / repeat | Parallel first / repeat |
|---|---|---|
| 1 (serial, then parallel) | 74.0 s / 67.2 s | 29.9 s / 26.6 s |
| 2 (parallel, then serial) | 72.5 s / 69.5 s | 30.3 s / 29.1 s |

Serial ≈ 68–73 s, parallel ≈ 27–30 s: **≈ 40 s saved (≈ 58%)**, stable
across orders. The `sha256` document maps are byte-identical serial vs
parallel and across rounds (copies share participant PKs, so ZIP names are
deterministic). With that margin, annual statements keep the pool.
Small batches (3 docs, below the pool threshold) are indistinguishable
across versions (invoice ~3–9 s, annual ~19–20 s), as expected.

Focused deployment check (single 20-document annual ZIP, whole-tree RSS):

- Serial: ~120 s, ~224 MiB tree peak.
- Pool (4 workers): ~29–66 s across runs, ~917 MiB tree peak.

**PostgreSQL setup profile and worker sizing (this host, 16 CPUs,
postgres:18, same 20-participant fixture shape).** Setup-once in the
parent: `community_totals_by_timestamp` 2.12 s (2 × 35,040 entries),
`eligible_participant_shares` 0.14 s — 2.26 s total. Against a cold
database the serial ZIP took 152.9 s (setup 1.5%) and the 4-worker ZIP
43.6 s (setup 5.2%, 3.5× speedup). Warmed repeats: 2 workers ≈ 29 s at
432 MiB whole-tree peak PSS; 4 workers ≈ 16–19 s at 742 MiB peak PSS
(~150 MiB per extra worker, stable across repeats; PSS, unlike the
summed RSS above, does not double-count shared pages).

No parent-computed-maps prototype: children run concurrently,
so the wall-time saving is bounded by one setup (~2.3 s) minus the cost
of pickling MB-scale Decimal maps to every child — below the threshold
that would justify the complexity. 4 workers stay the default for speed
where memory allows; budget (web workers × `PDF_POOL_MAX_WORKERS`) peak
children — the fullstack default of 3 web workers allows 12 PDF children
across concurrent exports. The serving process additionally buffers every
PDF while constructing the ZIP, so its peak grows with document count and
size. Tune against measured CPU and peak memory for the deployment;
throughput is workload and host dependent; no hard-limit OOM probe was run.
Controlled rerun:
`scripts/benchmark-pdf-batches.py --directory <fresh> --setup-only`, copy
the fixture per configuration, then alternate serial (`--workers 1`) and
parallel (`--workers 4`) annual runs and compare the `sha256` maps as well
as the timings.

## Consequences

- Annual exports use bounded CPU parallelism from the web workers serving
  them; invoice rendering stays a simple serial loop with per-invoice
  isolation.
- Every parallel batch pays worker/Django startup (~3 s amortized) and ~4×
  peak memory for ~2× speed on a normal annual batch.
- Partial per-document failures keep the reporting (`omitted.txt`
  with ID plus name; `500` when every statement fails).
- Annual ZIPs still render in-request; moving large exports out of the
  request remains the durable fix.
