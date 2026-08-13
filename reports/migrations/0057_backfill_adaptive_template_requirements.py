from django.db import migrations


REQUIRED_DATA = {
    "single_kpi": ["metric_value"],
    "entity_comparison": ["multiple_rows"],
    "period_comparison": ["multiple_rows"],
    "trend_analysis": ["multiple_rows"],
    "ranking": ["rows"],
    "downtime_drivers": ["downtime_drivers"],
    "equipment_detail": ["equipment_identity"],
}


def backfill_requirements(apps, schema_editor):
    Template = apps.get_model("reports", "AIResponseTemplate")
    for code, fields in REQUIRED_DATA.items():
        Template.objects.filter(code=code).update(required_data_fields_json=fields)


def clear_requirements(apps, schema_editor):
    Template = apps.get_model("reports", "AIResponseTemplate")
    Template.objects.filter(code__in=REQUIRED_DATA).update(required_data_fields_json=[])


class Migration(migrations.Migration):
    dependencies = [("reports", "0056_adaptive_performance_responses")]
    operations = [migrations.RunPython(backfill_requirements, clear_requirements)]
