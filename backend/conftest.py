"""Project-wide pytest fixtures.

These fixtures wrap the factories in :mod:`testing.factories` and the auth
helpers in :mod:`testing.helpers` so pytest-style tests can request a ready-made
object graph or an authenticated client without hand-writing ``setUp`` blocks.

Existing ``django.test.TestCase`` classes continue to work unchanged; these
fixtures are additive and only apply to pytest-style test functions.
"""

from __future__ import annotations

import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from testing import factories
from testing.helpers import authenticate


@pytest.fixture(autouse=True, scope="session")
def _isolated_media(tmp_path_factory):
    """Redirect MEDIA_ROOT to a temporary directory for the entire test run.

    Prevents tests that call ``FileField.save()`` from writing into the
    project's ``media/`` directory.  The directory is removed after all tests
    finish.  ``override_settings`` (rather than direct assignment) fires the
    ``setting_changed`` signal so cached storage locations are reset.
    """
    tmp = tmp_path_factory.mktemp("media")
    with override_settings(MEDIA_ROOT=str(tmp)):
        yield


@pytest.fixture(autouse=True)
def _no_broker_calls(monkeypatch):
    """Keep ``.delay()`` from reaching a real broker.

    There is no Redis in CI, so a view that queues work would otherwise spend
    the connection retry budget before failing — minutes of test time, and a
    failure that says nothing about the code under test. Tests that care
    whether something was queued patch the task themselves, and that patch
    nests inside this one.
    """
    from invoices.tasks import generate_invoice_pdf_task

    monkeypatch.setattr(generate_invoice_pdf_task, "delay", lambda *args, **kwargs: None)


@pytest.fixture
def api_client() -> APIClient:
    """An unauthenticated DRF test client."""
    return APIClient()


@pytest.fixture
def admin_user(db):
    return factories.AdminFactory()


@pytest.fixture
def owner_user(db):
    return factories.OwnerFactory()


@pytest.fixture
def participant_user(db):
    return factories.ParticipantUserFactory()


@pytest.fixture
def zev(db, owner_user):
    return factories.ZevFactory(owner=owner_user)


@pytest.fixture
def participant(db, zev):
    return factories.ParticipantFactory(zev=zev)


@pytest.fixture
def admin_client(db, admin_user) -> APIClient:
    client = APIClient()
    authenticate(client, admin_user)
    return client


@pytest.fixture
def owner_client(db, owner_user) -> APIClient:
    client = APIClient()
    authenticate(client, owner_user)
    return client


@pytest.fixture
def participant_client(db, participant_user) -> APIClient:
    client = APIClient()
    authenticate(client, participant_user)
    return client
