from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0012_databrowser_display_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="databrowser",
            name="show_browser_record_id",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="databrowser",
            name="show_eventchain_id",
            field=models.BooleanField(default=True),
        ),
    ]
