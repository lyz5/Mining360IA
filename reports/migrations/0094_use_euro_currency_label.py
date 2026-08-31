from django.db import migrations, models


def use_euro_label(apps, schema_editor):
    BusinessPerformanceConfig = apps.get_model("reports", "BusinessPerformanceConfig")
    BusinessPerformanceConfig.objects.filter(default_currency__iexact="EUR").update(
        default_currency="EURO"
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0093_configure_globalca_sales_dimensions")]

    operations = [
        migrations.AlterField(
            model_name="businessperformanceconfig",
            name="default_currency",
            field=models.CharField(default="EURO", max_length=16),
        ),
        migrations.RunPython(use_euro_label, migrations.RunPython.noop),
    ]
