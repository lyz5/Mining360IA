from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AIMetricMapping, KnowledgeBusinessGlossary, KnowledgeKPIDictionary


def _full_measure_reference(item: KnowledgeKPIDictionary, measure_name: str) -> str:
    table = str(item.powerbi_measure_table or "").replace("'", "''").strip()
    measure = str(measure_name or "").strip().strip("[]")
    return f"'{table}'[{measure}]" if table and measure else ""


@receiver(post_save, sender=AIMetricMapping)
def synchronize_metric_knowledge_references(sender, instance, **kwargs):
    """Keep descriptive KPI records aligned with the executable metric mapping."""
    for item in KnowledgeKPIDictionary.objects.filter(
        section=instance.section,
        kpi_code=instance.metric_code,
    ):
        item.kpi_name = instance.metric_label
        item.powerbi_measure_name = instance.powerbi_measure_name
        item.powerbi_measure_full_reference = _full_measure_reference(
            item, instance.powerbi_measure_name
        )
        item.save(update_fields=[
            "kpi_name",
            "powerbi_measure_name",
            "powerbi_measure_full_reference",
            "updated_at",
        ])

    KnowledgeBusinessGlossary.objects.filter(
        section=instance.section,
        related_kpi=instance.metric_code,
    ).update(related_powerbi_measure=instance.powerbi_measure_name)
