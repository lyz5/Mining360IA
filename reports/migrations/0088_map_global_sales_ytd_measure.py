from django.db import migrations


def map_global_sales_ytd(apps, schema_editor):
    BusinessPerformanceMapping = apps.get_model("reports", "BusinessPerformanceMapping")
    BusinessPerformanceMapping.objects.update_or_create(
        logical_name="global_revenue_ytd",
        defaults={
            "display_name": "Global Sales YTD",
            "category": "metric",
            "object_type": "measure",
            "table_name": "",
            "object_name": "YTD Parts Sales Dyn",
            "data_type": "decimal",
            "format_string": "currency",
            "description": (
                "Official Power BI global Sales YTD measure. A governed Sales-domain filter "
                "is required to derive Parts, Machines or Services."
            ),
            "is_required": True,
            "is_visible": True,
            "display_order": 105,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0087_prepare_globalca_sales_domains")]

    operations = [
        migrations.RunPython(map_global_sales_ytd, migrations.RunPython.noop),
    ]
