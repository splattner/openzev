from django.conf import settings
from django.db import migrations, models


def backfill_redirect_urls(apps, schema_editor):
    OAuthProvider = apps.get_model("accounts", "OAuthProvider")
    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173").rstrip("/")
    for provider in OAuthProvider.objects.all().only("id", "name"):
        provider.redirect_url = f"{frontend_url}/api/v1/auth/oauth/callback/{provider.name}/"
        provider.save(update_fields=["redirect_url"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_oauth_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthprovider",
            name="redirect_url",
            field=models.URLField(
                blank=True,
                help_text="Redirect/callback URL registered in the provider app.",
                max_length=500,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_redirect_urls, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="oauthprovider",
            name="redirect_url",
            field=models.URLField(
                help_text="Redirect/callback URL registered in the provider app.",
                max_length=500,
            ),
        ),
    ]
