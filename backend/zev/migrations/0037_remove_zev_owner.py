"""Remove ``Zev.owner`` (#761, ADR 0028).

Each job the column did has moved: access to manager grants (``ZevAccessGrant``,
phase 1 gave every owner one), the issuer of documents to the dated issuer role
(``zev.0036``). The column is made nullable first so the migration reverses: going
back fills it with the ZEV's earliest current manager (else its last one).
"""

from django.conf import settings
from django.db import migrations, models


def owner_from_managers(apps, schema_editor):
    Zev = apps.get_model("zev", "Zev")
    ZevAccessGrant = apps.get_model("zev", "ZevAccessGrant")
    for zev in Zev.objects.all().iterator():
        managers = ZevAccessGrant.objects.filter(zev=zev, role="manager").order_by("valid_from", "id")
        grant = managers.filter(valid_to__isnull=True).first() or managers.last()
        if grant is not None:
            Zev.objects.filter(pk=zev.pk).update(owner_id=grant.user_id)


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0036_party_roles_from_owner"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="zev",
            name="owner",
            field=models.ForeignKey(
                null=True, on_delete=models.PROTECT, related_name="owned_zevs", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, owner_from_managers),
        migrations.RemoveField(model_name="zev", name="owner"),
    ]
