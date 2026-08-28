from django.db import migrations


def map_invoice_revenue_measures(apps, schema_editor):
    BusinessPerformanceMapping = apps.get_model("reports", "BusinessPerformanceMapping")
    measures = (
        ("global_revenue_eur", "Revenue EUR", "CA Facture EU", "EUR", 100),
        ("global_revenue_usd", "Revenue USD", "CA Facture US", "USD", 101),
        ("global_revenue_cfa", "Revenue CFA", "CA Facture XO", "XOF", 102),
    )
    for logical_name, display_name, measure_name, format_string, order in measures:
        BusinessPerformanceMapping.objects.update_or_create(
            logical_name=logical_name,
            defaults={
                "display_name": display_name,
                "category": "metric",
                "object_type": "measure",
                "table_name": "",
                "object_name": measure_name,
                "data_type": "decimal",
                "format_string": format_string,
                "description": "Official Power BI invoice revenue measure.",
                "is_required": True,
                "is_visible": True,
                "display_order": order,
                "is_active": True,
            },
        )
    BusinessPerformanceMapping.objects.filter(logical_name="global_revenue_ytd").update(
        is_active=False,
        description="Superseded for revenue display by the official invoice currency measures.",
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0091_validate_globalca_lob_values")]

    operations = [
        migrations.RunPython(map_invoice_revenue_measures, migrations.RunPython.noop),
    ]
