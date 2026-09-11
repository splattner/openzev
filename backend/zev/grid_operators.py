"""The official ElCom list of Swiss distribution grid operators (VNB).

``Zev.grid_operator`` is free text, which meant the same operator reached the
database as "EKZ", "Elektrizitätswerke des Kantons Zürich", or a typo — and the
value is printed on contracts and invoices via ``{{ zev.grid_operator }}``.

ElCom publishes its electricity-tariff data as Linked Data on the federal
LINDAS platform under `TermsOfUse/Open-Use`. The operator list is derived from
it by ``manage.py fetch_grid_operators`` and checked in as a fixture rather
than queried at request time: it changes on a tariff-year cadence, it is a few
hundred kilobytes, and the ZEV-creation wizard must not fail because an
external SPARQL endpoint is unreachable.

The list is a *suggestion source*, never a constraint. A small utility missing
from the tariff cube — a recent merger, a municipal works with no published
tariff — must still be enterable, so ``grid_operator`` stays free text and
``grid_operator_elcom_id`` is simply null when the name was typed by hand.

The fixture also carries, per operator, ElCom's ``urltr`` dimension — "URL for
machine-readable tariffs", the Art. 7b address the VSE importer consumes — and
a postal-code-to-operator-id map, so a ZEV can be offered a suggested operator
and tariff URL from its own postal code (``Zev.postal_code``) instead of a
flat list.

Both are offered, never written automatically. A postal code resolving to one
operator is still only a suggestion — a small utility missing from the cube
would otherwise be silently overridden — and the URL doubly so: it is free
text an operator typed into a form, and it drifts between an operator's
re-upload and ElCom's next refresh. One operator's registered URL was found
to 404 while this feature was being built, with the live file sitting at a
different address entirely (see #691). A suggested URL must be fetched and
confirmed to work before anything is saved from it — never trusted on the
strength of appearing in this fixture alone.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "data" / "grid_operators.json"


@lru_cache(maxsize=1)
def load_grid_operators() -> dict:
    """The fixture as written by ``fetch_grid_operators``.

    Cached: the file is static for the life of the process, and this is read on
    every request that renders the operator picker.
    """
    with DATA_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


def grid_operator_ids() -> set[int]:
    """Every known ElCom operator id, for validating what a client sends."""
    return {operator["id"] for operator in load_grid_operators()["operators"]}


def grid_operators_for_postal_code(postal_code: str) -> list[dict]:
    """Operator suggestions for a postal code: empty, one, or a short list.

    Looked up against the checked-in fixture, not LINDAS — same reasoning as
    ``load_grid_operators``. An unrecognised or foreign postal code simply
    has no entry in the map and returns ``[]``, which is the correct outcome:
    the caller falls back to the full picker rather than treating it as an
    error.
    """
    postal_code = postal_code.strip()
    if not postal_code:
        return []
    data = load_grid_operators()
    ids = data.get("postal_codes", {}).get(postal_code, [])
    if not ids:
        return []
    by_id = {operator["id"]: operator for operator in data["operators"]}
    return [by_id[operator_id] for operator_id in ids if operator_id in by_id]
