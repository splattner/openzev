"""DRF mixins that wire views into the audit trail."""
from __future__ import annotations

from .models import AuditEventStatus
from .services import build_diff, build_instance_snapshot, record_audit_event


class AuditedUpdateMixin:
    """Record an audit event with a before/after field diff on update.

    Tracked fields default to the serializer's *writable* fields. Deriving them
    rather than hand-listing them is the point of this mixin: a hand-written
    list silently stops matching what the endpoint accepts as soon as a field is
    added to the serializer, and the resulting diff looks empty even though the
    update succeeded.

    Subclasses must set :attr:`audit_action_category`, :attr:`audit_action_type`
    and :attr:`audit_target_type`. Override :attr:`audit_tracked_fields` only to
    deliberately deviate from the serializer, and :attr:`audit_extra_fields` to
    track something the serializer does not expose.
    """

    audit_action_category: str = ""
    audit_action_type: str = ""
    audit_target_type: str = ""
    audit_target_label: str = ""
    audit_tracked_fields: list[str] | None = None
    audit_extra_fields: tuple[str, ...] = ()

    def get_audit_tracked_fields(self, serializer) -> list[str]:
        if self.audit_tracked_fields is not None:
            tracked = list(self.audit_tracked_fields)
        else:
            tracked = [name for name, field in serializer.fields.items() if not field.read_only]
        return tracked + [name for name in self.audit_extra_fields if name not in tracked]

    def get_audit_target_display(self, instance) -> str:
        return str(instance)

    def get_audit_summary(self, instance) -> str:
        label = self.audit_target_label or self.audit_target_type.rsplit(".", 1)[-1].lower()
        return f"Updated {label} {self.get_audit_target_display(instance)}."

    def perform_update(self, serializer):
        tracked_fields = self.get_audit_tracked_fields(serializer)
        before = build_instance_snapshot(self.get_object(), tracked_fields)
        instance = serializer.save()
        after = build_instance_snapshot(instance, tracked_fields)

        record_audit_event(
            request=self.request,
            action_category=self.audit_action_category,
            action_type=self.audit_action_type,
            target_type=self.audit_target_type,
            target=instance,
            target_id=str(instance.pk),
            target_display=self.get_audit_target_display(instance),
            summary=self.get_audit_summary(instance),
            status=AuditEventStatus.SUCCESS,
            changes=build_diff(before, after, tracked_fields),
        )
        return instance
