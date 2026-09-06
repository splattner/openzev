"""Render annual-statement batches in short-lived subprocesses.

Subprocess fan-out via ``subprocess.Popen`` (not ``multiprocessing``) keeps
this usable from daemonic workers too; the only production caller is the
annual-statements ZIP endpoint.

Protocol: the parent spawns ``python -m invoices.pdf_worker`` per chunk and
feeds it one trusted pickle of ``(worker_callable, chunk_args)`` on stdin;
the child replies with one pickle ``(status, result)`` on stdout, where
status is ``ok``, ``error`` (result is the exception object) or
``startup_error``. The worker duplicates fd 1 for the protocol pipe and
redirects its stdout to stderr before processing, so neither Python-level
nor native output can corrupt the pickle pipe.
"""

from __future__ import annotations

import logging
import os
import pickle
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)

_MIN_BATCH_FOR_POOL = 4
_WORKER_MODULE = "invoices.pdf_worker"
_BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Concurrent requests in one serving process share the same worker budget.
_batch_gate = threading.Lock()


def _available_workers() -> int:
    """Configured worker cap, clamped to [1, CPU count] available here.

    Prefers ``os.process_cpu_count()`` (scheduler affinity on 3.13+); older
    runtimes fall back to ``sched_getaffinity``, then to ``os.cpu_count()``.
    Affinity is not a quota: a container limited by CPU shares still reports
    its visible CPUs, so quota-limited deployments must set
    ``PDF_POOL_MAX_WORKERS`` explicitly instead of relying on this count.
    """
    from django.conf import settings

    counter = getattr(os, "process_cpu_count", None)
    if counter is not None:
        cpus = counter()
    elif hasattr(os, "sched_getaffinity"):
        cpus = len(os.sched_getaffinity(0))
    else:
        cpus = os.cpu_count()
    cpus = cpus or 1
    return max(1, min(int(settings.PDF_POOL_MAX_WORKERS), cpus))


def _split_into_chunks(items, n_chunks: int) -> list[list]:
    """Split ``items`` into at most ``n_chunks`` contiguous, balanced chunks.

    Input order is preserved across the chunks and empty chunks are never
    returned.
    """
    items = list(items)
    if not items or n_chunks <= 0:
        return []
    chunk_count = min(n_chunks, len(items))
    size, extra = divmod(len(items), chunk_count)
    chunks = []
    start = 0
    for index in range(chunk_count):
        end = start + size + (index < extra)
        chunks.append(items[start:end])
        start = end
    return chunks


def _terminate_and_reap(processes: Sequence[subprocess.Popen]) -> None:
    """Stop children before joining threads blocked in communicate()."""
    for process in processes:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                # Exited between poll() and kill(); wait() below still reaps it.
                pass
    for process in processes:
        process.wait()


def _close_process_pipes(processes: Sequence[subprocess.Popen]) -> None:
    for process in processes:
        process.stdin.close()
        process.stdout.close()


def _communicate(process, request):
    stdout, _ = process.communicate(input=request)
    if process.returncode != 0:
        raise RuntimeError(f"PDF worker exited with status {process.returncode}")
    status, result = pickle.loads(stdout)
    if status == "ok":
        return result
    if status == "error":
        raise result
    if status == "startup_error":
        raise RuntimeError(f"PDF worker startup failed: {result}")
    raise RuntimeError(f"PDF worker returned an invalid status: {status}")


def _run_processes(worker: Callable, chunks: Sequence, deadline: float):
    processes = []
    executor = None
    try:
        requests = [pickle.dumps((worker, chunk)) for chunk in chunks]
        for _ in chunks:
            process = subprocess.Popen(
                [
                    sys.executable, "-u", "-m", _WORKER_MODULE,
                    # Our PID is the worker's parent; the worker's watchdog
                    # exits if we are SIGKILL'd and cannot run cleanup.
                    str(os.getpid()),
                ],
                cwd=_BACKEND_ROOT,
                env={
                    **os.environ,
                    "DJANGO_SETTINGS_MODULE": os.environ.get(
                        "DJANGO_SETTINGS_MODULE", "config.settings",
                    ),
                },
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            processes.append(process)

        # Feed and drain every pipe concurrently: sequential communicate()
        # would leave the other workers waiting for their input.
        executor = ThreadPoolExecutor(max_workers=len(processes))
        futures = {
            executor.submit(_communicate, process, request): index
            for index, (process, request) in enumerate(zip(processes, requests))
        }
        results = [None] * len(processes)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("PDF worker batch exceeded its deadline")
        for future in as_completed(futures, timeout=remaining):
            results[futures[future]] = future.result()
        return results
    finally:
        # Killing children must precede shutdown(wait=True), including when
        # a submit fails or the serving process receives a soft time limit.
        _terminate_and_reap(processes)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        _close_process_pipes(processes)


def _run_chunks(worker: Callable, chunks: Sequence, workers: int):
    """Run chunk callables in bounded, short lived subprocesses.

    ``None`` means no workers are available; smaller batches and one-worker
    configurations stay serial in the caller and never reach this function.
    Spawn failures propagate without serial retry, and a late failure
    leaves no budget for a second full batch. The deadline starts before
    this batch acquires ``_batch_gate`` and covers worker startup plus
    completion; overall request limits are the caller's concern.
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    chunks = list(chunks)
    if not chunks:
        return []
    if workers < 1:
        return None
    if len(chunks) > workers:
        raise ValueError("PDF batch contains more chunks than configured workers")

    timeout_s = getattr(settings, "PDF_POOL_TIMEOUT_S", 600)
    if timeout_s <= 0:
        raise ImproperlyConfigured("PDF_POOL_TIMEOUT_S must be positive.")
    deadline = time.monotonic() + timeout_s
    if not _batch_gate.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise TimeoutError("PDF worker batch exceeded its deadline")
    try:
        return _run_processes(worker, chunks, deadline)
    finally:
        _batch_gate.release()


def _render_statement_chunk(args) -> list:
    """Worker entry: render statements and return ``(id, pdf, error)``."""
    participant_ids, zev_id, year, share_windows = args
    from django.db import connections
    from datetime import date
    from allocation.validity import period_window
    from allocation.read_model import (
        community_totals_by_timestamp,
        eligible_participant_shares,
    )
    from invoices.annual_statement import generate_annual_statement_pdf
    from zev.models import Participant, Zev

    try:
        zev = Zev.objects.get(pk=zev_id)
        year_start_dt, year_end_dt = period_window(
            date(year, 1, 1), date(year, 12, 31),
        )
        zev_totals_by_ts = community_totals_by_timestamp(
            zev, year_start_dt, year_end_dt,
        )
        shares_by_date = eligible_participant_shares(
            zev, date(year, 1, 1), date(year, 12, 31),
            windows=share_windows,
        )

        results = []
        for participant in Participant.objects.filter(id__in=participant_ids).order_by("id"):
            try:
                pdf_bytes = generate_annual_statement_pdf(
                    participant,
                    zev,
                    year,
                    shares_by_date=shares_by_date,
                    zev_totals_by_ts=zev_totals_by_ts,
                )
                results.append((participant.id, pdf_bytes, None))
            except Exception as exc:
                # The full traceback only exists here in the child; keep it
                # for the logs before reducing the result to a string.
                logger.exception(
                    "Annual statement failed for participant %s", participant.id,
                )
                results.append((participant.id, None, str(exc)))
        return results
    finally:
        connections.close_all()


def render_statements_parallel(participants, zev, year, *, share_windows=None) -> list | None:
    """Render annual statements in child processes and restore input order."""
    ordered = list(participants)
    count = len(ordered)
    if count < _MIN_BATCH_FOR_POOL:
        return None
    workers = min(count, _available_workers())
    if workers < 2:
        return None

    id_chunks = [
        [participant.id for participant in chunk]
        for chunk in _split_into_chunks(ordered, workers)
    ]
    results = _run_chunks(
        _render_statement_chunk,
        [(chunk, zev.id, year, share_windows) for chunk in id_chunks],
        workers,
    )

    by_id = {
        participant_id: (pdf_bytes, error)
        for chunk in results
        for participant_id, pdf_bytes, error in chunk
    }
    return [
        (participant.id, *by_id.get(participant.id, (None, "statement never returned")))
        for participant in ordered
    ]
