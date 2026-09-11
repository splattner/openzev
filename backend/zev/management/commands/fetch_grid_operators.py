"""
Django management command: python manage.py fetch_grid_operators

Refreshes ``zev/data/grid_operators.json`` from ElCom's electricity-tariff cube
on the federal LINDAS platform. Run it once per tariff year; the result is
committed, so nothing queries LINDAS at request time (see zev.grid_operators
for why).

The operator set shrinks slowly as Swiss utilities merge — 618 in 2019, 553 in
2026 — so a sudden large drop means the query or the cube changed, not that a
hundred utilities dissolved. ``--min-operators`` fails the command rather than
writing a truncated fixture over a good one. ``--min-tariff-urls`` and
``--min-postal-codes`` guard the two additions below the same way.

Two things beyond the operator list are captured here, both used only as
*suggestions* — see ``zev.grid_operators`` for why neither is trusted enough
to write into a ``Zev`` without the owner confirming it:

- ``tariff_url``: ElCom's ``urltr`` dimension, "URL for machine-readable
  tariffs" — the Art. 7b address the VSE importer consumes. It is free text a
  human typed into a form, not a validated URL: about a tenth of the raw
  values have no scheme (``www.example.ch``), and it drifts — an operator's
  own re-upload can move the file to a new address before ElCom's copy is
  refreshed. ``_normalise_tariff_url`` fixes the first problem; nothing here
  can fix the second, which is why the frontend must fetch the URL before
  offering to save it, never write it straight from this fixture.
- ``postal_codes``: a postal code to operator id(s) map, so a ZEV can be
  offered a suggested operator from its own postal code instead of a flat
  553-entry list.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from zev.grid_operators import DATA_FILE

SPARQL_ENDPOINT = "https://lindas.admin.ch/query"
CUBE = "https://energy.ld.admin.ch/elcom/electricityprice"
LICENCE = "https://ld.admin.ch/vocabulary/TermsOfUse/Open-Use"
REQUEST_TIMEOUT_SECONDS = 120

# One row per (operator, municipality, category, product) observation that
# carries a tariff-year record, not DISTINCT: the same operator can publish
# more than one ``urltr`` value (mirrored on its own site and on a
# third-party aggregator, most often), and picking the most frequent one
# needs the real occurrence counts, not a deduplicated set. Only operators
# with data for the requested year: the cube also holds ids for utilities
# that have since merged or dissolved (759 across all years), which should
# not be offered when creating a ZEV today.
QUERY_OPERATORS = """
PREFIX schema: <http://schema.org/>
PREFIX e: <https://energy.ld.admin.ch/elcom/electricityprice/dimension/>
SELECT ?id ?name ?uid ?website ?urltr WHERE {
  ?obs e:operator ?operator ;
       e:period "%(period)s"^^<http://www.w3.org/2001/XMLSchema#gYear> .
  ?operator schema:name ?name .
  OPTIONAL { ?operator schema:url ?website }
  OPTIONAL { ?operator schema:identifier ?uid . FILTER(STRSTARTS(STR(?uid), "CHE-")) }
  OPTIONAL { ?obs e:urltr ?urltr }
  BIND(REPLACE(STR(?operator), "^.*/", "") AS ?id)
}
ORDER BY ?name
"""

# Postal codes live in a separate LINDAS graph (the federal register of
# municipalities) from the tariff cube; joined here on the shared
# municipality URI. DISTINCT because this only needs the (plz, operator)
# pairs, not how many category/product rows produced each one.
QUERY_POSTAL_CODES = """
PREFIX schema: <http://schema.org/>
PREFIX e: <https://energy.ld.admin.ch/elcom/electricityprice/dimension/>
SELECT DISTINCT ?plz ?operatorId WHERE {
  GRAPH <https://lindas.admin.ch/territorial> { ?muni schema:postalCode ?plz }
  ?obs e:municipality ?muni ;
       e:operator ?operator ;
       e:period "%(period)s"^^<http://www.w3.org/2001/XMLSchema#gYear> .
  BIND(REPLACE(STR(?operator), "^.*/", "") AS ?operatorId)
}
ORDER BY ?plz
"""

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def normalise_tariff_url(raw: str) -> str:
    """Add a scheme to a bare-domain ``urltr`` value; pass everything else through.

    ``urlopen`` and a browser's ``new URL()`` both reject ``www.example.ch``
    outright, so this runs once here rather than in every consumer.
    """
    value = raw.strip()
    if not value or _SCHEME_RE.match(value):
        return value
    return f"https://{value}"


def looks_like_direct_json(url: str) -> bool:
    """Best-effort signal that a URL is the tariff file itself, not a page about it."""
    return url.lower().split("?", 1)[0].rstrip("/").endswith(".json")


def pick_tariff_url(raw_values: list[str]) -> tuple[str, bool]:
    """The single best tariff URL for an operator that published more than one.

    Most common value wins. Ties prefer a direct ``.json`` link over a
    landing page, then the lexicographically first value — so the choice is
    reproducible across runs against the same source data rather than
    depending on SPARQL result ordering. Returns ``("", False)`` when the
    operator published nothing usable.
    """
    counts = Counter(filter(None, (normalise_tariff_url(raw) for raw in raw_values)))
    if not counts:
        return "", False
    best_count = max(counts.values())
    chosen = min(
        (url for url, count in counts.items() if count == best_count),
        key=lambda url: (not looks_like_direct_json(url), url),
    )
    return chosen, looks_like_direct_json(chosen)


def build_operators(rows: list[dict]) -> list[dict]:
    """Rows from ``QUERY_OPERATORS`` collapsed to one entry per operator id."""
    urls_by_id: dict[int, list[str]] = defaultdict(list)
    identity_by_id: dict[int, dict] = {}
    for row in rows:
        operator_id = int(row["id"]["value"])
        identity_by_id.setdefault(
            operator_id,
            {
                "name": row["name"]["value"],
                "uid": row.get("uid", {}).get("value") or "",
                "website": row.get("website", {}).get("value") or "",
            },
        )
        urltr = row.get("urltr", {}).get("value") or ""
        if urltr:
            urls_by_id[operator_id].append(urltr)

    operators = []
    for operator_id, identity in identity_by_id.items():
        tariff_url, is_direct = pick_tariff_url(urls_by_id.get(operator_id, []))
        operators.append({
            "id": operator_id,
            "name": identity["name"],
            "uid": identity["uid"],
            "website": identity["website"],
            "tariff_url": tariff_url,
            "tariff_url_is_direct": is_direct,
        })
    return sorted(operators, key=lambda operator: operator["name"].casefold())


def build_postal_codes(rows: list[dict]) -> dict[str, list[int]]:
    """Rows from ``QUERY_POSTAL_CODES`` grouped into a plz -> operator ids map."""
    by_plz: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        by_plz[row["plz"]["value"]].add(int(row["operatorId"]["value"]))
    return {plz: sorted(ids) for plz, ids in sorted(by_plz.items())}


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
        parser.add_argument(
            "--min-tariff-urls",
            type=int,
            default=300,
            help="Refuse to write the fixture if fewer operators carry a tariff_url (default: 300).",
        )
        parser.add_argument(
            "--min-postal-codes",
            type=int,
            default=2000,
            help="Refuse to write the fixture if fewer postal codes resolve to an operator (default: 2000).",
        )

    def handle(self, *args, **options):
        period = options["period"]
        operators = build_operators(self._query(QUERY_OPERATORS % {"period": period}))
        postal_codes = build_postal_codes(self._query(QUERY_POSTAL_CODES % {"period": period}))

        if len(operators) < options["min_operators"]:
            raise CommandError(
                f"Only {len(operators)} operators returned for {period} "
                f"(expected at least {options['min_operators']}). Refusing to overwrite "
                f"{DATA_FILE.name} — check the query and the cube before rerunning."
            )

        ids = [operator["id"] for operator in operators]
        if len(set(ids)) != len(ids):
            raise CommandError("ElCom returned duplicate operator ids; refusing to write.")

        with_url = sum(1 for operator in operators if operator["tariff_url"])
        if with_url < options["min_tariff_urls"]:
            raise CommandError(
                f"Only {with_url} of {len(operators)} operators carry a tariff_url for {period} "
                f"(expected at least {options['min_tariff_urls']}). Refusing to overwrite "
                f"{DATA_FILE.name} — check the query and the cube before rerunning."
            )

        if len(postal_codes) < options["min_postal_codes"]:
            raise CommandError(
                f"Only {len(postal_codes)} postal codes resolved for {period} "
                f"(expected at least {options['min_postal_codes']}). Refusing to overwrite "
                f"{DATA_FILE.name} — check the territorial-graph join before rerunning."
            )

        known_ids = set(ids)
        unknown_referenced = {
            operator_id
            for operator_ids in postal_codes.values()
            for operator_id in operator_ids
            if operator_id not in known_ids
        }
        if unknown_referenced:
            raise CommandError(
                f"postal_codes references {len(unknown_referenced)} operator id(s) absent from "
                "the operator list; the two queries disagree — refusing to write."
            )

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
                    "postal_codes": postal_codes,
                },
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            handle.write("\n")

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(operators)} grid operators ({with_url} with a tariff_url) and "
                f"{len(postal_codes)} postal codes for {period} to {DATA_FILE}."
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
