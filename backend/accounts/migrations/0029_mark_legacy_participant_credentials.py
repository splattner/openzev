from django.db import migrations, models


def mark_legacy_participant_credentials(apps, schema_editor):
    """Unknown credential origins cannot establish ownership for a future promotion."""
    database = schema_editor.connection.alias
    User = apps.get_model("accounts", "User")
    Participant = apps.get_model("zev", "Participant")
    participants = Participant.objects.using(database)
    users = User.objects.using(database).filter(independent_login_required=False).filter(
        models.Q(pk__in=participants.values("user_id"))
        | models.Q(pk__in=participants.values("party__user_id"))
    )
    user_ids = users.values("pk")
    users.update(password_from_participant_link=True, session_version=models.F("session_version") + 1)
    apps.get_model("accounts", "OAuthExchangeCode").objects.using(database).filter(user_id__in=user_ids).delete()
    for model_name in ("TotpDevice", "WebAuthnCredential", "MfaRecoveryCode"):
        apps.get_model("accounts", model_name).objects.using(database).filter(user_id__in=user_ids).update(
            from_participant_link=True,
        )
    # Legacy linking requests cannot prove which session authorized them.
    apps.get_model("accounts", "OAuthState").objects.using(database).filter(user_id__isnull=False).delete()
    social_accounts = apps.get_model("accounts", "SocialAccount").objects.using(database)
    unproven = []
    for social in social_accounts.filter(
        user_id__in=user_ids,
    ).select_related("user").iterator(chunk_size=1000):
        claims = social.extra_data if isinstance(social.extra_data, dict) else {}
        email = claims.get("email")
        if (
            claims.get("email_verified") is not True or not isinstance(email, str)
            or not email.strip() or email.strip().casefold() != social.user.email.strip().casefold()
        ):
            unproven.append(social.pk)
            if len(unproven) == 1000:
                social_accounts.filter(pk__in=unproven).update(from_participant_link=True)
                unproven.clear()
    if unproven:
        social_accounts.filter(pk__in=unproven).update(from_participant_link=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0028_participant_link_provenance"),
        ("zev", "0038_party_user"),
    ]
    operations = [
        migrations.RunPython(mark_legacy_participant_credentials, migrations.RunPython.noop),
    ]
