import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0026_merge_duplicate_account_emails")]
    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                condition=models.Q(("email", ""), _negated=True),
                name="accounts_user_email_unique_ci",
                violation_error_message="An account with this email address already exists.",
            ),
        ),
    ]
