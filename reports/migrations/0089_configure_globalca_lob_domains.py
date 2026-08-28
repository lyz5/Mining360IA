from django.db import migrations, models


def configure_globalca_lob(apps, schema_editor):
    BusinessPerformanceMapping = apps.get_model("reports", "BusinessPerformanceMapping")
    BusinessPerformanceMapping.objects.update_or_create(
        logical_name="lob",
        defaults={
            "display_name": "LOB",
            "category": "filter",
            "object_type": "column",
            "table_name": "GlobalCA",
            "object_name": "LOB",
            "data_type": "text",
            "description": "Validated Sales-domain discriminator in the GlobalCA semantic table.",
            "is_required": True,
            "is_visible": True,
            "display_order": 40,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0088_map_global_sales_ytd_measure")]

    operations = [
        migrations.AddField(
            model_name="businessperformanceconfig",
            name="parts_lob_values",
            field=models.CharField(blank=True, default="PARTS", max_length=500),
        ),
        migrations.AddField(
            model_name="businessperformanceconfig",
            name="machine_lob_values",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="businessperformanceconfig",
            name="services_lob_values",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.RunPython(configure_globalca_lob, migrations.RunPython.noop),
    ]
