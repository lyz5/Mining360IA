from django.db import migrations


def configure_downtime_diagnostics(apps, schema_editor):
    Section = apps.get_model("reports", "AIConfigSection")
    Metric = apps.get_model("reports", "AIMetricMapping")
    Filter = apps.get_model("reports", "AIFilterMapping")

    section = Section.objects.filter(code="performance").first()
    if not section:
        return
    Metric.objects.update_or_create(
        section=section,
        metric_code="downtime_hours",
        defaults={
            "metric_label": "Downtime Hours",
            "powerbi_measure_name": "[DonwtimeHours]",
            "description": (
                "Validated semantic measure used to explain Availability "
                "through total downtime hours."
            ),
            "is_active": True,
        },
    )
    Filter.objects.update_or_create(
        section=section,
        filter_code="downtime_driver",
        defaults={
            "filter_label": "Downtime Driver",
            "powerbi_table_name": "DowntimeData_MiningProd",
            "powerbi_column_name": "DescriptionCat",
            "data_type": "Text",
            "is_required": False,
            "is_active": True,
        },
    )


def remove_downtime_diagnostics(apps, schema_editor):
    Metric = apps.get_model("reports", "AIMetricMapping")
    Filter = apps.get_model("reports", "AIFilterMapping")
    Metric.objects.filter(
        section__code="performance",
        metric_code="downtime_hours",
    ).delete()
    Filter.objects.filter(
        section__code="performance",
        filter_code="downtime_driver",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0031_add_cbg_resolution_aliases"),
    ]

    operations = [
        migrations.RunPython(
            configure_downtime_diagnostics,
            remove_downtime_diagnostics,
        ),
    ]
