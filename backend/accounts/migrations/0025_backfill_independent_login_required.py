from django.db import migrations, models


def protect_existing_accounts(apps, schema_editor):
    """Record existing independent access without retiring credentials on upgrade."""
    database = schema_editor.connection.alias
    User = apps.get_model("accounts", "User")
    ZevAccessGrant = apps.get_model("zev", "ZevAccessGrant")
    ZevPartyRole = apps.get_model("zev", "ZevPartyRole")
    Party = apps.get_model("zev", "Party")
    Participant = apps.get_model("zev", "Participant")
    managing_parties = ZevPartyRole.objects.using(database).filter(
        role__in=["issuer", "representative"],
    ).values("party_id")
    User.objects.using(database).filter(
        models.Q(role="admin")
        | models.Q(is_superuser=True)
        | models.Q(may_create_zev=True)
        | models.Q(pk__in=ZevAccessGrant.objects.using(database).values("user_id"))
        | models.Q(pk__in=Party.objects.using(database).filter(pk__in=managing_parties).values("user_id"))
        | models.Q(pk__in=Participant.objects.using(database).filter(party_id__in=managing_parties).values("user_id"))
    ).update(independent_login_required=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0024_user_independent_login_required"),
        ("zev", "0038_party_user"),
    ]
    operations = [
        migrations.RunPython(protect_existing_accounts, migrations.RunPython.noop),
    ]
