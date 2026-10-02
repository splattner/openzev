"""Make the owner's party the issuer and a landowner of each ZEV (#761).

Documents found their issuer through the owner account's participation in the
ZEV; from now on through the dated issuer role. The role starts early enough
to cover every document already dated in the ZEV — its start date, its first
participation, its first invoice period and its first issued contract — so
every invoice, contract and statement keeps naming the same issuer.

A ZEV whose owner is not a participant gets no role: its documents carry the
ZEV's name as before.
"""

from django.db import migrations
from django.db.models import Min


def to_roles(apps, schema_editor):
    Zev = apps.get_model("zev", "Zev")
    Participant = apps.get_model("zev", "Participant")
    ZevPartyRole = apps.get_model("zev", "ZevPartyRole")
    Invoice = apps.get_model("invoices", "Invoice")
    ContractIssue = apps.get_model("invoices", "ContractIssue")

    for zev in Zev.objects.exclude(owner_id=None).iterator():
        if ZevPartyRole.objects.filter(zev=zev, role="issuer").exists():
            continue
        own = (
            Participant.objects.filter(zev=zev, user_id=zev.owner_id)
            .order_by("party__sort_name", "party__first_name", "id")
            .first()
        )
        if own is None:
            continue
        starts = [
            zev.start_date,
            Participant.objects.filter(zev=zev).aggregate(day=Min("valid_from"))["day"],
            Invoice.objects.filter(zev=zev).aggregate(day=Min("period_start"))["day"],
            ContractIssue.objects.filter(zev=zev).aggregate(day=Min("rendered_on"))["day"],
        ]
        valid_from = min(day for day in starts if day is not None)
        for role in ("issuer", "landowner"):
            ZevPartyRole.objects.create(zev=zev, party_id=own.party_id, role=role, valid_from=valid_from)


def drop_roles(apps, schema_editor):
    apps.get_model("zev", "ZevPartyRole").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("zev", "0035_party_role"),
        ("invoices", "0019_invoice_issuer_recipient_copy"),
    ]

    operations = [migrations.RunPython(to_roles, drop_roles)]
