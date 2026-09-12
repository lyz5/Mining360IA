from django.db import migrations


DATASET_ID = "364edd69-532c-4e10-867f-3b3d4dfdb6c7"
WORKSPACE_ID = "a378c518-bfc4-4cd7-a49d-ba40394db80f"
REPORT_ID = "6468f0ea-a64d-44b0-8c13-78597ec44bb9"

METRICS = {
    "availability": ("Physical Availability", "[Availability New]", "DowntimeData_MiningProd", "Percentage", True, False),
    "mtbs": ("MTBS", "[MTBS Per Equip]", "OperatingTime_MiningProd", "Duration", True, False),
    "mtbf": ("MTBF", "[MTBF Per Equip]", "OperatingTime_MiningProd", "Duration", True, False),
    "mttr": ("MTTR", "[MTTR Per Equip]", "OperatingTime_MiningProd", "Duration", False, True),
    "planned_downtime_percentage": ("Planned Downtime", "[% PlannedHours DT]", "DowntimeData_MiningProd", "Percentage", False, False),
    "unplanned_downtime_percentage": ("Unplanned Downtime", "[% UnplannedHours DT]", "DowntimeData_MiningProd", "Percentage", False, True),
}

BUNDLES = {
    "fleet_performance_core": ["availability", "mtbs", "mtbf", "mttr", "planned_downtime_percentage", "unplanned_downtime_percentage"],
    "reliability_core": ["mtbs", "mtbf", "mttr"],
    "downtime_mix": ["planned_downtime_percentage", "unplanned_downtime_percentage"],
    "availability_reliability": ["availability", "mtbs", "mtbf", "mttr"],
}

RESPONSE_TEMPLATES = {
    "fleet_performance_overview": ("fleet_performance_overview", ["context", "data_coverage", "metric_grid", "key_takeaway", "contextual_actions"]),
    "reliability_overview": ("reliability_overview", ["context", "metric_grid", "trend_chart", "key_takeaway", "contextual_actions"]),
    "multi_kpi_summary": ("multi_kpi_summary", ["context", "metric_grid", "key_takeaway", "contextual_actions"]),
    "planned_unplanned_analysis": ("planned_unplanned_analysis", ["context", "metric_grid", "comparison_summary", "key_takeaway", "contextual_actions"]),
    "fleet_performance_comparison": ("entity_comparison", ["context", "comparison_table", "key_takeaway", "contextual_actions"]),
    "fleet_performance_period_comparison": ("period_comparison", ["context", "comparison_table", "key_takeaway", "contextual_actions"]),
    "fleet_performance_trend": ("trend_analysis", ["context", "trend_chart", "result_table", "key_takeaway", "contextual_actions"]),
    "fleet_performance_ranking": ("ranking", ["context", "ranking_table", "key_takeaway", "contextual_actions"]),
    "equipment_performance_detail": ("equipment_performance", ["equipment_identity", "metric_grid", "contextual_actions"]),
    "component_analysis": ("component_analysis", ["context", "result_table", "key_takeaway", "contextual_actions"]),
    "pm_analysis": ("pm_analysis", ["context", "result_table", "key_takeaway", "contextual_actions"]),
    "smu_tracking": ("smu_tracking", ["context", "result_table", "contextual_actions"]),
    "fleet_performance_benchmark": ("benchmark_analysis", ["context", "comparison_table", "key_takeaway", "contextual_actions"]),
}

DAX_TEMPLATES = (
    "PERF_SINGLE_KPI", "PERF_CORE_KPI_SUMMARY", "PERF_RELIABILITY_SUMMARY", "PERF_DOWNTIME_MIX",
    "PERF_KPI_BY_SITE", "PERF_KPI_BY_MODEL", "PERF_KPI_BY_EQUIPMENT",
    "PERF_MULTI_KPI_BY_SITE", "PERF_MULTI_KPI_BY_MODEL", "PERF_MULTI_KPI_BY_EQUIPMENT",
    "PERF_KPI_TREND", "PERF_MULTI_KPI_TREND", "PERF_PERIOD_COMPARISON", "PERF_RANKING",
    "PERF_DOWNTIME_DRIVERS", "PERF_DOWN_HOURS_BY_COMPARTMENT", "PERF_DOWN_HOURS_BY_EQUIPMENT",
    "PERF_COMPONENT_ANALYSIS", "PERF_SMU_TRACKING", "PERF_BENCHMARK",
)

SYNONYMS = {
    "availability": ("availability", "physical availability", "disponibilité", "disponibilité physique", "PA"),
    "mtbs": ("MTBS", "mean time between stoppages", "temps moyen entre arrêts"),
    "mtbf": ("MTBF", "mean time between failures", "temps moyen entre pannes"),
    "mttr": ("MTTR", "mean time to repair", "temps moyen de réparation"),
    "planned_downtime_percentage": ("planned downtime", "planned hours", "downtime planifié", "arrêts planifiés"),
    "unplanned_downtime_percentage": ("unplanned downtime", "unplanned hours", "downtime non planifié", "arrêts non planifiés"),
}

QUESTIONS = (
    ("Donne-moi la performance de Fekola YTD.", "fr", "fleet_performance_overview", "fleet_performance_core"),
    ("Quel est le MTBF des 777 à Fekola en Mai 2026 ?", "fr", "single_kpi", None),
    ("Give me MTBS, MTBF and MTTR for Essakane 785.", "en", "reliability_overview", "reliability_core"),
    ("Compare Fekola and Essakane fleet performance YTD.", "en", "entity_comparison", "fleet_performance_core"),
    ("Show the MTBS, MTBF and MTTR trend at Fekola over the last 12 months.", "en", "trend_analysis", "reliability_core"),
    ("Which Fekola machines have the lowest Availability?", "en", "ranking", None),
    ("What percentage of Essakane 785 downtime is planned versus unplanned?", "en", "planned_unplanned_analysis", "downtime_mix"),
    ("Benchmark Essakane 785 against the same Model across all Sites.", "en", "benchmark_analysis", None),
)


def configure(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIMetricMapping = apps.get_model("reports", "AIMetricMapping")
    AIDaxTemplate = apps.get_model("reports", "AIDaxTemplate")
    AIResponseTemplate = apps.get_model("reports", "AIResponseTemplate")
    AIIntentMapping = apps.get_model("reports", "AIIntentResponseTemplateMapping")
    AIQuestionExample = apps.get_model("reports", "AIQuestionExample")
    AISynonym = apps.get_model("reports", "AISynonym")
    KnowledgeSynonym = apps.get_model("reports", "KnowledgeSynonym")
    KnowledgeKPI = apps.get_model("reports", "KnowledgeKPIDictionary")
    AIAgent = apps.get_model("reports", "AIAgent")
    AIAgentCapability = apps.get_model("reports", "AIAgentCapability")
    AIAgentIntent = apps.get_model("reports", "AIAgentIntent")
    section = AIConfigSection.objects.get(code="performance")

    for code, (label, measure, table, calculation_type, higher, lower) in METRICS.items():
        AIMetricMapping.objects.update_or_create(
            section=section, metric_code=code,
            defaults={
                "metric_label": label,
                "powerbi_measure_name": measure,
                "description": "Governed Fleet Performance semantic measure. Evaluate directly in the requested context.",
                "is_active": True,
            },
        )
        KnowledgeKPI.objects.update_or_create(
            section=section, kpi_code=code,
            defaults={
                "kpi_name": label,
                "business_definition": f"Governed Fleet Performance KPI: {label}.",
                "formula_description": "Calculated by the existing Power BI semantic measure; Mining360 does not recreate the formula.",
                "powerbi_measure_name": measure,
                "unit": "Percentage" if calculation_type == "Percentage" else "Hours",
                "aggregation_rule": "Evaluate the semantic measure directly in the requested filter and grouping context.",
                "default_time_grain": "Month",
                "business_category": "Reliability" if code in {"mtbs", "mtbf", "mttr"} else "Maintenance",
                "higher_is_better": higher,
                "lower_is_better": lower,
                "calculation_type": calculation_type,
                "null_handling_rule": "Return Blank",
                "zero_denominator_behavior": "Return Blank",
                "decimal_precision": 2,
                "display_format": "0.00%" if calculation_type == "Percentage" else "#,##0.00 h",
                "powerbi_workspace_id": WORKSPACE_ID,
                "powerbi_report_id": REPORT_ID,
                "powerbi_semantic_model_id": DATASET_ID,
                "powerbi_measure_table": table,
                "powerbi_measure_full_reference": f"'{table}'{measure}",
                "source_report_name": "Fleet Performance Report",
                "trend_supported": True,
                "comparison_supported": True,
                "ranking_supported": True,
                "root_cause_supported": code in {"availability", "mtbf", "mttr", "unplanned_downtime_percentage"},
                "supported_dimensions": ["minesite", "model", "equipment", "serial_number", "family", "period"],
                "optional_filters": ["minesite", "model", "equipment", "serial_number", "family", "period"],
                "validation_status": "To Review",
                "is_active": True,
                "version": "1.0",
            },
        )

    for bundle, metric_codes in BUNDLES.items():
        AIDaxTemplate.objects.update_or_create(
            section=section, template_code=f"BUNDLE_{bundle.upper()}",
            defaults={
                "template_name": bundle.replace("_", " ").title(),
                "dax_template": "Controlled metric bundle: " + ", ".join(metric_codes),
                "description": "Logical bundle consumed by the governed Fleet Performance query planner.",
                "is_active": True,
            },
        )
    for code in DAX_TEMPLATES:
        AIDaxTemplate.objects.update_or_create(
            section=section, template_code=code,
            defaults={
                "template_name": code.replace("PERF_", "").replace("_", " ").title(),
                "dax_template": "Generated by FleetPerformanceQueryPlanningService from validated metrics, dimensions and filters.",
                "description": "Closed Fleet Performance query template; arbitrary DAX is not accepted.",
                "is_active": True,
            },
        )

    for code, (intent_type, components) in RESPONSE_TEMPLATES.items():
        template, _ = AIResponseTemplate.objects.update_or_create(
            code=code,
            defaults={
                "name": code.replace("_", " ").title(),
                "description": "Adaptive Fleet Performance response.",
                "domain": "machine_performance",
                "supported_intent_types": [intent_type],
                "primary_component": components[1] if len(components) > 1 else components[0],
                "component_order_json": components,
                "required_data_fields_json": ["rows"],
                "optional_data_fields_json": ["metrics", "coverage", "source"],
                "fallback_template_code": "generic_analytical",
                "active": True,
                "validation_status": "Validated",
                "version": "1.0",
            },
        )
        AIIntentMapping.objects.update_or_create(
            domain="machine_performance", intent_type=intent_type,
            scope_type="", metric_code="", response_template=template,
            defaults={"priority": 250, "active": True, "validation_status": "Validated"},
        )

    for canonical, variants in SYNONYMS.items():
        for value in variants:
            language = "fr" if any(char in value for char in "éèà") or value.startswith(("temps", "downtime plan", "arrêts")) else "en"
            AISynonym.objects.update_or_create(
                section=section, entity_type="metric", canonical_value=canonical,
                synonym_value=value, language=language,
                defaults={"is_active": True},
            )
            KnowledgeSynonym.objects.update_or_create(
                section=section, canonical_term=canonical, synonym=value,
                entity_type="KPI", language=language,
                defaults={
                    "normalized_value": canonical,
                    "confidence": 100,
                    "synonym_source": "System Generated",
                    "match_type": "Phrase",
                    "resolution_priority": 80,
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )

    for question, language, intent_type, bundle in QUESTIONS:
        AIQuestionExample.objects.update_or_create(
            section=section, question_text=question,
            defaults={
                "language": language,
                "expected_json_intent": {
                    "section": "performance", "capability": "fleet_performance",
                    "intent_type": intent_type, "metric_bundle": bundle,
                },
                "is_active": True,
            },
        )

    agent = AIAgent.objects.filter(code="machine_performance").first()
    if agent:
        AIAgentCapability.objects.update_or_create(
            agent=agent, capability_code="fleet_performance",
            defaults={
                "display_name": "Fleet Performance Intelligence",
                "description": "Compositional Fleet Performance analysis using governed semantic measures.",
                "enabled": True,
                "configuration_json": {"metric_bundles": BUNDLES, "semantic_model_id": DATASET_ID},
                "priority": 95,
                "validation_status": "To Review",
            },
        )
        for intent_type in {item[0] for item in RESPONSE_TEMPLATES.values()}:
            AIAgentIntent.objects.update_or_create(
                agent=agent, intent_code=intent_type,
                defaults={
                    "display_name": intent_type.replace("_", " ").title(),
                    "description": "Governed Fleet Performance analytical intent.",
                    "examples_json": [],
                    "required_entities_json": [],
                    "optional_entities_json": ["minesite", "model", "equipment", "serial_number", "period"],
                    "priority": 90,
                    "enabled": True,
                    "validation_status": "To Review",
                },
            )


def rollback(apps, schema_editor):
    section = apps.get_model("reports", "AIConfigSection").objects.filter(code="performance").first()
    if not section:
        return
    AIMetricMapping = apps.get_model("reports", "AIMetricMapping")
    legacy = {
        "availability": "[Avail Per Equip]", "mtbs": "[MTBS]",
        "mtbf": "[MTBF]", "mttr": "[MTTR]",
    }
    for code, measure in legacy.items():
        AIMetricMapping.objects.filter(section=section, metric_code=code).update(powerbi_measure_name=measure)
    AIMetricMapping.objects.filter(
        section=section,
        metric_code__in=["planned_downtime_percentage", "unplanned_downtime_percentage"],
    ).delete()
    apps.get_model("reports", "AIDaxTemplate").objects.filter(
        section=section,
        template_code__in=list(DAX_TEMPLATES) + [f"BUNDLE_{code.upper()}" for code in BUNDLES],
    ).delete()
    apps.get_model("reports", "AIQuestionExample").objects.filter(
        section=section, question_text__in=[item[0] for item in QUESTIONS]
    ).delete()
    apps.get_model("reports", "AIIntentResponseTemplateMapping").objects.filter(
        domain="machine_performance", response_template__code__in=list(RESPONSE_TEMPLATES)
    ).delete()
    apps.get_model("reports", "AIResponseTemplate").objects.filter(code__in=list(RESPONSE_TEMPLATES)).delete()
    apps.get_model("reports", "AIAgentCapability").objects.filter(capability_code="fleet_performance").delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0100_complete_fleet_inventory_config")]
    operations = [migrations.RunPython(configure, rollback)]
