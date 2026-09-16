from django.db import migrations


NEW_MEASURE = "[Avail Per Equip]"
PREVIOUS_MEASURE = "[Availability New]"


def use_per_equipment_measure(apps, schema_editor):
    section = apps.get_model("reports", "AIConfigSection").objects.filter(code="performance").first()
    if not section:
        return
    apps.get_model("reports", "AIMetricMapping").objects.filter(
        section=section,
        metric_code="availability",
    ).update(
        metric_label="Availability Per Equip",
        powerbi_measure_name=NEW_MEASURE,
    )
    apps.get_model("reports", "KnowledgeKPIDictionary").objects.filter(
        section=section,
        kpi_code="availability",
    ).update(
        kpi_name="Availability Per Equip",
        powerbi_measure_name=NEW_MEASURE,
        powerbi_measure_full_reference=f"'DowntimeData_MiningProd'{NEW_MEASURE}",
    )


def restore_previous_measure(apps, schema_editor):
    section = apps.get_model("reports", "AIConfigSection").objects.filter(code="performance").first()
    if not section:
        return
    apps.get_model("reports", "AIMetricMapping").objects.filter(
        section=section,
        metric_code="availability",
    ).update(
        metric_label="Physical Availability",
        powerbi_measure_name=PREVIOUS_MEASURE,
    )
    apps.get_model("reports", "KnowledgeKPIDictionary").objects.filter(
        section=section,
        kpi_code="availability",
    ).update(
        kpi_name="Physical Availability",
        powerbi_measure_name=PREVIOUS_MEASURE,
        powerbi_measure_full_reference=f"'DowntimeData_MiningProd'{PREVIOUS_MEASURE}",
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0141_parts_sales_brand_classification")]
    operations = [migrations.RunPython(use_per_equipment_measure, restore_previous_measure)]
