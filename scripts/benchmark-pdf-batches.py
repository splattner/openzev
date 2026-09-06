"""Compare batch PDF timings across checkouts on copies of one fixture.

Usage (from repository root):
  .venv/bin/python scripts/benchmark-pdf-batches.py --directory /tmp/pdf-base --setup-only --participants 20
  cp -r /tmp/pdf-base /tmp/pdf-A
  .venv/bin/python scripts/benchmark-pdf-batches.py --directory /tmp/pdf-A --backend /tmp/openzev-A/backend
  # copy the base fixture once per checkout, then measure the copies in
  # alternating run order

Each invocation measures one checkout using a separate fixture copy:
run --setup-only once, copy that directory per checkout, then
measure. Copies share participant PKs, so ZIP names stay deterministic.
Only the annual serial-vs-parallel comparison on such copies is
established — equal --participants on independently generated fixtures is
not equivalent. Timing excludes fixture generation, migrations, hashing,
and archive checks.

Workloads: invoice_pdfs renders the January period via _render_pdfs;
annual_zip renders the full-year ZIP via the API endpoint. Statements use a
full year of 15-minute readings, matching production interval data.

Output is one JSON object per workload with revision, runtime versions,
document count, first/repeat/median seconds, worker engagement, and hashes.
"""

import argparse
import hashlib
import importlib.metadata
import io
import json
import logging
import os
import platform
import statistics
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

INTERVAL = timedelta(minutes=15)


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--directory", type=Path, required=True,
                        help="writable fixture copy for this checkout")
    parser.add_argument("--backend", type=Path,
                        default=Path(__file__).resolve().parents[1] / "backend")
    parser.add_argument("--participants", type=positive_int, default=20)
    parser.add_argument("--workers", type=positive_int, default=4,
                        help="parallel worker cap (only used by pool checkouts)")
    parser.add_argument("--runs", type=positive_int, default=3,
                        help="repeated batches after the first (total runs+1)")
    parser.add_argument("--workload", choices=("invoice_pdfs", "annual_zip", "both"),
                        default="both")
    parser.add_argument("--setup-only", action="store_true")
    return parser.parse_args(argv)


def build_fixture(participants_count, logger_):
    """Create SQLite fixture with bounded inserts (one meter at a time)."""
    from django.core.management import call_command
    from metering.models import MeterReading, ReadingDirection
    from tariffs.models import BillingMode, SplitKey, TariffCategory
    from testing.factories import (
        MeteringPointAssignmentFactory,
        MeteringPointFactory,
        ParticipantFactory,
        TariffFactory,
        flat_tariff,
    )
    from zev.models import AllocationMode, MeteringPointType

    call_command("migrate", verbosity=0, interactive=False)
    first = ParticipantFactory()
    zev = first.zev
    participants = [first] + [
        ParticipantFactory(zev=zev, allocation_weight=Decimal(index + 1))
        for index in range(1, participants_count)
    ]

    year_start = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    year_end = datetime(2027, 1, 1, tzinfo=dt_timezone.utc)
    per_meter = int((year_end - year_start) / INTERVAL)

    total = 0
    for participant in participants:
        meter = MeteringPointFactory(zev=zev,
                                     meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignmentFactory(
            metering_point=meter, participant=participant,
            valid_from=date(2026, 1, 1), allocation_mode=AllocationMode.PERSONAL)
        MeterReading.objects.bulk_create(
            _meter_readings(meter, year_start, per_meter, "10.5",
                            ReadingDirection.IN),
            batch_size=1000)
        total += per_meter

    for meter_type, direction in (
        (MeteringPointType.CONSUMPTION, ReadingDirection.IN),
        (MeteringPointType.PRODUCTION, ReadingDirection.OUT),
    ):
        meter = MeteringPointFactory(zev=zev, meter_type=meter_type)
        MeteringPointAssignmentFactory(
            metering_point=meter, participant=participants[0],
            valid_from=date(2026, 1, 1), allocation_mode=AllocationMode.COMMUNITY)
        MeterReading.objects.bulk_create(
            _meter_readings(meter, year_start, per_meter, "4.25", direction),
            batch_size=1000)
        total += per_meter
    logger_.info("fixture: %d readings (%d per meter)", total, per_meter)

    flat_tariff(zev)
    for split_key in (SplitKey.EQUAL, SplitKey.WEIGHT):
        TariffFactory(zev=zev, category=TariffCategory.METERING,
                      billing_mode=BillingMode.SHARED_MONTHLY_FEE,
                      energy_type=None, fixed_price_chf=Decimal("10.00"),
                      valid_from=date(2026, 1, 1), split_key=split_key)
    return zev


def _meter_readings(meter, year_start, count, energy, direction):
    from metering.models import MeterReading

    return [MeterReading(metering_point=meter,
                         timestamp=year_start + index * INTERVAL,
                         energy_kwh=Decimal(energy), direction=direction)
            for index in range(count)]


def pdf_hash(data):
    assert data.startswith(b"%PDF-"), "missing or invalid PDF"
    return hashlib.sha256(data).hexdigest()


def checkout_info(path):
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain", "--", "."],
            text=True).strip())
        return {"revision": revision, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "dirty": None}


def runtime_versions():
    import django

    return {"python": platform.python_version(),
            "django": django.get_version(),
            "weasyprint": importlib.metadata.version("weasyprint"),
            "platform": platform.platform()}


class WorkerProbe:
    """Record whether pool workers were spawned (C) or not (A/B)."""

    def __init__(self):
        self.pids = set()
        self._original_popen = subprocess.Popen

    def __enter__(self):
        probe = self

        def observed_popen(*args, **kwargs):
            process = probe._original_popen(*args, **kwargs)
            command = args[0] if args else kwargs.get("args")
            if (isinstance(command, (list, tuple))
                    and "invoices.pdf_worker" in command):
                probe.pids.add(process.pid)
            return process

        subprocess.Popen = observed_popen
        return self

    def __exit__(self, *exc):
        subprocess.Popen = self._original_popen
        return False

    def sample(self):
        return {"worker_engaged": bool(self.pids),
                "workers_spawned": len(self.pids)}


def validate_invoice_hashes(_result, count):
    from invoices.models import Invoice

    hashes = {}
    for row in Invoice.objects.order_by("invoice_number"):
        row.pdf_file.open("rb")
        try:
            hashes[row.invoice_number] = pdf_hash(row.pdf_file.read())
        finally:
            row.pdf_file.close()
    assert len(hashes) == count
    return hashes


def validate_statement_hashes(result, count):
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert "omitted.txt" not in archive.namelist(), "a statement was omitted"
        assert len(archive.namelist()) == count, "a statement was omitted"
        return {name: pdf_hash(archive.read(name)) for name in archive.namelist()}


def _dispatch_workload(workload):
    from invoices.models import Invoice
    from invoices.tasks import _render_pdfs
    from rest_framework.test import APIClient
    from zev.models import Zev

    zev = Zev.objects.get()
    if workload == "invoice_pdfs":
        # Mirror the production entry: a plain period queryset. Item loading
        # is whatever the checkout's own _render_pdfs does — prefetching here
        # would hand older checkouts an optimization they do not have.
        rows = list(Invoice.objects.select_related("participant", "zev")
                    .order_by("invoice_number"))
        assert len(rows) == zev.participants.count()
        assert _render_pdfs(rows) == 0
        return None
    client = APIClient()
    client.force_authenticate(user=zev.owner)
    response = client.get("/api/v1/invoices/invoices/annual-statements-zip/",
                          {"year": 2026, "zev_id": str(zev.pk)})
    assert response.status_code == 200, response.content
    return response.content


def run_single_batch(workload):
    from django.db import connections

    connections.close_all()
    with WorkerProbe() as probe:
        start = time.perf_counter()
        result = _dispatch_workload(workload)
        elapsed = round(time.perf_counter() - start, 4)
    return result, elapsed, probe.sample()


def production_min_batch():
    try:
        from invoices.pdf_pool import _MIN_BATCH_FOR_POOL

        return int(_MIN_BATCH_FOR_POOL)
    except (ImportError, TypeError, ValueError):
        return 4


def effective_workers(workers, documents):
    cpus = os.process_cpu_count() or 1
    if documents < production_min_batch():
        return 1
    return max(1, min(workers, cpus, documents))


def assert_workers_engaged(workload, worker_samples, documents, workers):
    if workload == "invoice_pdfs":
        # Invoices always render serially; any spawned worker is a regression.
        assert all(not s["worker_engaged"] for s in worker_samples), \
            "invoice batch spawned PDF workers but must render serially"
        return
    if effective_workers(workers, documents) < 2:
        return
    try:
        from invoices import pdf_pool  # noqa: F401
    except ImportError:
        return  # serial checkout (A/B): nothing to engage
    assert all(s["worker_engaged"] and s["workers_spawned"] >= 2
               for s in worker_samples), \
        "benchmark did not spawn workers for every sample"


def _setup_runtime(args):
    sys.path.insert(0, str(args.backend))
    # The benchmark owns its process environment: assign unconditionally so
    # an inherited DATABASE_URL/MEDIA_ROOT cannot redirect migrations and
    # fixture data, and the requested worker count always applies.
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_test"
    os.environ["DATABASE_URL"] = f"sqlite:///{args.directory / 'fixture.sqlite3'}"
    os.environ["MEDIA_ROOT"] = str(args.directory / "media")
    os.environ["SECRET_KEY"] = "isolated-pdf-benchmark-only"
    os.environ["ALLOWED_HOSTS"] = "testserver,localhost"
    os.environ["PDF_POOL_MAX_WORKERS"] = str(args.workers)
    import django

    django.setup()


def main():
    args = parse_args()
    args.directory = args.directory.resolve()
    args.backend = args.backend.resolve()
    _setup_runtime(args)
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("benchmark")
    checkout = checkout_info(args.backend.parent)
    versions = runtime_versions()

    args.directory.mkdir(parents=True, exist_ok=True)
    if args.setup_only:
        assert not (args.directory / "fixture.sqlite3").exists(), \
            "use a fresh directory for setup"
        from invoices.engine import generate_invoices_for_zev

        zev = build_fixture(args.participants, logger)
        result = generate_invoices_for_zev(zev, date(2026, 1, 1), date(2026, 1, 31))
        assert not result.failures and len(result.invoices) == args.participants
        print(json.dumps({"fixture": str(args.directory),
                          "participants": args.participants,
                          "interval_minutes": int(INTERVAL.total_seconds() // 60),
                          **checkout, "runtime": versions}))
        return

    assert (args.directory / "fixture.sqlite3").exists(), "run --setup-only first"
    from zev.models import Zev

    count = Zev.objects.get().participants.count()
    workloads = (("invoice_pdfs", validate_invoice_hashes),
                 ("annual_zip", validate_statement_hashes))
    if args.workload != "both":
        workloads = tuple(w for w in workloads if w[0] == args.workload)

    # Alternate workload order across runs is handled by the caller running
    # A/B/C in rotation; within one invocation keep fixture-level drift low
    # by validating bytes outside the timed section.
    for workload, validate in workloads:
        samples, worker_samples, expected = [], [], None
        for _ in range(args.runs + 1):
            result, elapsed, sample = run_single_batch(workload)
            samples.append(elapsed)
            worker_samples.append(sample)
            hashes = validate(result, count)
            if expected is None:
                expected = hashes
            assert hashes == expected, "PDF bytes changed between samples"
        assert_workers_engaged(workload, worker_samples, count, args.workers)
        print(json.dumps({"workload": workload, "documents": count,
                          "workers": args.workers, "first_s": samples[0],
                          "repeat_s": samples[1:],
                          "median_s": statistics.median(samples[1:]),
                          "worker_samples": worker_samples,
                          **checkout, "runtime": versions,
                          "sha256": expected}), flush=True)


if __name__ == "__main__":
    main()
