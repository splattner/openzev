"""Fetch one dynamic tariff source and report what the series now covers.

Mostly an operator tool: it is how you check a newly configured endpoint
without waiting for the beat schedule.

    python manage.py fetch_dynamic_prices --list
    python manage.py fetch_dynamic_prices <source-id> --backfill
    python manage.py fetch_dynamic_prices --probe https://example.test/tariffs \
        --api-version v1_0_5 --tariff-type grid

``--probe`` fetches and parses without writing anything, which is the safe way
to try a URL that arrived in a published tariff document.
"""

from django.core.management.base import BaseCommand, CommandError

from tariffs.dynamic.adapters import DynamicApiVersion
from tariffs.dynamic.discovery import probe_source_configuration
from tariffs.dynamic.fetch import coverage_gaps, refresh_source
from tariffs.dynamic.models import DynamicTariffSource, DynamicTariffType
from tariffs.importers.remote import TariffFetchError


class Command(BaseCommand):
    help = "Fetch dynamic tariff prices for one source, or probe an endpoint without storing."

    def add_arguments(self, parser):
        parser.add_argument("source_id", nargs="?", help="Source to refresh.")
        parser.add_argument("--list", action="store_true", help="List configured sources and exit.")
        parser.add_argument("--backfill", action="store_true", help="Also pull whatever history the operator still has.")
        parser.add_argument("--probe", metavar="URL", help="Fetch and parse a URL without storing anything.")
        parser.add_argument("--api-version", default=DynamicApiVersion.V1_0_5, choices=[v.value for v in DynamicApiVersion])
        parser.add_argument("--tariff-type", default=DynamicTariffType.GRID, choices=[t.value for t in DynamicTariffType])
        parser.add_argument("--tariff-name", default="")

    def handle(self, *args, **options):
        if options["list"]:
            return self._list()
        if options["probe"]:
            return self._probe(options)
        if not options["source_id"]:
            raise CommandError("Give a source id, --list, or --probe URL.")
        return self._refresh(options)

    def _list(self):
        sources = DynamicTariffSource.objects.all()
        if not sources:
            self.stdout.write("No dynamic tariff sources configured.")
            return
        for source in sources:
            covers = (
                f"{source.covers_from:%Y-%m-%d %H:%M} .. {source.covers_to:%Y-%m-%d %H:%M}"
                if source.covers_from and source.covers_to else "nothing stored"
            )
            self.stdout.write(
                f"{source.pk}  {source.label}\n"
                f"    {source.api_version} {source.tariff_type}"
                f"{'/' + source.tariff_name if source.tariff_name else ''}  "
                f"[{source.last_fetch_status}]  covers {covers}"
            )
            if source.last_fetch_error:
                self.stdout.write(self.style.WARNING(f"    last error: {source.last_fetch_error}"))

    def _probe(self, options):
        """Read an endpoint without touching the database."""
        try:
            capabilities = probe_source_configuration(
                options["probe"],
                api_version=options["api_version"],
                tariff_type=options["tariff_type"],
                tariff_name=options["tariff_name"],
            )
        except (TariffFetchError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        points, warnings = capabilities.points, capabilities.warnings

        if not points:
            self.stdout.write(self.style.WARNING(
                "The endpoint answered, but priced nothing for that window. That is a normal "
                "answer for a day the operator has no data for — it is not proof the URL is wrong."
            ))
            return
        prices = [point.price_chf_per_kwh for point in points]
        self.stdout.write(self.style.SUCCESS(
            f"{len(points)} interval(s) {points[0].valid_from.isoformat()} .. {points[-1].valid_to.isoformat()}"
        ))
        self.stdout.write(
            f"    {capabilities.api_version}; request mode {capabilities.request_mode}; "
            f"range queries {'supported' if capabilities.supports_range else 'not supported'}"
        )
        self.stdout.write(f"    min {min(prices)}  max {max(prices)}  negative {sum(1 for p in prices if p < 0)}")
        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"    {warning}"))

    def _refresh(self, options):
        source = DynamicTariffSource.objects.filter(pk=options["source_id"]).first()
        if source is None:
            raise CommandError(f"No dynamic tariff source with id {options['source_id']}.")
        try:
            result = refresh_source(source, backfill=options["backfill"])
        except TariffFetchError as exc:
            raise CommandError(str(exc)) from exc

        source.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f"{result.points_written} point(s) from {result.requests} request(s); "
            f"series now covers {source.covers_from} .. {source.covers_to}"
        ))
        if source.covers_from and source.covers_to:
            gaps = coverage_gaps(source, source.covers_from, source.covers_to)
            if gaps:
                self.stdout.write(self.style.WARNING(f"{len(gaps)} gap(s) inside the covered range:"))
                for start, end in gaps[:5]:
                    self.stdout.write(f"    {start.isoformat()} .. {end.isoformat()}")
        for warning in result.warnings or []:
            self.stdout.write(self.style.WARNING(f"    {warning}"))
