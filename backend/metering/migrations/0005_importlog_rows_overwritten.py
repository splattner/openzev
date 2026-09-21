import re

from django.db import migrations, models


def backfill_overwrites(apps, schema_editor):
    ImportLog = apps.get_model("metering", "ImportLog")
    logs = ImportLog.objects.using(schema_editor.connection.alias)
    # Before warnings were introduced, overwrite notes lived in errors.
    for log in logs.iterator():
        count = 0
        for entry in [*(log.errors or []), *(log.warnings or [])]:
            if not isinstance(entry, dict):
                continue
            note = entry.get("warning") or entry.get("error") or ""
            match = re.fullmatch(r"Overwrote (\d+) existing readings\.", str(note))
            if match:
                count = max(count, int(match[1]))
        if count:
            logs.filter(pk=log.pk).update(rows_overwritten=count)


class Migration(migrations.Migration):
    dependencies = [("metering", "0004_importlog_warnings")]

    operations = [
        migrations.AddField(
            model_name="importlog",
            name="rows_overwritten",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill_overwrites, migrations.RunPython.noop),
    ]
