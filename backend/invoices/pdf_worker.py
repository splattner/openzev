"""Subprocess entry point used by :mod:`invoices.pdf_pool`.

See :mod:`invoices.pdf_pool` for the wire protocol. This module performs
Django setup before loading the request, then sends exactly one result pickle
on stdout. Logging, Python-level prints, and native file-descriptor writes
stay on stderr, so they cannot corrupt the pickle pipe.
"""

from __future__ import annotations

import logging
import os
import pickle
import sys
import threading


def _write_message(stream, value) -> None:
    pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
    stream.flush()


def _watch_parent(expected_parent_pid: int) -> None:
    """Exit if the parent is killed, so workers are not orphaned.

    A SIGKILL'd parent never runs its ``finally``; polling ``os.getppid()``
    against the expected PID also covers a parent killed before this thread
    starts. Best-effort while native rendering holds the GIL.
    """
    sleep = threading.Event()
    while True:
        if os.getppid() != expected_parent_pid:
            os._exit(1)
        sleep.wait(0.5)


def main() -> int:
    """Set up Django, execute one trusted chunk, and return a process status."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Duplicate fd 1 before redirecting it to stderr: keeping the old Python
    # object would still write to fd 1, so only a real file-descriptor
    # duplicate keeps the protocol pipe safe from native os.write output too.
    protocol_stream = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    # Application prints and Django diagnostics must stay off the pickle
    # stream; as Python-level objects they go to stderr, which the parent shares.
    sys.stdout = sys.stderr
    # Keep the watchdog independent from worker code, which may set up handlers.
    # See _watch_parent for why the parent PID arrives as an argument.
    threading.Thread(
        target=_watch_parent, args=(int(sys.argv[1]),), daemon=True,
    ).start()
    try:
        import django

        django.setup()
    except BaseException as exc:
        _write_message(protocol_stream, ("startup_error", repr(exc)))
        return 0

    try:
        worker, chunk = pickle.load(sys.stdin.buffer)
        result = worker(chunk)
        message = ("ok", result)
    except BaseException as exc:
        # The traceback exists only here before the exception is reduced to a
        # pickled object for the parent, so log it now.
        logging.getLogger("invoices.pdf_worker").exception("PDF worker failed")
        message = ("error", exc)

    _write_message(protocol_stream, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
