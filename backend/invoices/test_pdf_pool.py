"""Annual-statement subprocess rendering and failure cleanup."""

import os
import pickle
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from invoices import pdf_pool

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="PDF subprocess pool tests require POSIX process semantics (waitpid, signals).",
)


def _raise_runtime(_chunk):
    raise RuntimeError("worker failed")


def _raise_soft_limit(_chunk):
    raise SoftTimeLimitExceeded()


def _crash_or_hang(chunk):
    """First chunk exits without a protocol answer; the sibling keeps working
    and must be killed when the crash is noticed."""
    if chunk[0]:
        os._exit(3)
    time.sleep(60)
    return chunk


def _handshake_work(chunk):
    """Prove overlap with a bounded readiness handshake.

    Each child marks itself started, waits (bounded) for the other to do the
    same, and reports whether it saw the other running. Waiting for readiness
    instead of assuming a fixed sleep makes the assertion about concurrency,
    not about scheduler timing on a busy machine.
    """
    state_dir, own_index = chunk
    Path(state_dir, f"started-{own_index}").touch()
    other = Path(state_dir, f"started-{1 - own_index}")
    saw_other = True
    for _ in range(200):
        if other.exists():
            break
        time.sleep(0.05)
    else:
        saw_other = False
    return os.getpid(), saw_other


def _track_processes(monkeypatch):
    processes = []
    real_popen = pdf_pool.subprocess.Popen

    def _tracked_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(pdf_pool.subprocess, "Popen", _tracked_popen)
    return processes


def _assert_processes_reaped(processes):
    assert processes
    for process in processes:
        assert process.returncode is not None
        process.wait(timeout=0)
        with pytest.raises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)


def test_terminate_and_reap_tolerates_children_exiting_first():
    """A child exiting between poll() and kill() must not mask the original
    failure with ProcessLookupError."""
    process = mock.Mock()
    process.poll.return_value = None
    process.kill.side_effect = ProcessLookupError()

    pdf_pool._terminate_and_reap([process])

    process.wait.assert_called_once_with()


def _hung_child_script():
    """Bypass Django startup so transport tests can use short deadlines."""
    return (
        "import os, sys, time; from pathlib import Path; "
        "(Path(sys.argv[1]) / str(os.getpid())).touch(); time.sleep(60)"
    )


def _spawn_hung_children(monkeypatch, tmp_path):
    """Start children that record their startup, then hang until killed."""
    script = _hung_child_script()
    processes = []
    real_popen = subprocess.Popen

    def start_hung_worker(_command, **kwargs):
        process = real_popen([sys.executable, "-c", script, str(tmp_path)], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start_hung_worker)
    return processes


def _pid_state(pid):
    """Return /proc's state char for ``pid``, or None once it is fully gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # /proc/pid/stat: pid (comm) state ppid ... — comm may contain spaces.
    return stat.rsplit(")", 1)[1].split()[0]


def _pid_running(pid):
    """True while the process can still execute; zombies count as exited."""
    return _pid_state(pid) not in (None, "Z")


@pytest.mark.slow
def test_chunks_run_concurrently_in_separate_processes(monkeypatch, tmp_path):
    """Two bounded chunks overlap in time; worker communication must not
    accidentally await each child before sending the next one."""
    processes = _track_processes(monkeypatch)
    chunks = [(str(tmp_path), 0), (str(tmp_path), 1)]
    results = pdf_pool._run_chunks(_handshake_work, chunks, 2)

    assert len(results) == 2
    assert len({pid for pid, _saw_other in results}) == 2
    assert all(saw_other for _pid, saw_other in results), "chunks did not overlap"
    _assert_processes_reaped(processes)


@pytest.mark.skipif(
    not Path("/proc").is_dir(), reason="orphan detection scans Linux /proc",
)
@pytest.mark.integration
@pytest.mark.slow
def test_workers_exit_when_parent_is_sigkilled(tmp_path):
    """A SIGKILL'd parent cannot run its ``finally``; the workers' watchdog
    must bound their lifetime instead of leaving orphans behind."""
    environment = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings_test",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'parent.sqlite3'}",
        "MEDIA_ROOT": str(tmp_path / "media"),
        "SECRET_KEY": "isolated-orphan-pdf-test-key-20260905",
    }
    parent_script = (
        "import time; from invoices import pdf_pool; "
        "pdf_pool._run_chunks(time.sleep, [60, 60], 2)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    worker_pids = []
    try:
        deadline = time.monotonic() + 30
        # Both PDF children of this parent must appear before it is killed.
        while len(worker_pids) < 2 and time.monotonic() < deadline:
            worker_pids = _pdf_worker_pids_of(parent.pid)
            time.sleep(0.05)
        assert len(worker_pids) == 2, "parent never started both PDF workers"

        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=10)

        # The watchdog polls every 0.5s, so the orphans must be gone soon.
        # A zombie counts as gone: it no longer executes, it only waits to
        # be reaped by whatever inherited it.
        gone_deadline = time.monotonic() + 15
        while time.monotonic() < gone_deadline and any(
            _pid_running(pid) for pid in worker_pids
        ):
            time.sleep(0.1)
        assert not any(_pid_running(pid) for pid in worker_pids), (
            "orphaned PDF workers outlived a SIGKILL'd parent"
        )
    finally:
        # Cleanup must not depend on the watchdog being correct: whatever
        # failed above, the parent and every worker it spawned are killed
        # here directly instead of being left to time out on their own.
        # Children are killed before the parent is drained: they inherit its
        # output pipes, so communicate() could block while a broken watchdog
        # keeps them alive.
        for pid in {*worker_pids, *_pdf_worker_pids_of(parent.pid)}:
            if _pid_running(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if parent.poll() is None:
            try:
                parent.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.kill(parent.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                parent.communicate()
        else:
            parent.communicate()
        for pid in _pdf_worker_pids_of(parent.pid):
            if _pid_running(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _pdf_worker_pids_of(parent_pid):
    """PDF worker PIDs spawned by ``parent_pid``, matched via their argv.

    Workers are started as ``python -m invoices.pdf_worker <parent pid>``,
    so the match keeps working after the parent is SIGKILL'd and the
    workers are reparented.
    """
    marker = f"invoices.pdf_worker\x00{parent_pid}\x00".encode()
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if marker in cmdline:
            pids.append(int(entry.name))
    return pids


@pytest.mark.slow
def test_timeout_kills_and_reaps_every_worker(monkeypatch, tmp_path):
    processes = _spawn_hung_children(monkeypatch, tmp_path)

    with override_settings(PDF_POOL_TIMEOUT_S=2):
        with pytest.raises(TimeoutError):
            pdf_pool._run_chunks(time.sleep, [60, 60], 2)
    assert len(list(tmp_path.iterdir())) == 2
    _assert_processes_reaped(processes)


def test_non_positive_pool_timeout_is_rejected(monkeypatch):
    """A non-positive timeout would expire every batch before it starts;
    misconfiguration must fail loudly instead of spawning doomed workers."""
    monkeypatch.setattr(pdf_pool, "_run_processes", mock.Mock())
    with (
        override_settings(PDF_POOL_TIMEOUT_S=0),
        pytest.raises(ImproperlyConfigured),
    ):
        pdf_pool._run_chunks(str, [[1]], 1)


@pytest.mark.slow
def test_soft_time_limit_to_parent_cleans_up_active_workers(monkeypatch, tmp_path):
    """A soft time limit interrupts the serving process while its
    communication threads are active; cleanup must still kill and join."""
    processes = _spawn_hung_children(monkeypatch, tmp_path)

    def raise_soft_limit(_signum, _frame):
        raise SoftTimeLimitExceeded()

    previous = signal.signal(signal.SIGALRM, raise_soft_limit)
    try:
        # Arm the interrupt before the batch so it is delivered while the
        # parent is blocked in the communication threads. The children touch
        # their marker within ~0.3s of spawn, well before the 1.5s deadline.
        signal.setitimer(signal.ITIMER_REAL, 1.5)
        with pytest.raises(SoftTimeLimitExceeded):
            pdf_pool._run_chunks(time.sleep, [60, 60], 2)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    assert len(list(tmp_path.iterdir())) == 2, "both children never started"
    _assert_processes_reaped(processes)


@pytest.mark.parametrize(
    "worker, expected",
    [
        (_raise_runtime, RuntimeError),
        (_raise_soft_limit, SoftTimeLimitExceeded),
    ],
)
@pytest.mark.slow
def test_worker_failures_propagate_and_reap_children(worker, expected, monkeypatch):
    processes = _track_processes(monkeypatch)

    with pytest.raises(expected):
        pdf_pool._run_chunks(worker, [[1], [2]], 2)

    _assert_processes_reaped(processes)


@pytest.mark.slow
def test_abrupt_worker_exit_propagates_and_reaps_siblings(monkeypatch):
    """A worker exiting without a protocol answer (crash, OOM kill) is a
    different failure path from a cooperative error message."""
    processes = _track_processes(monkeypatch)

    with pytest.raises(RuntimeError, match="exited with status 3"):
        pdf_pool._run_chunks(_crash_or_hang, [[True], [False]], 2)

    _assert_processes_reaped(processes)


def test_worker_count_respects_process_cpu_affinity():
    with (
        mock.patch.object(pdf_pool.os, "process_cpu_count", lambda: 2, create=True),
        override_settings(PDF_POOL_MAX_WORKERS=8),
    ):
        assert pdf_pool._available_workers() == 2


def test_worker_count_falls_back_to_scheduler_affinity():
    """Pre-3.13 runtimes lack os.process_cpu_count: scheduler affinity
    (not plain cpu_count) must bound the workers where process_cpu_count
    is absent. Affinity still ignores CPU quotas — quota-limited
    deployments size PDF_POOL_MAX_WORKERS explicitly."""
    with (
        mock.patch.object(pdf_pool.os, "process_cpu_count", None),
        mock.patch.object(
            pdf_pool.os, "sched_getaffinity", return_value={0, 1, 2},
        ),
        override_settings(PDF_POOL_MAX_WORKERS=8),
    ):
        assert pdf_pool._available_workers() == 3


def test_worker_setting_floor_is_one():
    with (
        mock.patch.object(pdf_pool.os, "process_cpu_count", lambda: 16, create=True),
        override_settings(PDF_POOL_MAX_WORKERS=0),
    ):
        # A non-positive setting must never yield zero (or negative) workers.
        assert pdf_pool._available_workers() == 1


@pytest.mark.parametrize(
    "count, workers, expected_sizes",
    [
        (8, 4, [2, 2, 2, 2]),
        (5, 2, [3, 2]),
        (3, 8, [1, 1, 1]),
        (6, 4, [2, 2, 1, 1]),
        (5, 4, [2, 1, 1, 1]),
        (0, 4, []),
    ],
)
def test_split_into_chunks_is_balanced_and_ordered(count, workers, expected_sizes):
    chunks = pdf_pool._split_into_chunks(list(range(count)), workers)

    assert [len(chunk) for chunk in chunks] == expected_sizes
    assert [item for chunk in chunks for item in chunk] == list(range(count))


def test_statement_results_are_restored_to_input_order(monkeypatch):
    participants = [SimpleNamespace(id=f"p{i}") for i in range(4)]
    zev = SimpleNamespace(id="zev-a")

    def _out_of_order(_worker, chunks, workers):
        assert workers == 2
        assert chunks == [
            (["p0", "p1"], "zev-a", 2026, None),
            (["p2", "p3"], "zev-a", 2026, None),
        ]
        return [
            [("p2", b"PDF-2", None), ("p3", b"PDF-3", None)],
            [("p0", b"PDF-0", None), ("p1", b"PDF-1", None)],
        ]

    monkeypatch.setattr(pdf_pool, "_available_workers", lambda: 2)
    monkeypatch.setattr(pdf_pool, "_run_chunks", _out_of_order)

    result = pdf_pool.render_statements_parallel(participants, zev, 2026)

    assert result == [
        ("p0", b"PDF-0", None),
        ("p1", b"PDF-1", None),
        ("p2", b"PDF-2", None),
        ("p3", b"PDF-3", None),
    ]


@pytest.mark.django_db
def test_statement_chunk_reuses_shared_setup_and_isolates_failure(monkeypatch):
    from testing.factories import ParticipantFactory

    first = ParticipantFactory(first_name="S0", last_name="Stmt0")
    zev = first.zev
    participants = [first] + [
        ParticipantFactory(zev=zev, first_name=f"S{i}", last_name=f"Stmt{i}")
        for i in range(1, 4)
    ]
    share_windows = [
        (
            participant.id,
            participant.valid_from,
            participant.valid_to,
            participant.allocation_weight,
        )
        for participant in participants
    ]

    import allocation.read_model as read_model
    from allocation.read_model import (
        community_totals_by_timestamp,
        eligible_participant_shares,
    )
    import invoices.annual_statement as annual_statement

    def _flaky_generate(participant, zev_arg, year, **kwargs):
        if participant.id == participants[1].id:
            raise ValueError("statement failed")
        return f"PDF-{participant.id}".encode()

    with (
        mock.patch.object(
            read_model, "eligible_participant_shares",
            wraps=eligible_participant_shares,
        ) as build_shares,
        mock.patch.object(
            read_model, "community_totals_by_timestamp",
            wraps=community_totals_by_timestamp,
        ) as build_totals,
        mock.patch.object(
            annual_statement, "generate_annual_statement_pdf",
            side_effect=_flaky_generate,
        ) as generate_statement,
    ):
        result = pdf_pool._render_statement_chunk(
            ([participant.id for participant in participants], zev.id, 2026, share_windows),
        )

    assert len(result) == 4
    by_id = {
        participant_id: (pdf_bytes, error)
        for participant_id, pdf_bytes, error in result
    }
    assert by_id[participants[1].id][0] is None
    assert "statement failed" in by_id[participants[1].id][1]
    assert all(
        by_id[participant.id][0] == f"PDF-{participant.id}".encode()
        for participant in (participants[0], participants[2], participants[3])
    )
    # Yearly shared data is built once per chunk and reused for every document.
    build_shares.assert_called_once()
    build_totals.assert_called_once()
    assert generate_statement.call_count == 4
    shares_by_date = generate_statement.call_args_list[0].kwargs["shares_by_date"]
    assert all(
        call.kwargs["shares_by_date"] is shares_by_date
        for call in generate_statement.call_args_list
    )
    zev_totals_by_ts = generate_statement.call_args_list[0].kwargs["zev_totals_by_ts"]
    assert all(
        call.kwargs["zev_totals_by_ts"] is zev_totals_by_ts
        for call in generate_statement.call_args_list
    )


@pytest.mark.django_db
def test_statement_chunk_propagates_shared_setup_failure():
    """A failure in the once-per-chunk shared data must abort the chunk (and
    thus the batch), not be reduced to per-document errors."""
    from testing.factories import ParticipantFactory

    first = ParticipantFactory()
    zev = first.zev
    participants = [first, ParticipantFactory(zev=zev)]

    import allocation.read_model as read_model

    share_windows = [
        (
            participant.id,
            participant.valid_from,
            participant.valid_to,
            participant.allocation_weight,
        )
        for participant in participants
    ]

    with (
        mock.patch.object(
            read_model, "community_totals_by_timestamp",
            side_effect=RuntimeError("yearly totals unavailable"),
        ),
        mock.patch(
            "invoices.annual_statement.generate_annual_statement_pdf",
        ) as generate_statement,
        pytest.raises(RuntimeError, match="yearly totals unavailable"),
    ):
        pdf_pool._render_statement_chunk(
            ([participant.id for participant in participants], zev.id, 2026, share_windows),
        )
    generate_statement.assert_not_called()


@pytest.mark.django_db
def test_statement_chunk_logs_document_failure_with_traceback(monkeypatch, caplog):
    """The pickled result row carries only a string; the traceback must be
    logged in the child where the stack still exists."""
    from testing.factories import ParticipantFactory

    first = ParticipantFactory()
    zev = first.zev
    participants = [first, ParticipantFactory(zev=zev)]

    import invoices.annual_statement as annual_statement

    def _failing_generate(_participant, _zev_arg, _year, **_kwargs):
        raise ValueError("traceback must be logged")

    monkeypatch.setattr(
        annual_statement, "generate_annual_statement_pdf", _failing_generate,
    )
    share_windows = [
        (
            participant.id,
            participant.valid_from,
            participant.valid_to,
            participant.allocation_weight,
        )
        for participant in participants
    ]

    with caplog.at_level("ERROR", logger="invoices.pdf_pool"):
        result = pdf_pool._render_statement_chunk(
            ([participant.id for participant in participants], zev.id, 2026, share_windows),
        )

    assert all(pdf_bytes is None for _participant_id, pdf_bytes, _error in result)
    assert len(caplog.records) == len(participants)
    assert all(record.exc_info for record in caplog.records)
    assert all(
        "Annual statement failed for participant" in record.message
        for record in caplog.records
    )


@pytest.mark.django_db
def test_statement_chunk_closes_connection_when_done(monkeypatch):
    from testing.factories import ParticipantFactory

    first = ParticipantFactory()
    zev = first.zev
    participants = [first, ParticipantFactory(zev=zev)]

    import django.db as django_db

    import invoices.annual_statement as annual_statement

    monkeypatch.setattr(
        annual_statement,
        "generate_annual_statement_pdf",
        lambda participant, zev_arg, year, **kwargs: b"PDF",
    )
    share_windows = [
        (
            participant.id,
            participant.valid_from,
            participant.valid_to,
            participant.allocation_weight,
        )
        for participant in participants
    ]

    with mock.patch.object(
        django_db.connections,
        "close_all",
        wraps=django_db.connections.close_all,
    ) as close_all:
        result = pdf_pool._render_statement_chunk(
            ([participant.id for participant in participants], zev.id, 2026, share_windows),
        )

    close_all.assert_called_once()
    assert all(pdf_bytes == b"PDF" for _participant_id, pdf_bytes, _error in result)


@pytest.mark.slow
def test_partial_startup_failure_reaps_started_child(monkeypatch):
    real_popen = subprocess.Popen
    processes = []

    def fail_second_spawn(*args, **kwargs):
        if processes:
            raise OSError("second spawn failed")
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", fail_second_spawn)
    with pytest.raises(OSError, match="second spawn"):
        pdf_pool._run_chunks(time.sleep, [60, 60], 2)
    _assert_processes_reaped(processes)


def _noisy_worker(value):
    import os

    print("worker diagnostic")
    os.write(1, b"native diagnostic\n")
    return value


@pytest.mark.slow
def test_application_stdout_does_not_corrupt_worker_results():
    assert pdf_pool._run_chunks(_noisy_worker, ["first", "second"], 2) == ["first", "second"]


@pytest.mark.slow
def test_worker_logs_the_original_traceback_before_returning_error():
    """The pickled exception loses its traceback in transit; the child must
    log it where the stack still exists.

    Runs the real module entry in a subprocess so the test cannot disturb
    this pytest/xdist process's own stdin and stdout.
    """
    from invoices.tasks import _render_pdfs

    # A picklable module-level callable that fails, like a real render chunk.
    request = pickle.dumps((_render_pdfs, ["not-an-invoice"]))
    child = subprocess.run(
        [sys.executable, "-m", "invoices.pdf_worker", str(os.getpid())],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings_test"},
        input=request, capture_output=True, timeout=60,
    )
    assert child.returncode == 0, child.stderr

    status, exc = pickle.loads(child.stdout)
    assert status == "error"
    # The failure itself is incidental; the protocol must carry it back.
    assert isinstance(exc, BaseException)
    stderr = child.stderr.decode()
    # The traceback was logged inside the child, where the stack existed,
    # under the worker's dedicated logger message.
    assert "Traceback (most recent call last)" in stderr, (
        "worker did not log the original traceback"
    )
    assert "PDF worker failed" in stderr


def test_concurrent_batches_share_the_worker_budget(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    first_entered = threading.Event()
    second_started = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()

    def run_processes(worker, chunks, deadline):
        if chunks == [1]:
            first_entered.set()
            assert release.wait(5)
        else:
            second_entered.set()
        return chunks

    def second_batch():
        second_started.set()
        return pdf_pool._run_chunks(str, [2], 1)

    monkeypatch.setattr(pdf_pool, "_run_processes", run_processes)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(pdf_pool._run_chunks, str, [1], 1)
        try:
            assert first_entered.wait(5)
            second = executor.submit(second_batch)
            assert second_started.wait(5)
            assert not second_entered.wait(0.05)
        finally:
            release.set()
        assert first.result(timeout=5) == [1]
        assert second.result(timeout=5) == [2]


def test_gate_wait_counts_against_the_batch_deadline():
    """Time queued behind another batch counts against the budget: a gate
    held past it must fail fast with TimeoutError instead of running late."""
    import threading
    import time

    from django.test import override_settings

    held = threading.Event()
    release = threading.Event()

    def hold_gate():
        with pdf_pool._batch_gate:
            held.set()
            assert release.wait(10)

    holder = threading.Thread(target=hold_gate)
    holder.start()
    try:
        assert held.wait(5)
        start = time.monotonic()
        with override_settings(PDF_POOL_TIMEOUT_S=0.05):
            with pytest.raises(TimeoutError, match="deadline"):
                pdf_pool._run_chunks(str, ["late"], 1)
        assert time.monotonic() - start < 5
    finally:
        release.set()
        holder.join(timeout=10)
