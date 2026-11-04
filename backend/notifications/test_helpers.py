"""Shared fixtures for the notification tests."""

from datetime import date

from accounts.models import UserRole
from testing.factories import MeteringPointAssignmentFactory, MeteringPointFactory
from testing.helpers import create_managed_zev, make_user
from zev.models import Participant


class Community:
    """A ZEV with a manager, one participant with a login and one without, and a metering point."""

    def __init__(self, tag="a"):
        self.manager = make_user(f"mgr_{tag}", UserRole.USER)
        self.zev = create_managed_zev(name=f"Notif ZEV {tag}", owner=self.manager, invoice_prefix=tag.upper())
        self.login = make_user(f"part_{tag}", UserRole.USER)
        self.participant = Participant.objects.create(
            zev=self.zev, user=self.login, first_name="Jane", last_name="Doe",
            email=f"jane_{tag}@example.com", valid_from=date(2026, 1, 1),
        )
        self.no_login = Participant.objects.create(
            zev=self.zev, first_name="No", last_name="Login",
            email=f"nologin_{tag}@example.com", valid_from=date(2026, 1, 1),
        )
        self.metering_point = MeteringPointFactory(zev=self.zev)
        self.assignment = MeteringPointAssignmentFactory(
            metering_point=self.metering_point, participant=self.participant, valid_from=date(2026, 1, 1)
        )
