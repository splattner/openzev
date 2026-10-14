from django.contrib.auth.hashers import is_password_usable
from django.db import migrations, transaction
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Lower


def _is_protected(user):
    return user.is_superuser or user.role == "admin" or user.may_create_zev or user.independent_login_required


def _is_bare(apps, db, user):
    """A participant-only account: nothing of its own would be lost by merging it."""
    if _is_protected(user) or is_password_usable(user.password):
        return False
    owned = [
        apps.get_model("accounts", "SocialAccount"),
        apps.get_model("accounts", "WebAuthnCredential"),
        apps.get_model("accounts", "ApiKey"),
        apps.get_model("accounts", "TotpDevice"),
        apps.get_model("zev", "ZevAccessGrant"),
    ]
    return not any(model.objects.using(db).filter(user_id=user.pk).exists() for model in owned)


def merge_duplicate_emails(apps, schema_editor):
    """Leave every address on one account: it is the account's identifier now.

    Duplicates came mostly from the participant flow, which made one
    participant-only account per participant row. Those are folded into the
    strongest account for the address: their participant rows and parties move
    over and the empty account is deleted. An account with a login of its own
    cannot be folded away, so it loses its address instead (it can still sign
    in by username, and an admin can give it a new address).
    """
    db = schema_editor.connection.alias
    User = apps.get_model("accounts", "User")
    Participant = apps.get_model("zev", "Participant")
    Party = apps.get_model("zev", "Party")

    duplicated = (
        User.objects.using(db).exclude(email="")
        .annotate(key=Lower("email")).values("key").annotate(n=Count("pk")).filter(n__gt=1)
        .values_list("key", flat=True)
    )
    for key in list(duplicated):
        accounts = list(User.objects.using(db).annotate(key=Lower("email")).filter(key=key))
        # Strongest first: protected, then with a way to sign in, then used, active, oldest.
        accounts.sort(key=lambda user: (
            _is_protected(user), not _is_bare(apps, db, user), user.last_login is not None, user.is_active, -user.pk,
        ), reverse=True)
        keeper, losers = accounts[0], accounts[1:]
        for loser in losers:
            if _is_bare(apps, db, loser):
                try:
                    with transaction.atomic(using=db):
                        Participant.objects.using(db).filter(user_id=loser.pk).update(user_id=keeper.pk)
                        Party.objects.using(db).filter(user_id=loser.pk).update(user_id=keeper.pk)
                        loser.delete()
                    continue
                except ProtectedError:
                    pass
            print(f"\n  accounts.0026: {loser.username!r} lost the address {loser.email!r}, kept on {keeper.username!r}")
            User.objects.using(db).filter(pk=loser.pk).update(email="")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0025_backfill_independent_login_required"),
        ("zev", "0043_report_invalid_invoice_prefixes"),
    ]
    operations = [
        migrations.RunPython(merge_duplicate_emails, migrations.RunPython.noop),
    ]
