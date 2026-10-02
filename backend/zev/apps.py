from django.apps import AppConfig


class ZevConfig(AppConfig):
    name = 'zev'

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from . import access
        from .models import Participant, Party, ZevAccessGrant, ZevPartyRole

        # Access answers are memoised per user object; any change to who holds
        # a grant, a participant row, a party's account or a managing role must
        # make them stale (zev.access).
        for model in (ZevAccessGrant, Participant, Party, ZevPartyRole):
            post_save.connect(access.bump_generation, sender=model, dispatch_uid=f"zev-access-{model.__name__}-save")
            post_delete.connect(access.bump_generation, sender=model, dispatch_uid=f"zev-access-{model.__name__}-delete")
