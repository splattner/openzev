from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_must_change_password"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_enforcer", models.BooleanField(default=True, editable=False, unique=True)),
                (
                    "date_format_short",
                    models.CharField(
                        choices=[
                            ("dd.MM.yyyy", "DD.MM.YYYY"),
                            ("dd/MM/yyyy", "DD/MM/YYYY"),
                            ("MM/dd/yyyy", "MM/DD/YYYY"),
                            ("yyyy-MM-dd", "YYYY-MM-DD"),
                        ],
                        default="dd.MM.yyyy",
                        max_length=20,
                    ),
                ),
                (
                    "date_format_long",
                    models.CharField(
                        choices=[
                            ("d MMMM yyyy", "D MMMM YYYY"),
                            ("d. MMMM yyyy", "D. MMMM YYYY"),
                            ("MMMM d, yyyy", "MMMM D, YYYY"),
                            ("yyyy-MM-dd", "YYYY-MM-DD"),
                        ],
                        default="d MMMM yyyy",
                        max_length=20,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]