from django.test import TestCase

from .models import AIConfigSection, AIMetricMapping, KnowledgeKPIDictionary
from .semantic_dictionary import get_primary_measure


class MetricMeasureSynchronizationTests(TestCase):
    def setUp(self):
        self.section, _ = AIConfigSection.objects.get_or_create(
            code="performance",
            defaults={
                "name": "Performance",
                "description": "Performance configuration.",
                "is_active": True,
            },
        )
        self.metric, _ = AIMetricMapping.objects.update_or_create(
            section=self.section,
            metric_code="availability",
            defaults={
                "metric_label": "Physical Availability",
                "powerbi_measure_name": "[Availability New]",
                "is_active": True,
            },
        )
        self.kpi, _ = KnowledgeKPIDictionary.objects.update_or_create(
            section=self.section,
            kpi_code="availability",
            defaults={
                "kpi_name": "Physical Availability",
                "business_definition": "Equipment availability.",
                "formula_description": "Validated semantic-model measure.",
                "powerbi_measure_name": "[Availability New]",
                "unit": "%",
                "aggregation_rule": "Semantic measure",
                "default_time_grain": "Month",
                "validation_status": "Validated",
                "is_active": True,
            },
        )

    def test_metric_mapping_is_the_legacy_builder_source_of_truth(self):
        self.metric.powerbi_measure_name = "[Avail Per Equip]"
        self.metric.save()

        self.assertEqual(
            get_primary_measure("FPR Global DB + RLS", "availability"),
            "Avail Per Equip",
        )

    def test_metric_update_synchronizes_kpi_dictionary(self):
        self.metric.powerbi_measure_name = "[Avail Per Equip]"
        self.metric.save()

        self.kpi.refresh_from_db()
        self.assertEqual(self.kpi.powerbi_measure_name, "[Avail Per Equip]")
