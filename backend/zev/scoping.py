"""
Shared role-based scoping for ZEV-related viewsets.

Every ZEV-scoped viewset applies the same three-tier visibility rule:

- **admin** — sees everything
- **zev_owner** — sees objects belonging to ZEVs they own
- **participant** — sees only objects linked to their own participant record
  (or nothing, for owner-only resources such as tariffs)

Centralizing the rule makes the tenant-isolation logic auditable in one
place instead of being re-implemented per viewset.

Reads and writes are scoped here together on purpose. Scoping only the
queryset protects what a caller can *see* while leaving what they can *write*
open: DRF consults ``has_object_permission`` for detail routes but never on
create, so a payload naming another community's ZEV was accepted (#424). The
write rule is the mirror of the read rule — you may only create or move an
object into a ZEV you would be allowed to see.
"""

from rest_framework import serializers


class ZevScopedQuerySetMixin:
    """Mixin for DRF viewsets that scopes reads and writes by user role.

    Class attributes:

    - ``zev_owner_filter``: ORM lookup path from the model to the owning
      user, e.g. ``"zev__owner"``.
    - ``participant_filter``: ORM lookup path from the model to the
      participant's user, e.g. ``"participant__user"``. ``None`` means
      participants get an empty queryset (owner-only resource).
    - ``participant_distinct``: set to ``True`` when the participant filter
      traverses a to-many relation and may produce duplicate rows.
    - ``scope_parent_path``: attribute chain from a write payload to the ZEV
      the object would belong to. The first element is the key in
      ``validated_data``; any further elements walk from that object to its
      ``Zev``. ``("zev",)`` means the payload carries the ZEV itself;
      ``("metering_point", "zev")`` means it carries a metering point whose
      ``.zev`` is the one that matters. ``None`` disables the write check.
    """

    zev_owner_filter: str
    participant_filter: str | None = None
    participant_distinct: bool = False
    scope_parent_path: tuple[str, ...] | None = None

    def scope_queryset(self, qs):
        user = self.request.user
        if user.is_admin:
            return qs
        if user.is_zev_owner:
            return qs.filter(**{self.zev_owner_filter: user})
        if self.participant_filter is None:
            return qs.none()
        qs = qs.filter(**{self.participant_filter: user})
        if self.participant_distinct:
            qs = qs.distinct()
        return qs

    # ── Write scoping ─────────────────────────────────────────────────────

    def resolve_scope_zev(self, validated_data):
        """The ZEV a written object would belong to, or ``None`` if not determinable.

        ``None`` means the payload does not name the parent — a PATCH that
        leaves the relation alone, say — so there is no move to check.
        """
        if not self.scope_parent_path:
            return None
        key, *rest = self.scope_parent_path
        target = validated_data.get(key)
        for attribute in rest:
            if target is None:
                return None
            target = getattr(target, attribute, None)
        return target

    def assert_within_scope(self, validated_data):
        """Refuse a write that would land the object in someone else's ZEV.

        Raised as a field validation error rather than a permission denial so
        it reads like the rest of DRF's related-field errors, and so the
        response says which field was wrong without describing the ZEV behind
        it.
        """
        target_zev = self.resolve_scope_zev(validated_data)
        if target_zev is None:
            return
        user = self.request.user
        if user.is_admin or target_zev.owner_id == user.pk:
            return
        field = self.scope_parent_path[0]
        raise serializers.ValidationError(
            {field: ["You do not have access to the ZEV this would belong to."]}
        )

    def perform_create(self, serializer):
        self.assert_within_scope(serializer.validated_data)
        super().perform_create(serializer)
        return serializer.instance

    def perform_update(self, serializer):
        self.assert_within_scope(serializer.validated_data)
        super().perform_update(serializer)
        return serializer.instance
