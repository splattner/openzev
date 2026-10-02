from django.db import migrations, models


def collapse(apps, schema_editor):
    """#761: the platform role is admin or not. Access to a ZEV now comes from
    grants and participant links, so every other role becomes ``user``."""
    User = apps.get_model("accounts", "User")
    User.objects.exclude(role="admin").update(role="user")


def expand(apps, schema_editor):
    """Best-effort reverse: a manager grant → ``zev_owner``, a participant
    link → ``participant``, anything else → ``guest``."""
    User = apps.get_model("accounts", "User")
    ZevAccessGrant = apps.get_model("zev", "ZevAccessGrant")
    Participant = apps.get_model("zev", "Participant")
    managers = ZevAccessGrant.objects.filter(role="manager", valid_to__isnull=True).values("user_id")
    participants = Participant.objects.filter(user__isnull=False).values("user_id")
    users = User.objects.filter(role="user")
    users.filter(pk__in=managers).update(role="zev_owner")
    users.filter(pk__in=participants).update(role="participant")
    users.update(role="guest")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0020_access_grants_accounts"),
        ("zev", "0031_zev_access_grant"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[("admin", "Admin"), ("user", "User"), ("zev_owner", "ZEV Owner"), ("participant", "Participant"), ("guest", "Guest")],
                default="user",
                max_length=20,
            ),
        ),
        migrations.RunPython(collapse, expand),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(choices=[("admin", "Admin"), ("user", "User")], default="user", max_length=20),
        ),
    ]
