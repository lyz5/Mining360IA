from django.db import migrations, models


def add_rental_mappings(apps, schema_editor):
    BusinessPerformanceMapping = apps.get_model("reports", "BusinessPerformanceMapping")
    defaults = (
        ("rental_revenue", "Rental Revenue", "decimal", 320),
        ("rental_order_count", "Rental Orders", "integer", 330),
    )
    for logical_name, display_name, data_type, display_order in defaults:
        BusinessPerformanceMapping.objects.get_or_create(
            logical_name=logical_name,
            defaults={
                "display_name": display_name,
                "category": "rental",
                "object_type": "measure",
                "table_name": "",
                "object_name": "",
                "data_type": data_type,
                "description": "GlobalCA mapping pending semantic-model validation.",
                "is_required": False,
                "is_visible": True,
                "display_order": display_order,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0089_configure_globalca_lob_domains")]

    operations = [
        migrations.AlterField(
            model_name="businessperformancemapping",
            name="category",
            field=models.CharField(
                choices=[
                    ("metric", "Metric"), ("filter", "Filter"),
                    ("customer", "Customer"), ("parts", "Parts Sales"),
                    ("prime", "Machine Sales"), ("services", "Services Sales"),
                    ("rental", "Rental Sales"), ("fleet", "Fleet"),
                ],
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="businessperformanceconfig",
            name="rental_lob_values",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.RunPython(add_rental_mappings, migrations.RunPython.noop),
    ]
