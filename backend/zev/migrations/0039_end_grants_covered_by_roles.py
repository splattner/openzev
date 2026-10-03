"""End manager grants that only repeat what a role already gives (#761).

Creating a ZEV used to give the creator a manager grant *and* make their party
the issuer, so People & access listed them twice. The issuer and representative
manage through their role (ADR 0028, amended); an open manager grant held by an
account of a party with an open-ended managing role that applies today is ended
yesterday, the way revoking does (one that only starts today or later is
deleted). The ended rows stay as history; nothing is restored on reverse.
"""

from datetime import timedelta

from django.db import migrations
from django.utils import timezone

MANAGING_ROLES = ("issuer", "representative")


def end_covered_grants(apps, schema_editor):
    ZevPartyRole = apps.get_model("zev", "ZevPartyRole")
    Participant = apps.get_model("zev", "Participant")
    ZevAccessGrant = apps.get_model("zev", "ZevAccessGrant")
    today = timezone.localdate()
    roles = ZevPartyRole.objects.filter(
        role__in=MANAGING_ROLES, valid_from__lte=today, valid_to__isnull=True,
    ).select_related("party")
    for row in roles:
        accounts = set(
            Participant.objects.filter(party_id=row.party_id).exclude(user=None).values_list("user_id", flat=True)
        )
        if row.party.user_id is not None:
            accounts.add(row.party.user_id)
        grants = ZevAccessGrant.objects.filter(
            zev_id=row.zev_id, user_id__in=accounts, role="manager", valid_to__isnull=True,
        )
        for grant in grants:
            if grant.valid_from >= today:
                grant.delete()
            else:
                grant.valid_to = today - timedelta(days=1)
                grant.save(update_fields=["valid_to", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0038_party_user"),
    ]

    operations = [
        migrations.RunPython(end_covered_grants, migrations.RunPython.noop),
    ]
