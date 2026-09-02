"""
Django management command: python manage.py fetch_grid_operators

Refreshes ``zev/data/grid_operators.json`` from ElCom's electricity-tariff cube
on the federal LINDAS platform. Run it once per tariff year; the result is
committed, so nothing queries LINDAS at request time (see zev.grid_operators
for why).

The operator set shrinks slowly as Swiss utilities merge — 618 in 2019, 553 in
2026 — so a sudden large drop means the query or the cube changed, not that a
hundred utilities dissolved. ``--min-operators`` fails the command rather than
writing a truncated fixture over a good one.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from zev.grid_operators import DATA_FILE

SPARQL_ENDPOINT = "https://lindas.admin.ch/query"
CUBE = "https://energy.ld.admin.ch/elcom/electricityprice"
LICENCE = "https://ld.admin.ch/vocabulary/TermsOfUse/Open-Use"
REQUEST_TIMEOUT_SECONDS = 120

# Only operators with tariff data for the requested year: the cube also holds
# utilities that have since merged or dissolved (759 across all years), which
# should not be offered when creating a ZEV today.
QUERY = """
PREFIX schema: <http://schema.org/>
PREFIX e: <https://energy.ld.admin.ch/elcom/electricityprice/dimension/>
SELECT DISTINCT ?id ?name ?uid ?website WHERE {
  ?obs e:operator ?operator ;
       e:period "%(period)s"^^<http://www.w3.org/2001/XMLSchema#gYear> .
  ?operator schema:name ?name .
  OPTIONAL { ?operator schema:url ?website }
  OPTIONAL { ?operator schema:identifier ?uid . FILTER(STRSTARTS(STR(?uid), "CHE-")) }
  BIND(REPLACE(STR(?operator), "^.*/", "") AS ?id)
}
ORDER BY ?name
"""


class Command(BaseCommand):
    help = "Refresh the ElCom grid-operator list used by the ZEV grid-operator picker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            default=str(date.today().year),
            help="Tariff year to fetch (default: current year).",
        )
        parser.add_argument(
            "--min-operators",
            type=int,
            default=400,
            help="Refuse to write the fixture if fewer operators come back (default: 400).",
        )

    def handle(self, *args, **options):
        period = options["period"]
        rows = self._query(QUERY % {"period": period})

        operators = sorted(
            (
                {
                    "id": int(row["id"]["value"]),
                    "name": row["name"]["value"],
                    "uid": row.get("uid", {}).get("value") or "",
                    "website": row.get("website", {}).get("value") or "",
                }
                for row in rows
            ),
            key=lambda operator: operator["name"].casefold(),
        )

        if len(operators) < options["min_operators"]:
            raise CommandError(
                f"Only {len(operators)} operators returned for {period} "
                f"(expected at least {options['min_operators']}). Refusing to overwrite "
                f"{DATA_FILE.name} — check the query and the cube before rerunning."
            )

        ids = [operator["id"] for operator in operators]
        if len(set(ids)) != len(ids):
            raise CommandError("ElCom returned duplicate operator ids; refusing to write.")

        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with DATA_FILE.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "source": SPARQL_ENDPOINT,
                    "cube": CUBE,
                    "licence": LICENCE,
                    "period": period,
                    "fetched_on": date.today().isoformat(),
                    "operators": operators,
                },
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            handle.write("\n")

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(operators)} grid operators for {period} to {DATA_FILE}."
            )
        )

    def _query(self, query: str) -> list[dict]:
        request = urllib.request.Request(
            SPARQL_ENDPOINT,
            data=urllib.parse.urlencode({"query": query}).encode("utf-8"),
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CommandError(f"Querying {SPARQL_ENDPOINT} failed: {exc}") from exc
        return payload["results"]["bindings"]
