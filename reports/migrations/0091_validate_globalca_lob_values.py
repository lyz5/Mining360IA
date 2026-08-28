from django.db import migrations, models


def validate_lob_values(apps, schema_editor):
    BusinessPerformanceConfig = apps.get_model("reports", "BusinessPerformanceConfig")
    validated = {
        "parts_lob_values": "PARTS",
        "machine_lob_values": "PRIME",
        "services_lob_values": "SERVICE",
        "rental_lob_values": "RENTAL",
    }
    for field_name, value in validated.items():
        BusinessPerformanceConfig.objects.filter(**{field_name: ""}).update(**{field_name: value})


class Migration(migrations.Migration):
    dependencies = [("reports", "0090_add_rental_sales_domain")]

    operations = [
        migrations.AlterField(
            model_name="businessperformanceconfig",
            name="machine_lob_values",
            field=models.CharField(blank=True, default="PRIME", max_length=500),
        ),
        migrations.AlterField(
            model_name="businessperformanceconfig",
            name="services_lob_values",
            field=models.CharField(blank=True, default="SERVICE", max_length=500),
        ),
        migrations.AlterField(
            model_name="businessperformanceconfig",
            name="rental_lob_values",
            field=models.CharField(blank=True, default="RENTAL", max_length=500),
        ),
        migrations.RunPython(validate_lob_values, migrations.RunPython.noop),
    ]
