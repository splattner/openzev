"""Display pricing belongs to tariffs."""

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(("filename", "forbidden"), [
    ("display_pricing.py", "invoices"),
    ("views.py", "invoices.tariff_pricing"),
    ("serializers.py", "invoices.tariff_pricing"),
])
def test_display_pricing_import_direction(filename, forbidden):
    source = Path(__file__).with_name(filename).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            imports = [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        else:
            continue
        for name in imports:
            assert name != forbidden and not name.startswith(forbidden + "."), f"{filename} imports {name}"
