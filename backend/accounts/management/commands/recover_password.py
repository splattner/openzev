"""Set an independent password and retire existing sessions after operator verification."""

from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from accounts.passwords import recover_password
from audit.models import AuditActionCategory, AuditEventSource
from audit.services import record_audit_event


class Command(BaseCommand):
    help = "Recover an account with an independent password and sign out existing sessions."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError("Unknown username.") from None
        password = getpass(f"New password for {user.username}: ")
        if not password or password != getpass("New password (again): "):
            raise CommandError("Passwords must be nonempty and match.")
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        with transaction.atomic():
            user = recover_password(user, password)
            record_audit_event(
                action_category=AuditActionCategory.AUTH, action_type="auth.password.recovered",
                target_type="accounts.User", target=user, target_id=str(user.pk),
                summary="Operator set an independent password and revoked sessions.",
                source=AuditEventSource.MANAGEMENT_COMMAND,
            )
        self.stdout.write(self.style.SUCCESS("Password updated; existing sessions revoked."))
