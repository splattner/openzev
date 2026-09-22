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

import uuid

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
        """Everything a caller is allowed to see, narrowed by ``?zev_id=``.

        Both are applied here because every ZEV-scoped viewset already funnels
        its ``get_queryset`` through this method. Leaving the parameter to each
        viewset is how it came to be accepted and silently ignored on six of
        them (#411).

        The filter cannot widen what a caller sees: it only ever adds a
        conjunctive ``filter()`` to the role-scoped queryset, so naming
        somebody else's ZEV yields an empty list rather than their data.
        """
        return self._narrow_by_zev_id(self._scope_by_role(qs))

    def _scope_by_role(self, qs):
        user = self.request.user
        if user.is_admin:
            return qs
        if user.is_zev_owner:
            # Deliberately not excluding a disabled ZEV here: its owner keeps
            # read-only visibility of it (has_object_permission blocks their
            # writes; assert_within_scope blocks their creates). Only the
            # participant branch below makes a disabled ZEV disappear
            # entirely — see _exclude_disabled_zev.
            return qs.filter(**{self.zev_owner_filter: user})
        if self.participant_filter is None:
            return qs.none()
        qs = self._exclude_disabled_zev(qs.filter(**{self.participant_filter: user}))
        if self.participant_distinct:
            qs = qs.distinct()
        return qs

    def _exclude_disabled_zev(self, qs):
        """Narrow ``qs`` to rows whose ZEV is not disabled.

        Only ever applied to the participant branch of ``_scope_by_role``: a
        disabled ZEV is not merely read-only to a participant the way it is
        to its owner, it is invisible — the same as a ZEV they were never
        part of. A viewset whose participant scoping fully overrides
        ``_scope_by_role`` (``MeterReadingViewSet``, for its assignment-window
        query) calls this directly instead.
        """
        lookup = f"{self.zev_lookup}__disabled_at" if self.zev_lookup else "disabled_at"
        return qs.filter(**{f"{lookup}__isnull": True})

    @property
    def zev_lookup(self) -> str:
        """ORM path from this model to its ``Zev``, derived from the role filter.

        ``zev_owner_filter`` is by definition the path to that ZEV's ``owner``,
        so dropping the final segment yields the path to the ZEV itself:
        ``"metering_point__zev__owner"`` -> ``"metering_point__zev"``. Deriving
        it keeps the two in step — a viewset that changes its relation path
        cannot end up filtering on a stale one — and ``""`` correctly denotes
        the ZEV viewset, whose model *is* the ZEV.
        """
        head, _, _ = self.zev_owner_filter.rpartition("__")
        return head

    def _narrow_by_zev_id(self, qs):
        raw = self.request.query_params.get("zev_id")
        if not raw:
            return qs
        try:
            zev_id = uuid.UUID(str(raw))
        except (ValueError, AttributeError, TypeError):
            # Previously ignored along with the rest of the parameter, which
            # returned every ZEV the caller could see and looked like success.
            raise serializers.ValidationError(
                {"zev_id": ["Must be a valid UUID."]}
            ) from None
        lookup = f"{self.zev_lookup}__id" if self.zev_lookup else "id"
        return qs.filter(**{lookup: zev_id})

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
        """Refuse a write that would land the object in someone else's ZEV,
        or in a disabled one.

        Raised as a field validation error rather than a permission denial so
        it reads like the rest of DRF's related-field errors, and so the
        response says which field was wrong without describing the ZEV behind
        it.

        The disabled-ZEV rule has to live here too, not just in
        ``has_object_permission``: DRF never consults object permissions on
        create, which is the whole reason this write-scoping mixin exists —
        this is that check's create-time counterpart, for the same owner who
        would be refused a PATCH on an existing row in the same ZEV.
        """
        target_zev = self.resolve_scope_zev(validated_data)
        if target_zev is None:
            return
        user = self.request.user
        if user.is_admin:
            return
        field = self.scope_parent_path[0]
        if target_zev.owner_id != user.pk:
            raise serializers.ValidationError(
                {field: ["You do not have access to the ZEV this would belong to."]}
            )
        if target_zev.disabled_at is not None:
            raise serializers.ValidationError(
                {field: ["This ZEV is disabled. Ask an admin to re-enable it first."]}
            )

    def _zev_of(self, instance):
        """The ``Zev`` an existing instance currently belongs to, via
        ``zev_lookup``.

        Unlike ``resolve_scope_zev`` (which reads a *payload*, and only sees
        a ZEV when the write names it), this walks the instance already in
        the database — the ZEV a ``PATCH`` that leaves the relation alone
        still writes into, or the ZEV a ``DELETE`` removes a row from.
        """
        if not self.zev_lookup:
            return instance
        target = instance
        for attribute in self.zev_lookup.split("__"):
            if target is None:
                return None
            target = getattr(target, attribute, None)
        return target

    def assert_target_not_disabled(self, instance):
        """Refuse a write to an *existing* row under a disabled ZEV, admin
        exempt.

        The existing-row counterpart of ``assert_within_scope``'s disabled
        check: that one only fires when the payload names the ZEV relation,
        so a ``PATCH`` editing some other field of a row already sitting
        under a disabled ZEV would otherwise sail through untouched. This is
        what gives ``Tariff``/``TariffPeriod``/``MeterReading`` the
        object-level protection ``BaseZevScopedPermission.
        has_object_permission`` already gives ``Participant``/
        ``MeteringPoint``/``MeteringPointAssignment``/``Zev`` — those four
        don't use this mixin's ``perform_update``/``perform_destroy`` to get
        it, since they have that permission class instead, so this check is
        redundant-but-harmless for them. ``Invoice`` needed a separate fix
        (see ``invoices.views._deny_if_zev_disabled``): it barely uses these
        two methods at all, mutating almost entirely through custom actions.
        """
        if self.request.user.is_admin:
            return
        zev = self._zev_of(instance)
        if zev is not None and zev.disabled_at is not None:
            raise serializers.ValidationError(
                {"detail": "This ZEV is disabled. Ask an admin to re-enable it first."}
            )

    def perform_create(self, serializer):
        self.assert_within_scope(serializer.validated_data)
        super().perform_create(serializer)
        return serializer.instance

    def perform_update(self, serializer):
        self.assert_within_scope(serializer.validated_data)
        self.assert_target_not_disabled(serializer.instance)
        super().perform_update(serializer)
        return serializer.instance

    def perform_destroy(self, instance):
        self.assert_target_not_disabled(instance)
        super().perform_destroy(instance)
