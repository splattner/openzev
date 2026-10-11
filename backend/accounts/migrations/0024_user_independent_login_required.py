from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0023_featureflag_follows_default")]
    operations = [
        migrations.AddField(
            model_name="user",
            name="independent_login_required",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
