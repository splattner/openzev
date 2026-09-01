"""Every paginated list must have a total order.

DRF's ``PageNumberPagination`` is ``LIMIT``/``OFFSET``, and page 1 and page 2
are separate queries. Postgres gives no guarantee about the relative order of
rows that tie on the ``ORDER BY`` key across separate queries, so a tie
straddling a page boundary can come back on both pages or on neither.

That was latent while only the first page was ever fetched. Now that the
frontend walks the whole chain (``fetchAllPages``), "the complete set" can
quietly be missing a row — see #489.

The fix is a unique trailing sort key. These tests pin it in both places it
can be lost: the model's ``Meta.ordering``, and any ``.order_by()`` in a view,
which replaces ``Meta.ordering`` outright rather than extending it.
"""

from django.apps import apps
from django.test import TestCase

# Apps whose models we do not own; their ordering is not ours to change.
THIRD_PARTY_APP_LABELS = {
    "admin",
    "auth",
    "contenttypes",
    "sessions",
    "django_celery_beat",
    "django_celery_results",
    "token_blacklist",
}


def _is_total_order(model, ordering) -> bool:
    """True when *ordering* can never tie, i.e. it reaches a unique column."""
    for field_name in (entry.lstrip("-") for entry in ordering):
        if field_name in ("pk", model._meta.pk.name):
            return True
        try:
            field = model._meta.get_field(field_name)
        except Exception:  # noqa: BLE001 - related lookups like "provider__name"
            continue
        if getattr(field, "unique", False):
            return True
    return False


class ModelOrderingIsTotalTests(TestCase):
    def test_every_model_ordering_reaches_a_unique_column(self):
        offenders = []
        for model in apps.get_models():
            if model._meta.app_label in THIRD_PARTY_APP_LABELS:
                continue
            ordering = list(model._meta.ordering or [])
            if not ordering:
                # No Meta.ordering means no implied cross-page promise; DRF
                # warns about unordered pagination separately.
                continue
            if not _is_total_order(model, ordering):
                offenders.append(
                    f"{model._meta.app_label}.{model.__name__} ordering={ordering} "
                    "— append 'id' so paginated walks cannot drop or duplicate rows"
                )
        self.assertEqual(offenders, [])


class ViewOrderingIsTotalTests(TestCase):
    """``.order_by()`` in a view *replaces* ``Meta.ordering``.

    So a model-level tiebreaker does not protect a list view that sorts for
    itself. These are the paginated list views that do; each is driven through
    a real request so the assertion covers the queryset the view actually
    paginates, not one reconstructed here.
    """

    def _ordering_for(self, view_class, user, path):
        from rest_framework.test import APIRequestFactory, force_authenticate

        request = APIRequestFactory().get(path)
        force_authenticate(request, user=user)
        view = view_class()
        view.request = view.initialize_request(request)
        view.format_kwarg = None
        return list(view.get_queryset().query.order_by)

    def setUp(self):
        from accounts.models import User, UserRole

        self.admin = User.objects.create_user(
            username="ordering_admin", password="pass1234", role=UserRole.ADMIN
        )

    def test_vat_rate_list_orders_by_a_unique_trailing_key(self):
        from accounts.views import VatRateListCreateView

        ordering = self._ordering_for(VatRateListCreateView, self.admin, "/api/v1/auth/vat-rates/")
        self.assertEqual(ordering[-1], "id", f"ordering={ordering}")

    def test_admin_api_key_list_orders_by_a_unique_trailing_key(self):
        from accounts.views import AdminApiKeyListView

        ordering = self._ordering_for(AdminApiKeyListView, self.admin, "/api/v1/auth/admin/api-keys/")
        self.assertEqual(ordering[-1], "id", f"ordering={ordering}")

    def test_user_list_orders_by_a_unique_column(self):
        """``username`` is unique, so this one is already a total order and
        needs no trailing id — asserted so a later rename cannot silently drop
        the guarantee."""
        from accounts.models import User
        from accounts.views import UserListCreateView

        ordering = self._ordering_for(UserListCreateView, self.admin, "/api/v1/auth/users/")
        self.assertEqual(ordering, ["username"])
        self.assertTrue(User._meta.get_field("username").unique)
