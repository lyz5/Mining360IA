from django.db import migrations, models


def initialize_browser_order(apps, schema_editor):
    DataBrowser = apps.get_model("reports", "DataBrowser")
    for position, browser in enumerate(DataBrowser.objects.order_by("name", "id"), start=1):
        browser.display_order = position
        browser.save(update_fields=["display_order"])


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0011_systemdatabaseconfig_systemmanagedtable"),
    ]

    operations = [
        migrations.AddField(
            model_name="databrowser",
            name="display_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(initialize_browser_order, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="databrowser",
            options={"ordering": ["display_order", "name"]},
        ),
    ]
