"""The archive contract: format version, sections, and their dependencies.

Everything about *what an archive looks like* lives here so the export and the
import agree by construction rather than by convention.

The field lists are written out by hand rather than derived from the API
serializers on purpose. An archive is a file format with a version number — a
field added to ``ParticipantSerializer`` for the UI must not silently change
what a v1 archive contains, and a field removed from the API must not silently
break every archive already sitting on someone's disk.
"""

# Bumped whenever the archive layout changes in a way an older importer cannot
# read. An archive naming a version that is not listed here is rejected outright
# rather than imported half-understood.
FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = frozenset({1})

MANIFEST_NAME = "manifest.json"
READINGS_DIR = "readings"

SECTION_ZEV = "zev"
SECTION_PARTICIPANTS = "participants"
SECTION_METERING_POINTS = "metering_points"
SECTION_TARIFFS = "tariffs"
SECTION_READINGS = "readings"
SECTION_INVOICES = "invoices"

# Ordered: this is also the order in which sections are written and imported,
# and ordering is a correctness constraint, not presentation. Participants must
# exist before the assignments that point at them, metering points before their
# readings, participants before the invoices billed to them.
SECTIONS = (
    SECTION_ZEV,
    SECTION_PARTICIPANTS,
    SECTION_METERING_POINTS,
    SECTION_TARIFFS,
    SECTION_READINGS,
    SECTION_INVOICES,
)

# What a section cannot be imported without. These mirror actual foreign keys,
# so the check is enforceable rather than advisory:
#
#   * assignments live inside the metering-point section and point at participants
#   * readings point at metering points
#   * invoices point at participants
#
# Invoices deliberately do *not* depend on tariffs. ``InvoiceItem`` stores
# ``tariff_category`` as a value, not a foreign key — an invoice is a finished
# document that records what was charged, not a live reference to the tariff
# that produced it. Requiring tariffs here would block the legitimate case of
# migrating billing history without the pricing structure.
SECTION_DEPENDENCIES = {
    SECTION_ZEV: (),
    SECTION_PARTICIPANTS: (),
    SECTION_METERING_POINTS: (SECTION_PARTICIPANTS,),
    SECTION_TARIFFS: (),
    SECTION_READINGS: (SECTION_METERING_POINTS,),
    SECTION_INVOICES: (SECTION_PARTICIPANTS,),
}

# The file each section occupies inside the archive. ``readings`` is absent
# because it is a directory of CSVs, not a single JSON document.
SECTION_FILES = {
    SECTION_ZEV: "zev.json",
    SECTION_PARTICIPANTS: "participants.json",
    SECTION_METERING_POINTS: "metering_points.json",
    SECTION_TARIFFS: "tariffs.json",
    SECTION_INVOICES: "invoices.json",
}

# ── Field lists ────────────────────────────────────────────────────────────
#
# ``owner`` is absent from ZEV_FIELDS and ``user`` from PARTICIPANT_FIELDS by
# design: an export never carries an account reference, so importing an archive
# can never grant anybody access to anything. The importing user becomes the
# owner and participants arrive unlinked, to be connected by hand.

ZEV_FIELDS = (
    "name",
    "start_date",
    "zev_type",
    "grid_operator",
    "grid_operator_elcom_id",
    "tariff_source_url",
    "grid_connection_point",
    "billing_interval",
    "invoice_prefix",
    "invoice_counter",
    "contract_counter",
    "invoice_language",
    "payment_term_days",
    "bank_iban",
    "bank_name",
    "vat_mode",
    "vat_number",
    "itemize_tariff_bands",
    "notes",
    "email_subject_template",
    "email_body_template",
    "local_tariff_notes",
    "additional_contract_notes",
)

PARTICIPANT_FIELDS = (
    "title",
    "first_name",
    "last_name",
    "email",
    "phone",
    "address_line1",
    "address_line2",
    "postal_code",
    "city",
    "valid_from",
    "valid_to",
    "notes",
    "allocation_weight",
)

METERING_POINT_FIELDS = (
    "meter_id",
    "meter_type",
    "is_active",
    "location_description",
)

ASSIGNMENT_FIELDS = (
    "valid_from",
    "valid_to",
    "allocation_mode",
)

TARIFF_FIELDS = (
    "name",
    "category",
    "billing_mode",
    "energy_type",
    "fixed_price_chf",
    "percentage",
    "split_key",
    "valid_from",
    "valid_to",
    "notes",
    "source_component",
    "source_series_name",
)

TARIFF_PERIOD_FIELDS = (
    "period_type",
    "price_chf_per_kwh",
    "time_from",
    "time_to",
    "weekdays",
    "months",
    "label",
)

INVOICE_FIELDS = (
    "invoice_number",
    "period_start",
    "period_end",
    "status",
    "total_local_kwh",
    "total_grid_kwh",
    "total_feed_in_kwh",
    "subtotal_chf",
    "vat_rate",
    "vat_chf",
    "embedded_vat_chf",
    "total_chf",
    "sent_at",
    "due_date",
    "notes",
)

INVOICE_ITEM_FIELDS = (
    "item_type",
    "tariff_category",
    "description",
    "quantity_kwh",
    "unit",
    "unit_price_chf",
    "total_chf",
    "sort_order",
)

# ``resolution`` and ``import_source`` extend the layout ``csv_importer`` reads.
# It maps columns by name and ignores the ones it does not know, so these files
# stay loadable through the normal metering import — but a backup that silently
# turned hourly readings into 15-minute ones would not be a backup, so the
# archive carries them and the archive's own reader restores them.
READING_CSV_COLUMNS = (
    "meter_id",
    "timestamp",
    "energy_kwh",
    "direction",
    "resolution",
    "import_source",
)


class ArchiveError(ValueError):
    """The archive cannot be read: not a ZIP, no manifest, unknown version."""


def normalise_sections(requested, *, available=None):
    """Return ``requested`` as an ordered, de-duplicated tuple of known sections.

    Raises ``ValueError`` naming every unknown section at once, and — when
    ``available`` is given — every section that is not in the archive.
    """
    if requested is None:
        return tuple(SECTIONS if available is None else available)

    if isinstance(requested, str) or not hasattr(requested, "__iter__"):
        raise ValueError("sections must be a list of section names.")

    requested = [str(name) for name in requested]
    unknown = [name for name in requested if name not in SECTIONS]
    if unknown:
        raise ValueError(
            f"Unknown section(s): {', '.join(sorted(set(unknown)))}. "
            f"Valid sections are: {', '.join(SECTIONS)}."
        )

    if available is not None:
        missing = [name for name in requested if name not in available]
        if missing:
            raise ValueError(
                f"Section(s) not present in this archive: {', '.join(sorted(set(missing)))}."
            )

    return tuple(name for name in SECTIONS if name in set(requested))


def missing_dependencies(sections):
    """Map each selected section to the prerequisites it is missing.

    Empty when the selection is coherent. The UI is expected to grey out a
    section whose prerequisite is unselected; this is the check that makes the
    rule enforced rather than assumed.
    """
    selected = set(sections)
    return {
        section: [dep for dep in SECTION_DEPENDENCIES[section] if dep not in selected]
        for section in sections
        if any(dep not in selected for dep in SECTION_DEPENDENCIES[section])
    }


def check_dependencies(sections):
    problems = missing_dependencies(sections)
    if not problems:
        return
    detail = "; ".join(
        f"{section} requires {', '.join(deps)}" for section, deps in sorted(problems.items())
    )
    raise ValueError(f"Incomplete section selection: {detail}.")


def check_format_version(version):
    if version not in SUPPORTED_FORMAT_VERSIONS:
        raise ArchiveError(
            f"Unsupported archive format version {version!r}. "
            f"This instance reads version(s): {', '.join(str(v) for v in sorted(SUPPORTED_FORMAT_VERSIONS))}."
        )
