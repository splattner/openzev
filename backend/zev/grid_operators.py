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
