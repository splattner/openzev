"""Versioned aggregate composition; see the dynamic tariff spec §3.3."""

from __future__ import annotations

from .adapters import DynamicApiVersion

#: Aggregate definitions per API version, possibly nested. Plain types
#: (grid, metering, …) are absent: they bundle nothing.
COMPOSITION: dict[str, dict[str, tuple[str, ...]]] = {
    DynamicApiVersion.V1_0_5: {
        "integrated": ("electricity", "grid"),
    },
    DynamicApiVersion.V2_0_0: {
        "dso": ("grid", "metering", "national_fees"),
        "dso_complete": ("dso", "regional_fees"),
        "integrated": ("electricity", "dso"),
        "integrated_complete": ("electricity", "dso_complete"),
    },
}


def aggregated_tariff_types(api_version: str, tariff_type: str) -> tuple[str, ...]:
    """Every leaf component ``tariff_type`` contains on ``api_version``.

    Expanded transitively, order-stable, deduplicated. Empty for plain
    types and for unknown versions/types (never fail a warning path).
    """
    version_table = COMPOSITION.get(api_version)
    if not version_table or tariff_type not in version_table:
        return ()

    leaves: list[str] = []

    def expand(item: str) -> None:
        nested = version_table.get(item)
        if nested is None:
            if item not in leaves:
                leaves.append(item)
            return
        for part in nested:
            expand(part)

    expand(tariff_type)
    return tuple(leaves)


def certain_components(tariff_type: str) -> tuple[str, ...]:
    """Components bundled on every API version defining ``tariff_type``.

    For the import preview, which runs on the parsed document before any
    probe has pinned the endpoint version: warning about these can never
    under-list.
    """
    expansions = [
        aggregated_tariff_types(version, tariff_type)
        for version in COMPOSITION
        if tariff_type in COMPOSITION[version]
    ]
    if not expansions:
        return ()
    certain = set.intersection(*(set(expansion) for expansion in expansions))
    # First-seen order across versions for stable messages.
    ordered = [item for expansion in expansions for item in expansion]
    return tuple(item for item in dict.fromkeys(ordered) if item in certain)


def possible_extra_components(tariff_type: str) -> tuple[str, ...]:
    """Components bundled on some but not all versions: union minus certain."""
    expansions = [
        aggregated_tariff_types(version, tariff_type)
        for version in COMPOSITION
        if tariff_type in COMPOSITION[version]
    ]
    if not expansions:
        return ()
    union = {item for expansion in expansions for item in expansion}
    certain = set(certain_components(tariff_type))
    ordered = [item for expansion in expansions for item in expansion]
    return tuple(item for item in dict.fromkeys(ordered) if item in union - certain)
