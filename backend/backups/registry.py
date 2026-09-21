"""What a backup contains: every model, its section, and how it is scoped.

A backup archive is *logical* (ADR 0023): per-section JSON Lines written with
Django's own serializer, so every column — including the primary key — travels
as it is stored. Two consequences shape this file:

* **Fields are not listed here.** They come from the model at write time, so a
  new column is backed up the moment it exists and cannot be forgotten. What
  *can* be forgotten is a whole new model, so the registry is closed under a
  coverage test: every installed model must appear in a section below or in
  ``EXCLUDED_MODELS`` with a reason.
* **Many-to-many fields are not serialized.** ``User.groups`` and
  ``User.user_permissions`` are unused by the application (roles are the
  ``User.role`` column), and their target ids are not stable across instances.

Sections are written in order, and that order is a correctness constraint for
restore: parents before the rows that point at them.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── instance scope ───────────────────────────────────────────────────────────

# (section name, model labels). Each section is one ``instance/<name>.jsonl``.
INSTANCE_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("app_settings", ("accounts.AppSettings", "accounts.FeatureFlag", "accounts.VatRate")),
    ("oauth_providers", ("accounts.OAuthProvider",)),
    ("templates", ("invoices.PdfTemplate", "invoices.EmailTemplate")),
    ("dynamic_sources", ("tariffs.DynamicTariffSource",)),
    ("dynamic_prices", ("tariffs.DynamicPricePoint",)),
    (
        "accounts",
        (
            "accounts.User",
            "accounts.ApiKey",
            "accounts.TotpDevice",
            "accounts.MfaRecoveryCode",
            "accounts.WebAuthnCredential",
            "accounts.SocialAccount",
        ),
    ),
)

# Rows whose ZEV foreign key is null: they survive a ZEV's deletion on purpose
# (``ContractIssue`` is documented as an immutable archive; audit events keep
# the trail of a ZEV that no longer exists), so they belong to the instance,
# not to any one community.
UNSCOPED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("unscoped_audit_events", "audit.AuditEvent"),
    ("unscoped_contract_issues", "invoices.ContractIssue"),
    ("unscoped_import_logs", "metering.ImportLog"),
)

# ── ZEV scope ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ZevPart:
    """One model's rows within a ZEV section.

    ``lookup`` is the ORM path from the model to its ZEV, so the queryset is
    ``Model.objects.filter(**{lookup: zev.pk})``. ``order`` is the write order:
    a deterministic order makes archives reproducible and lets a large table be
    read by an index.
    """

    label: str
    lookup: str
    order: tuple[str, ...] = ("pk",)


# (section name, parts). Each section is one ``zevs/<id>/<name>.jsonl``. Order
# follows the transfer archive's dependency order: a section only points at
# sections written before it (or at instance-scope rows).
ZEV_SECTIONS: tuple[tuple[str, tuple[ZevPart, ...]], ...] = (
    ("zev", (ZevPart("zev.Zev", "pk"),)),
    (
        "participants",
        (
            ZevPart("zev.Participant", "zev"),
            ZevPart("zev.ParticipantOnboardingToken", "participant__zev"),
        ),
    ),
    (
        "metering_points",
        (
            ZevPart("zev.MeteringPoint", "zev"),
            ZevPart("zev.MeteringPointAssignment", "metering_point__zev"),
        ),
    ),
    (
        "tariffs",
        (
            ZevPart("tariffs.Tariff", "zev"),
            ZevPart("tariffs.TariffPeriod", "tariff__zev"),
        ),
    ),
    (
        "readings",
        (ZevPart("metering.MeterReading", "metering_point__zev", ("metering_point_id", "timestamp", "direction")),),
    ),
    ("import_logs", (ZevPart("metering.ImportLog", "zev"),)),
    (
        "invoices",
        (
            ZevPart("invoices.Invoice", "zev"),
            ZevPart("invoices.InvoiceItem", "invoice__zev"),
            ZevPart("invoices.InvoiceDynamicSourceEvidence", "invoice__zev"),
            ZevPart("invoices.InvoiceAccessToken", "invoice__zev"),
            ZevPart("invoices.EmailLog", "invoice__zev"),
        ),
    ),
    ("contract_issues", (ZevPart("invoices.ContractIssue", "zev"),)),
    ("audit_events", (ZevPart("audit.AuditEvent", "zev"),)),
)

# File-backed columns whose bytes are copied into the archive, as
# ``(model label, field name, lookup to the ZEV)``. Paired with a
# coverage test that fails if a backed-up model gains a ``FileField`` not
# listed here — the omission that made the old ``pg_dump`` guidance lose every
# invoice PDF.
MEDIA_FIELDS: tuple[tuple[str, str, str], ...] = (("invoices.Invoice", "pdf_file", "zev"),)

# ── deliberately not backed up ───────────────────────────────────────────────

EXCLUDED_MODELS: dict[str, str] = {
    # Short-lived credentials and flow state: restoring a stale one is worse
    # than not having it.
    "accounts.EmailVerificationToken": "short-lived; a restored token would be stale or replayable",
    "accounts.MagicLinkToken": "short-lived; a restored token would be stale or replayable",
    "accounts.OAuthState": "in-flight login state, valid for minutes",
    "accounts.OAuthExchangeCode": "one-time login code, valid for minutes",
    # Operational records about artifacts that do not travel.
    "exports.ExportJob": "transient; its artifact is deleted after EXPORT_RETENTION_HOURS",
    "backups.BackupDestination": "instance configuration of the backup system itself; recreated on restore",
    "backups.BackupJob": "history of other archives; must never be inside the archive it describes",
    "backups.RestoreJob": "history of restores on this instance; describes archives, is not part of one",
    # Scheduler state. Settings-defined schedules are recreated by beat itself;
    # the one admin-editable schedule arrives with the scheduler (phase 4).
    "django_celery_beat.ClockedSchedule": "scheduler state; see PeriodicTask",
    "django_celery_beat.CrontabSchedule": "scheduler state; see PeriodicTask",
    "django_celery_beat.IntervalSchedule": "scheduler state; see PeriodicTask",
    "django_celery_beat.SolarSchedule": "scheduler state; see PeriodicTask",
    "django_celery_beat.PeriodicTask": "recreated by beat from CELERY_BEAT_SCHEDULE; backup scheduling lands in phase 4",
    "django_celery_beat.PeriodicTasks": "scheduler change marker, not data",
    # Framework tables.
    "admin.LogEntry": "Django admin history; the audit stream is the record of truth",
    "auth.Permission": "generated by migrations; ids differ per instance",
    "auth.Group": "unused by the application; roles are User.role",
    "contenttypes.ContentType": "generated by migrations; ids differ per instance",
    "sessions.Session": "sessions are per-instance and short-lived",
}

# ── helpers ──────────────────────────────────────────────────────────────────


def instance_labels() -> list[str]:
    return [label for _, labels in INSTANCE_SECTIONS for label in labels]


def zev_labels() -> list[str]:
    return [part.label for _, parts in ZEV_SECTIONS for part in parts]


def unscoped_labels() -> list[str]:
    return [label for _, label in UNSCOPED_SECTIONS]


def backed_up_labels() -> set[str]:
    """Every model label some section writes."""
    return {*instance_labels(), *zev_labels(), *unscoped_labels()}
