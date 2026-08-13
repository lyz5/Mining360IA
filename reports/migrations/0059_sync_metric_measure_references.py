from django.db import migrations


def synchronize_measure_references(apps, schema_editor):
    AIMetricMapping = apps.get_model("reports", "AIMetricMapping")
    KnowledgeBusinessGlossary = apps.get_model("reports", "KnowledgeBusinessGlossary")
    KnowledgeKPIDictionary = apps.get_model("reports", "KnowledgeKPIDictionary")

    for metric in AIMetricMapping.objects.filter(is_active=True):
        for item in KnowledgeKPIDictionary.objects.filter(
            section_id=metric.section_id,
            kpi_code=metric.metric_code,
        ):
            measure = str(metric.powerbi_measure_name or "").strip()
            table = str(item.powerbi_measure_table or "").replace("'", "''").strip()
            unqualified = measure.strip("[]")
            KnowledgeKPIDictionary.objects.filter(pk=item.pk).update(
                kpi_name=metric.metric_label,
                powerbi_measure_name=measure,
                powerbi_measure_full_reference=(
                    f"'{table}'[{unqualified}]" if table and unqualified else ""
                ),
            )
        KnowledgeBusinessGlossary.objects.filter(
            section_id=metric.section_id,
            related_kpi=metric.metric_code,
        ).update(related_powerbi_measure=metric.powerbi_measure_name)


class Migration(migrations.Migration):
    dependencies = [("reports", "0058_powerbi_user_owned_embedding")]

    operations = [
        migrations.RunPython(synchronize_measure_references, migrations.RunPython.noop),
    ]
