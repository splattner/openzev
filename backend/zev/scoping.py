"""
Shared scoping for ZEV-related viewsets: what an account may see and change.

Access is per ZEV (ADR 0027, SPEC-2026-10-zev-access-grants §6.1), and an
account gets the union of everything it holds:

- **admin** — sees and may change everything;
- **manager / viewer grant** — sees every row of that ZEV; only a manager may
  change them;
- **participant link** — sees the rows reached through their own participant
  record (nothing, for resources such as tariffs), while that record is current;
  invoices once sent stay visible after it ends.

An account with one relationship sees exactly what the old role-based rule gave
it (``zev/test_access_regression.py`` pins that). Centralizing the rule keeps
the tenant-isolation logic auditable in one place, and every decision about a
grant is made by ``zev.access``.

Reads and writes are scoped here together on purpose. Scoping only the
queryset protects what a caller can *see* while leaving what they can *write*
open: DRF consults ``has_object_permission`` for detail routes but never on
create, so a payload naming another community's ZEV was accepted (#424). The
write rule is the mirror of the read rule — you may only create or move an
object into a ZEV you manage — and for unsafe methods the queryset itself
narrows to managed ZEVs, so a write a viewer or participant reaches through any
detail route, custom actions included, resolves to 404 before view code runs.
"""

import uuid

from django.db.models import Q
from rest_framework import serializers
from rest_framework.permissions import SAFE_METHODS

from . import access


class ZevScopedQuerySetMixin:
    """Mixin for DRF viewsets that scopes reads and writes by ZEV relationship.

    Class attributes:

    - ``zev_lookup``: ORM path from the model to its ``Zev``, e.g.
      ``"metering_point__zev"``; ``""`` for the ZEV viewset, whose model *is*
      the ZEV.
    - ``participant_path``: ORM path from the model to the ``Participant`` it
      belongs to, e.g. ``"participant"`` or ``"assignments__participant"``;
      ``""`` when the model is ``Participant``. ``None`` means a participant
      link reveals nothing (manager-only resource).
    - ``participant_distinct``: set to ``True`` when the participant path
      traverses a to-many relation and may produce duplicate rows.
    - ``participant_visible``: an optional ``Q`` a row must also match to be
      visible through a participant link, for rows a participant may only see
      once they reach a given state (an invoice once it is sent). Grants and
      admins are not narrowed by it.
    - ``participant_access_survives_end``: ``True`` when a participant keeps
      seeing these rows after their participant record has ended (sent
      invoices). Otherwise only current records count.
    - ``viewer_allowed_actions``: action names that use an unsafe method but
      only read (a ZIP of PDFs), so a viewer may call them.
    - ``scope_parent_path``: attribute chain from a write payload to the ZEV
      the object would belong to. The first element is the key in
      ``validated_data``; any further elements walk from that object to its
      ``Zev``. ``("zev",)`` means the payload carries the ZEV itself;
      ``("metering_point", "zev")`` means it carries a metering point whose
      ``.zev`` is the one that matters. ``None`` disables the write check.
    """

    zev_lookup: str
    participant_path: str | None = None
    participant_distinct: bool = False
    participant_visible: Q | None = None
    participant_access_survives_end: bool = False
    viewer_allowed_actions: frozenset[str] = frozenset()
    scope_parent_path: tuple[str, ...] | None = None

    def scope_queryset(self, qs):
        """Everything a caller is allowed to see, narrowed by ``?zev_id=``.

        Both are applied here because every ZEV-scoped viewset already funnels
        its ``get_queryset`` through this method. Leaving the parameter to each
        viewset is how it came to be accepted and silently ignored on six of
        them (#411).

        The filter cannot widen what a caller sees: it only ever adds a
        conjunctive ``filter()`` to the relation-scoped queryset, so naming
        somebody else's ZEV yields an empty list rather than their data.
        """
        return self._narrow_by_zev_id(self._scope_by_relation(qs))

    def is_write_request(self) -> bool:
        """An unsafe method that is not one of the read-only exceptions."""
        if self.request.method in SAFE_METHODS:
            return False
        return getattr(self, "action", None) not in self.viewer_allowed_actions

    def _scope_by_relation(self, qs):
        user = self.request.user
        if user.is_admin:
            return qs
        if self.is_write_request():
            # Only a manager writes. A disabled ZEV stays in this set on
            # purpose: has_object_permission and assert_target_not_disabled
            # refuse the write with their own message.
            return self._filter_distinct(qs, self._zev_in(access.managed_zev_ids(user)))
        # Deliberately not excluding a disabled ZEV from the grant branch: its
        # managers and viewers keep read-only visibility of it. Only the
        # participant branch makes a disabled ZEV disappear entirely — see
        # _not_disabled_q.
        condition = self._zev_in(access.viewable_zev_ids(user))
        participant = self._participant_q(user)
        if participant is not None:
            condition |= participant
        return self._filter_distinct(qs, condition)

    def _filter_distinct(self, qs, condition):
        qs = qs.filter(condition)
        return qs.distinct() if self.participant_distinct else qs

    def _zev_in(self, zev_ids) -> Q:
        return Q(**{f"{self.zev_lookup}__in" if self.zev_lookup else "pk__in": zev_ids})

    def _participant_prefix(self) -> str:
        return f"{self.participant_path}__" if self.participant_path else ""

    def _participant_q(self, user):
        """Rows reached through the caller's own participant records, or ``None``."""
        if self.participant_path is None:
            return None
        prefix = self._participant_prefix()
        condition = Q(**{f"{prefix}user": user}) & self._not_disabled_q()
        if not self.participant_access_survives_end:
            condition &= access.live_participant_q(prefix)
        if self.participant_visible is not None:
            condition &= self.participant_visible
        return condition

    def _not_disabled_q(self) -> Q:
        """Rows whose ZEV is not disabled.

        Only ever part of the participant branch: a disabled ZEV is not merely
        read-only to a participant the way it is to its managers, it is
        invisible — the same as a ZEV they were never part of.
        """
        lookup = f"{self.zev_lookup}__disabled_at" if self.zev_lookup else "disabled_at"
        return Q(**{f"{lookup}__isnull": True})

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
        if not access.can_manage(user, target_zev):
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
