"""Restore one community into a running instance (SPEC-2026-09-backup-and-restore §6.6).

Unlike an instance restore this runs against live data, next to communities and
accounts that must not notice it. The rules that follow from that:

* **The ``Zev`` row is updated in place, never deleted.** Deleting it would run
  ``SET NULL`` on every audit event that names the community and on every
  account whose ``preferred_zev`` it is — a rewrite of the audit trail and of
  accounts, both of which a per-ZEV restore promises not to touch (ADR 0023).
* **Accounts are relinked by natural key, never written.** The backup's user ids
  mean nothing on another instance, so ``Participant.user`` and friends are
  resolved through ``account_refs.json`` to whoever has that email (or username)
  *now*, and left unlinked when nobody does.
* **The audit trail is not restored at all.** It is append-only and already
  contains everything the backup's copy does; the restore adds one entry.
* **Every check runs twice**: once to tell the operator (a dry run is the plan),
  and again under the row lock immediately before the first write, because
  minutes can pass between them.

The conflicts a restore reports come in two kinds. *Overridable* ones (a sent or
paid invoice that would be deleted or reverted, an issued contract that would be
deleted) need ``force``. *Hard* ones cannot be forced past without damaging
something else — a meter id now owned by another community, a referenced price
source that no longer exists, an export or another restore in flight, an owner
who cannot be found — and always refuse.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import BinaryIO

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction

from . import archive
from .registry import ZEV_SECTIONS
from .restore import (
    MediaUndo,
    RestoreError,
    RestoreReport,
    _load_member,
    _reconcile_sequences,
    _records,
    _restore_media,
    check_migrations,
)

logger = logging.getLogger(__name__)

# The trail is never restored (see the module docstring); its section is skipped.
_KEPT_SECTIONS = frozenset({"audit_events"})
_LOCKED_STATUSES = ("sent", "paid")
_MAX_LISTED = 20


class RestoreRefused(RestoreError):
    """The restore was refused by its own rules; ``plan`` says why."""

    def __init__(self, message: str, plan: dict):
        super().__init__(message)
        self.plan = plan


@dataclass
class ArchiveFacts:
    """What the plan needs from the archive, read without loading a single row."""

    zev_id: str
    zev_name: str
    owner_ref: int | None
    users: list[dict]
    invoices: dict[str, str]  # invoice id → status
    contract_issue_ids: set[str]
    meter_ids: set[str]
    external: dict[str, set[str]] = field(default_factory=dict)  # model label → referenced ids
    counts: dict[str, int] = field(default_factory=dict)  # section → rows in the backup
    media_files: int = 0
    media_missing: int = 0


@dataclass
class ZevRestoreResult:
    plan: dict
    report: RestoreReport | None = None
    safety_backup_id: str | None = None


# ── what the archive says ────────────────────────────────────────────────────

def _raw_records(zf, member: str):
    """JSON lines of a member as dicts. Cheaper than deserializing when only a few fields matter."""
    with zf.open(member) as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _foreign_keys_outside_scope() -> dict[str, list]:
    """Model label → its foreign keys to rows that are neither this community's nor an account.

    Those rows (price sources) belong to the instance; a restore must find them
    already there, since it does not create them.
    """
    in_scope = {part.label for _, parts in ZEV_SECTIONS for part in parts}
    user_model = get_user_model()
    found: dict[str, list] = {}
    for _, parts in ZEV_SECTIONS:
        for part in parts:
            model = apps.get_model(part.label)
            fields = [
                f for f in model._meta.concrete_fields
                if f.is_relation and f.related_model._meta.label not in in_scope and f.related_model is not user_model
            ]
            if fields:
                found[part.label] = fields
    return found


def read_facts(zf, manifest: dict, entry: dict) -> ArchiveFacts:
    zev_id = entry["id"]
    base = f"zevs/{zev_id}"

    zev_record = next(_raw_records(zf, f"{base}/zev.jsonl"))
    refs = json.loads(zf.read(f"{base}/account_refs.json"))

    facts = ArchiveFacts(
        zev_id=zev_id,
        zev_name=zev_record["fields"].get("name", ""),
        owner_ref=zev_record["fields"].get("owner"),
        users=refs.get("users", []),
        invoices={},
        contract_issue_ids=set(),
        meter_ids=set(),
        counts=dict(entry["counts"]),
        media_files=entry.get("media", {}).get("files", 0),
        media_missing=len(entry.get("media", {}).get("missing", [])),
    )

    external = _foreign_keys_outside_scope()
    wanted = {"metering_points", "tariffs", "invoices", "contract_issues"}
    for name, parts in ZEV_SECTIONS:
        if name not in wanted:
            continue
        for record in _raw_records(zf, f"{base}/{name}.jsonl"):
            label = record["model"]
            # ``json`` gives the model label lower-cased (``invoices.invoice``).
            canonical = next((p.label for p in parts if p.label.lower() == label), None)
            if canonical is None:
                continue
            fields = record["fields"]
            if canonical == "invoices.Invoice":
                facts.invoices[record["pk"]] = fields.get("status", "")
            elif canonical == "invoices.ContractIssue":
                facts.contract_issue_ids.add(record["pk"])
            elif canonical == "zev.MeteringPoint":
                facts.meter_ids.add(fields.get("meter_id", ""))
            for fk in external.get(canonical, []):
                value = fields.get(fk.name)
                if value is not None:
                    facts.external.setdefault(fk.related_model._meta.label, set()).add(str(value))
    return facts


# ── what the instance says ───────────────────────────────────────────────────

def resolve_accounts(users: list[dict]) -> tuple[dict[int, int | None], list[str]]:
    """Map each backed-up user id to whoever has that email (else username) now.

    Never creates or changes an account. A reference nobody matches — or that
    matches more than one account, which cannot be resolved safely — maps to
    ``None`` and is reported by name.
    """
    user_model = get_user_model()
    mapping: dict[int, int | None] = {}
    missing: list[str] = []
    for ref in users:
        found = []
        if ref.get("email"):
            found = list(user_model.objects.filter(email__iexact=ref["email"]).values_list("pk", flat=True)[:2])
        if not found and ref.get("username"):
            found = list(user_model.objects.filter(username=ref["username"]).values_list("pk", flat=True)[:2])
        if len(found) == 1:
            mapping[ref["id"]] = found[0]
        else:
            mapping[ref["id"]] = None
            label = ref.get("email") or ref.get("username") or f"user {ref['id']}"
            missing.append(f"{label} (ambiguous)" if len(found) > 1 else label)
    return mapping, missing


def _listed(items: list[str]) -> list[str]:
    return items[:_MAX_LISTED] + ([f"and {len(items) - _MAX_LISTED} more"] if len(items) > _MAX_LISTED else [])


def _conflict(kind: str, detail: str, *, overridable: bool) -> dict:
    return {"kind": kind, "detail": detail, "overridable": overridable}


def evaluate(facts: ArchiveFacts, *, force: bool, exclude_job=None) -> dict:
    """The plan: what a restore would replace, who it would relink, and what stands in its way."""
    zev_model = apps.get_model("zev.Zev")
    zev = zev_model.objects.filter(pk=facts.zev_id).first()
    mapping, missing = resolve_accounts(facts.users)

    sections: dict[str, dict] = {}
    for name, parts in ZEV_SECTIONS:
        current = sum(
            apps.get_model(part.label)._base_manager.filter(**{part.lookup: facts.zev_id}).count() for part in parts
        )
        sections[name] = {"backup": facts.counts.get(name, 0), "current": current, "kept": name in _KEPT_SECTIONS}

    conflicts: list[dict] = []

    # Overridable: things a restore would destroy or roll back that were issued to someone.
    invoice_model = apps.get_model("invoices.Invoice")
    deleted, reverted = [], []
    for row in invoice_model._base_manager.filter(zev_id=facts.zev_id, status__in=_LOCKED_STATUSES).values(
        "pk", "status", "invoice_number"
    ):
        key = str(row["pk"])
        if key not in facts.invoices:
            deleted.append(f"{row['invoice_number']} ({row['status']})")
        elif facts.invoices[key] != row["status"]:
            reverted.append(f"{row['invoice_number']} ({row['status']} → {facts.invoices[key]})")
    conflicts += [_conflict("sent_invoice_deleted", d, overridable=True) for d in _listed(deleted)]
    conflicts += [_conflict("sent_invoice_reverted", d, overridable=True) for d in _listed(reverted)]

    contract_model = apps.get_model("invoices.ContractIssue")
    lost_contracts = [
        f"{row['document_number']} (v{row['version']})"
        for row in contract_model._base_manager.filter(zev_id=facts.zev_id).values("pk", "document_number", "version")
        if str(row["pk"]) not in facts.contract_issue_ids
    ]
    conflicts += [_conflict("contract_issue_deleted", d, overridable=True) for d in _listed(lost_contracts)]

    # Hard: forcing these would corrupt something else.
    point_model = apps.get_model("zev.MeteringPoint")
    stolen = [
        f"{row['meter_id']} → {row['zev__name']}"
        for row in point_model._base_manager.filter(meter_id__in=facts.meter_ids)
        .exclude(zev_id=facts.zev_id).values("meter_id", "zev__name")
    ]
    conflicts += [_conflict("meter_id_owned_by_other_zev", d, overridable=False) for d in _listed(stolen)]

    for label, ids in sorted(facts.external.items()):
        model = apps.get_model(label)
        present = {str(pk) for pk in model._base_manager.filter(pk__in=ids).values_list("pk", flat=True)}
        gone = sorted(ids - present)
        conflicts += [
            _conflict("referenced_row_missing", f"{model._meta.verbose_name}: {pk}", overridable=False)
            for pk in gone[:_MAX_LISTED]
        ]

    if zev is None and mapping.get(facts.owner_ref) is None:
        conflicts.append(_conflict("owner_not_found", "the community's owner has no matching account", overridable=False))

    export_model = apps.get_model("exports.ExportJob")
    if export_model._base_manager.filter(zev_id=facts.zev_id, status__in=("queued", "running")).exists():
        conflicts.append(_conflict("export_in_progress", "an annual-statement export is running", overridable=False))

    restore_model = apps.get_model("backups.RestoreJob")
    busy = restore_model._base_manager.filter(target_zev_id=facts.zev_id, status__in=("queued", "running"))
    if exclude_job is not None:
        busy = busy.exclude(pk=exclude_job)
    if busy.exists():
        conflicts.append(_conflict("restore_in_progress", "another restore of this community is running", overridable=False))

    blocked = any(not c["overridable"] for c in conflicts) or (bool(conflicts) and not force)
    return {
        "zev": {
            "id": facts.zev_id,
            "name": facts.zev_name,
            "exists_now": zev is not None,
            "current_name": zev.name if zev is not None else "",
        },
        "sections": sections,
        "accounts": {"relink": sum(1 for v in mapping.values() if v is not None), "missing": missing},
        "media": {"files": facts.media_files, "missing": facts.media_missing},
        "conflicts": conflicts,
        "blocked": blocked,
        "safety_backup_id": None,
        "restored": None,
    }


def _refusal(plan: dict) -> RestoreRefused:
    hard = sum(1 for c in plan["conflicts"] if not c["overridable"])
    soft = sum(1 for c in plan["conflicts"] if c["overridable"])
    if hard:
        message = f"The restore was refused: {hard} problem(s) cannot be overridden. See the plan."
    else:
        message = f"The restore was refused: it would delete or roll back {soft} issued record(s). Review the plan, then restore with force."
    return RestoreRefused(message, plan)


# ── applying ─────────────────────────────────────────────────────────────────

def _scoped_parts() -> list[tuple[str, tuple]]:
    """``(section, parts)`` for every section that is restored, in load order — the trail is not."""
    return [(name, parts) for name, parts in ZEV_SECTIONS if name not in _KEPT_SECTIONS]


def _clear_zev(zev_id: str, contract_issue_ids: set[str]) -> None:
    """Delete the community's rows, dependants first — but neither its own row nor its audit trail.

    Issued contracts outlive a deleted community with no community (``SET NULL``),
    so recreating it would collide with them on primary key. The ones the backup
    also holds are replaced by that copy, which is a relink, not a loss.
    """
    apps.get_model("invoices.ContractIssue")._base_manager.filter(
        zev__isnull=True, pk__in=contract_issue_ids
    ).delete()
    for name, parts in reversed(_scoped_parts()):
        for part in reversed(parts):
            if part.label == "zev.Zev":
                continue
            apps.get_model(part.label)._base_manager.filter(**{part.lookup: zev_id}).delete()


def _account_transform(model, mapping: dict[int, int | None], current_owner_id: int | None):
    """A per-record hook that points user foreign keys at today's accounts."""
    user_model = get_user_model()
    fields = [f for f in model._meta.concrete_fields if f.is_relation and f.related_model is user_model]
    if not fields:
        return None

    def transform(instance) -> None:
        for fk in fields:
            old = getattr(instance, fk.attname)
            if old is None:
                continue
            new = mapping.get(old)
            if new is None and not fk.null:
                # The one required account link is the community's owner; if the
                # community exists, its current owner stays.
                new = current_owner_id
            setattr(instance, fk.attname, new)

    return transform


def _load_zev_row(zf, member: str, transform, report: RestoreReport, *, write: bool) -> None:
    """Replace the community's own row in place (update if it exists, insert if not)."""
    count = 0
    for record in _records(zf, member, frozenset({"zev.Zev"})):
        instance = record.object
        if transform is not None:
            transform(instance)
        if write:
            # ``raw`` keeps the stored timestamps and updates the row when it is
            # there — the reason a per-ZEV restore never deletes it.
            instance.save_base(raw=True)
        count += 1
    if count != 1:
        raise RestoreError(f"{member} must hold exactly one community, but holds {count}.")
    report.counts["zev.Zev"] = 1


def _apply(zf, manifest, facts, report: RestoreReport, referenced: set[str], *, write: bool):
    zev_id = facts.zev_id
    base = f"zevs/{zev_id}"
    mapping, _ = resolve_accounts(facts.users)
    zev_model = apps.get_model("zev.Zev")
    current = zev_model.objects.filter(pk=zev_id).values_list("owner_id", flat=True).first()
    owner_fallback = current
    for name, parts in _scoped_parts():
        member = f"{base}/{name}.jsonl"
        expected = manifest["members"][member]["models"]
        if name == "zev":
            transform = _account_transform(zev_model, mapping, owner_fallback)
            _load_zev_row(zf, member, transform, report, write=write)
            continue
        allowed = frozenset(part.label for part in parts)
        # One hook per section: every model in it that has an account link gets remapped.
        transforms = {p.label: _account_transform(apps.get_model(p.label), mapping, owner_fallback) for p in parts}

        def transform(instance, transforms=transforms):
            hook = transforms.get(instance._meta.label)
            if hook is not None:
                hook(instance)

        _load_member(zf, member, allowed, expected, report, referenced, write=write, transform=transform)


def _verify_counts(zev_id: str, report: RestoreReport) -> None:
    for _, parts in _scoped_parts():
        for part in parts:
            expected = report.counts.get(part.label, 0)
            actual = apps.get_model(part.label)._base_manager.filter(**{part.lookup: zev_id}).count()
            if actual != expected:
                raise RestoreError(f"{part.label}: loaded {expected} rows but the community holds {actual}.")


def restore_zev(
    source: BinaryIO,
    zev_id: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    safety_backup: Callable[[], str | None] | None = None,
    exclude_job=None,
    progress: Callable[[str], None] = lambda message: None,
) -> ZevRestoreResult:
    """Restore one community from the backup in ``source``.

    ``dry_run`` returns the plan — including refusals, unraised — and reads every
    record for schema fit, but writes nothing. Otherwise a refusal raises
    ``RestoreRefused``. ``safety_backup`` runs after the plan passes and before
    the first write; it returns the id of a backup of the community as it is now
    (or ``None`` when it does not exist yet), and if it raises nothing is written.
    """
    zev_id = str(zev_id)
    with archive.open_archive(source) as zf:
        progress("Verifying the archive…")
        manifest = archive.verify_open_archive(zf)["manifest"]
        entry = next((z for z in manifest["zevs"] if z["id"] == zev_id), None)
        if entry is None:
            raise RestoreError("This backup does not contain that community.")
        check_migrations(manifest)

        progress("Planning…")
        facts = read_facts(zf, manifest, entry)
        plan = evaluate(facts, force=force, exclude_job=exclude_job)
        plan["backup"] = {
            "created_at": manifest.get("created_at"),
            "scope": manifest["scope"],
            "instance_name": manifest.get("instance_name", ""),
            "openzev_version": manifest.get("openzev_version", ""),
        }

        report = RestoreReport(dry_run=dry_run, manifest=manifest)
        if dry_run:
            # Read every record so a section the schema cannot hold is found now.
            _apply(zf, manifest, facts, report, set(), write=False)
            plan["restored"] = None
            return ZevRestoreResult(plan=plan, report=report)

        if plan["blocked"]:
            raise _refusal(plan)

        safety_id = None
        if safety_backup is not None and plan["zev"]["exists_now"]:
            progress("Taking a safety backup of the community as it is now…")
            safety_id = safety_backup()
        plan["safety_backup_id"] = safety_id

        referenced: set[str] = set()
        undo = MediaUndo()
        zev_model = apps.get_model("zev.Zev")
        try:
            with transaction.atomic():
                # The row lock serializes this with anything else that locks the
                # community (contract issuance does) for the whole restore.
                zev_model.objects.select_for_update().filter(pk=zev_id).first()
                fresh = evaluate(facts, force=force, exclude_job=exclude_job)
                plan.update({key: fresh[key] for key in ("zev", "sections", "accounts", "conflicts", "blocked")})
                if plan["blocked"]:
                    raise _refusal(plan)

                progress("Replacing the community's data…")
                _clear_zev(zev_id, facts.contract_issue_ids)
                _apply(zf, manifest, facts, report, referenced, write=True)
                _verify_counts(zev_id, report)
                connection.check_constraints()
                progress("Restoring invoice PDFs…")
                _restore_media(zf, manifest, referenced, report, undo, only_zev=zev_id)
                _reconcile_sequences(report, [p.label for _, parts in _scoped_parts() for p in parts])
        except (IntegrityError, DatabaseError) as exc:
            logger.exception("Per-ZEV restore was rejected by the database")
            undo.rollback()
            raise RestoreError(
                "The database rejected the backup's data; nothing was restored. The server log has the details."
            ) from exc
        except BaseException:
            undo.rollback()
            raise
        finally:
            undo.close()

        plan["restored"] = dict(sorted(report.counts.items()))
        return ZevRestoreResult(plan=plan, report=report, safety_backup_id=safety_id)
