from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('zev', '0004_zev_start_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='title',
            field=models.CharField(blank=True, choices=[('mr', 'Mr.'), ('mrs', 'Mrs.'), ('ms', 'Ms.'), ('dr', 'Dr.'), ('prof', 'Prof.')], max_length=10),
        ),
        migrations.RemoveField(
            model_name='participant',
            name='unit_identifier',
        ),
    ]
