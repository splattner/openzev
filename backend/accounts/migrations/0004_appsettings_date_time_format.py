from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_appsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="date_time_format",
            field=models.CharField(
                choices=[
                    ("dd.MM.yyyy HH:mm", "DD.MM.YYYY HH:mm"),
                    ("dd/MM/yyyy HH:mm", "DD/MM/YYYY HH:mm"),
                    ("MM/dd/yyyy HH:mm", "MM/DD/YYYY HH:mm"),
                    ("yyyy-MM-dd HH:mm", "YYYY-MM-DD HH:mm"),
                ],
                default="dd.MM.yyyy HH:mm",
                max_length=25,
            ),
        ),
    ]