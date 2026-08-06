from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from .models import (
    AIConfigSection,
    AIBusinessRule,
    AIBusinessVocabulary,
    AIDaxTemplate,
    AIFewShotExample,
    AIFilterMapping,
    AIKPITarget,
    AIMetricMapping,
    AIPowerBIPage,
    AIPromptTemplate,
    AIQuestionExample,
    AIRecommendedAction,
    AISemanticColumn,
    AISemanticMeasure,
    AISemanticRelationship,
    AISemanticTable,
    AISynonym,
    AIVisualMapping,
    IntentNavigationMapping,
    KnowledgeBusinessGlossary,
    KnowledgeBusinessRule,
    KnowledgeKPIDictionary,
    KnowledgeMiningTerminology,
    KnowledgePrompt,
    KnowledgeQuestion,
    KnowledgeRecommendedAction,
    KnowledgeSynonym,
    KPIPageMapping,
    KPIVisualMapping,
    PowerBIPage,
    PowerBIReport,
    PowerBISlicer,
    PowerBIVisual,
)
from .powerbi import env_value, execute_dataset_dax, list_workspace_reports, resolve_workspace_dataset_id


DATASET_NAME = "FPR Global DB + RLS"
TARGET_KPI_CODE = "availability"
ALLOWED_REPORT_NAMES = (
    "FPR Global DB + RLS",
    "Neemba Monthly Report_New",
)


MANAGED_MODELS = {
    "AI Config / Question Examples": AIQuestionExample,
    "AI Config / Synonyms": AISynonym,
    "AI Config / Metrics Mapping": AIMetricMapping,
    "AI Config / Filters Mapping": AIFilterMapping,
    "AI Config / DAX Templates": AIDaxTemplate,
    "AI Config / Semantic Tables": AISemanticTable,
    "AI Config / Semantic Columns": AISemanticColumn,
    "AI Config / Semantic Measures": AISemanticMeasure,
    "AI Config / Semantic Relationships": AISemanticRelationship,
    "AI Config / Business Vocabulary": AIBusinessVocabulary,
    "AI Config / Few Shot Examples": AIFewShotExample,
    "AI Config / Prompt Templates": AIPromptTemplate,
    "AI Config / Business Rules": AIBusinessRule,
    "AI Config / Power BI Pages": AIPowerBIPage,
    "AI Config / Visual Mapping": AIVisualMapping,
    "AI Config / KPI Targets": AIKPITarget,
    "AI Config / Recommended Actions": AIRecommendedAction,
    "Knowledge Base / KPI Dictionary": KnowledgeKPIDictionary,
    "Knowledge Base / Business Glossary": KnowledgeBusinessGlossary,
    "Knowledge Base / Mining Terminology": KnowledgeMiningTerminology,
    "Knowledge Base / Question Library": KnowledgeQuestion,
    "Knowledge Base / Synonym Library": KnowledgeSynonym,
    "Knowledge Base / Business Rules": KnowledgeBusinessRule,
    "Knowledge Base / Prompt Library": KnowledgePrompt,
    "Knowledge Base / Recommended Actions": KnowledgeRecommendedAction,
    "Power BI Interaction / Reports": PowerBIReport,
    "Power BI Interaction / Pages": PowerBIPage,
    "Power BI Interaction / Visuals": PowerBIVisual,
    "Power BI Interaction / Slicers": PowerBISlicer,
    "Power BI Interaction / KPI to Page": KPIPageMapping,
    "Power BI Interaction / KPI to Visual": KPIVisualMapping,
    "Power BI Interaction / Intent Navigation": IntentNavigationMapping,
}


AVAILABILITY_TERMS = [
    ("Availability", "Reliability"),
    ("Physical Availability", "Reliability"),
    ("Mine Site", "Mine Site"),
    ("Equipment Model", "Equipment"),
    ("Equipment Family", "Equipment"),
    ("Serial Number", "Equipment"),
    ("Customer", "Business"),
    ("Period", "Time"),
    ("Downtime", "Downtime"),
]


AVAILABILITY_BUSINESS_RULES = [
    ("availability_physical_equivalence", "Availability and Physical Availability equivalence"),
    ("availability_configured_measure", "Use the configured Availability Power BI measure only"),
    ("availability_controlled_dax", "Use controlled DAX templates for Availability only"),
    ("availability_authorized_filters", "Use configured Availability filter columns only"),
    ("availability_ambiguity", "Clarify unresolved Availability ambiguity"),
    ("availability_invalid_filter", "Reject unavailable Availability filter values"),
    ("availability_percentage_format", "Format Availability as configured percentage"),
    ("availability_relative_period", "Resolve relative periods before Availability execution"),
    ("availability_rls", "Respect Power BI RLS when querying Availability"),
]


AVAILABILITY_DAX_TEMPLATES = [
    "availability_value",
    "availability_one_filter",
    "availability_multiple_filters",
    "availability_by_period",
    "availability_monthly_trend",
    "availability_compare_minesites",
    "availability_compare_models",
    "availability_top_n",
    "availability_bottom_n",
    "availability_equipment_detail",
    "availability_target_variance",
    "availability_current_period",
    "availability_previous_period",
    "availability_year_to_date",
]


AVAILABILITY_PROMPTS = [
    "Availability Intent Classification",
    "Availability Entity Extraction",
    "Availability Synonym Resolution",
    "Availability Clarification",
    "Availability Response Generation",
    "Availability Business Interpretation",
    "Availability Recommended Action",
    "Availability Knowledge Resolution Explanation",
]


def _field_names(model):
    return {field.name for field in model._meta.fields}


def _section_queryset(model, section):
    queryset = model.objects.all()
    if "section" in _field_names(model):
        queryset = queryset.filter(section=section)
    return queryset


def _inventory(section):
    result = {}
    for label, model in MANAGED_MODELS.items():
        queryset = _section_queryset(model, section)
        statuses = {}
        if "validation_status" in _field_names(model):
            statuses = dict(Counter(queryset.values_list("validation_status", flat=True)))
        result[label] = {
            "total": queryset.count(),
            "statuses": statuses,
            "governance": {
                "has_validation_status": "validation_status" in _field_names(model),
                "has_source": "source" in _field_names(model) or "synonym_source" in _field_names(model),
                "has_validation_notes": "validation_notes" in _field_names(model),
            },
        }
    return result


def _technical_probe(dataset_id):
    tests = {}
    metadata = {}
    for info_name in ("TABLES", "COLUMNS", "MEASURES", "RELATIONSHIPS"):
        try:
            rows = execute_dataset_dax(dataset_id, f"EVALUATE INFO.{info_name}()")
            tests[info_name.lower()] = {"status": "Passed", "rows": len(rows), "error": ""}
            metadata[info_name.lower()] = rows
        except Exception as exc:
            tests[info_name.lower()] = {
                "status": "Failed",
                "rows": 0,
                "error": str(exc)[:1200],
            }
            metadata[info_name.lower()] = []
    return tests, metadata


def _proposal(section_name, item, action="create", source="System Generated", reason="", status="To Review"):
    return {
        "section": section_name,
        "action": action,
        "item": item,
        "source": source,
        "validation_status": status,
        "reason": reason,
    }


def build_performance_population_preview():
    section = AIConfigSection.objects.get(code="performance")
    dataset_id = resolve_workspace_dataset_id(DATASET_NAME)
    live_reports = {
        item.name: item
        for item in list_workspace_reports()
        if item.name in ALLOWED_REPORT_NAMES
    }
    configured_reports = {
        item.report_name: item
        for item in PowerBIReport.objects.filter(report_name__in=ALLOWED_REPORT_NAMES)
    }
    live_report = live_reports.get(DATASET_NAME)
    primary_tests, metadata = _technical_probe(dataset_id)
    tests = {
        f"fleet_performance_{name}": result
        for name, result in primary_tests.items()
    }
    monthly_report = configured_reports.get("Neemba Monthly Report_New")
    if monthly_report and monthly_report.semantic_model_id:
        monthly_tests, _monthly_metadata = _technical_probe(monthly_report.semantic_model_id)
        tests.update({
            f"mine_monthly_{name}": result
            for name, result in monthly_tests.items()
        })
    inventory = _inventory(section)
    proposals = []
    conflicts = []
    missing = []
    ignored = []

    for report_name in ALLOWED_REPORT_NAMES:
        configured_report = configured_reports.get(report_name)
        live_item = live_reports.get(report_name)
        if configured_report:
            ignored.append(_proposal(
                "Power BI Interaction / Reports",
                configured_report.display_name or report_name,
                "ignore",
                "Imported",
                "Availability report already configured and explicitly allowed.",
                configured_report.validation_status,
            ))
        elif live_item:
            proposals.append(_proposal(
                "Power BI Interaction / Reports",
                report_name,
                source="Imported",
                reason="Availability report confirmed by Power BI REST API.",
            ))

    # Use live metadata when available; otherwise only propose objects already evidenced
    # by validated/configured filter and KPI mappings.
    table_names = set()
    column_pairs = set()
    if metadata["tables"]:
        for row in metadata["tables"]:
            name = str(row.get("[Name]") or row.get("Name") or "").strip()
            if name:
                table_names.add(name)
    if metadata["columns"]:
        for row in metadata["columns"]:
            table = str(row.get("[Table]") or row.get("Table") or "").strip()
            column = str(row.get("[Name]") or row.get("Name") or "").strip()
            if table and column:
                column_pairs.add((table, column))
    if not table_names:
        for mapping in AIFilterMapping.objects.filter(section=section, is_active=True):
            table_names.add(mapping.powerbi_table_name)
            column_pairs.add((mapping.powerbi_table_name, mapping.powerbi_column_name))
        table_names.update(
            value for value in KnowledgeKPIDictionary.objects.filter(
                section=section,
                kpi_code=TARGET_KPI_CODE,
                is_active=True,
            ).values_list("powerbi_measure_table", flat=True) if value
        )
        missing.append({
            "section": "Semantic Model",
            "item": "Complete tables, columns, measures and relationships",
            "reason": "INFO metadata queries are not authorized (401); inferred candidates are limited to existing mappings.",
        })

    existing_tables = {
        value.casefold() for value in AISemanticTable.objects.filter(section=section).values_list("table_name", flat=True)
    }
    for table in sorted(table_names):
        target = "ignore" if table.casefold() in existing_tables else "create"
        destination = ignored if target == "ignore" else proposals
        destination.append(_proposal(
            "AI Config / Semantic Tables", table, target,
            "Imported" if metadata["tables"] else "System Generated",
            "Confirmed by Power BI metadata." if metadata["tables"] else "Referenced by an existing filter or KPI mapping.",
        ))

    existing_columns = {
        (table.casefold(), column.casefold())
        for table, column in AISemanticColumn.objects.filter(section=section).values_list("table_name", "column_name")
    }
    for table, column in sorted(column_pairs):
        target = "ignore" if (table.casefold(), column.casefold()) in existing_columns else "create"
        destination = ignored if target == "ignore" else proposals
        destination.append(_proposal(
            "AI Config / Semantic Columns", f"{table}[{column}]", target,
            "Imported" if metadata["columns"] else "System Generated",
            "Allowed filter mapping already exists; business meaning remains To Review.",
        ))

    active_metrics = list(AIMetricMapping.objects.filter(
        section=section,
        metric_code=TARGET_KPI_CODE,
        is_active=True,
    ))
    existing_measures = {
        value.casefold() for value in AISemanticMeasure.objects.filter(section=section).values_list("measure_name", flat=True)
    }
    for metric in active_metrics:
        measure = metric.powerbi_measure_name.strip("[]")
        target = "ignore" if measure.casefold() in existing_measures else "create"
        destination = ignored if target == "ignore" else proposals
        destination.append(_proposal(
            "AI Config / Semantic Measures", measure, target,
            "Imported" if metadata["measures"] else "System Generated",
            "Referenced by an active Metrics Mapping; DAX expression could not be confirmed."
            if not metadata["measures"] else "Confirmed by INFO.MEASURES().",
        ))
        if not KnowledgeKPIDictionary.objects.filter(section=section, kpi_code=metric.metric_code).exists():
            proposals.append(_proposal(
                "Knowledge Base / KPI Dictionary", metric.metric_code,
                reason=f"Active metric mapping exists for {metric.powerbi_measure_name}; business fields require review.",
            ))

    if not metadata["relationships"]:
        missing.append({
            "section": "AI Config / Semantic Relationships",
            "item": "All relationships",
            "reason": "No relationship metadata could be retrieved; no relationship will be invented.",
        })

    existing_terms = {
        value.casefold() for value in KnowledgeMiningTerminology.objects.filter(section=section).values_list("term", flat=True)
    }
    for term, category in AVAILABILITY_TERMS:
        target = "ignore" if term.casefold() in existing_terms else "create"
        destination = ignored if target == "ignore" else proposals
        destination.append(_proposal(
            "Knowledge Base / Mining Terminology", term, target,
            reason=f"Term evidenced by configured filters, KPI mappings or report pages; category={category}; definition=To be validated.",
        ))

    existing_rules = {
        value.casefold() for value in KnowledgeBusinessRule.objects.filter(section=section).values_list("rule_name", flat=True)
    }
    for code, name in AVAILABILITY_BUSINESS_RULES:
        target = "ignore" if name.casefold() in existing_rules else "create"
        destination = ignored if target == "ignore" else proposals
        destination.append(_proposal(
            "Knowledge Base / Business Rules", f"{code}: {name}", target,
            reason="Deterministic platform safety or confirmed Availability equivalence rule.",
        ))

    existing_templates = {
        value.casefold() for value in AIDaxTemplate.objects.filter(section=section).values_list("template_code", flat=True)
    }
    for code in AVAILABILITY_DAX_TEMPLATES:
        target = "ignore" if code.casefold() in existing_templates else "create"
        destination = ignored if target == "ignore" else proposals
        destination.append(_proposal(
            "AI Config / DAX Templates", code, target,
            reason="Controlled Availability template skeleton; must remain To Review until a Power BI execution test passes.",
        ))

    existing_prompts = {
        value.casefold() for value in KnowledgePrompt.objects.filter(section=section).values_list("prompt_name", flat=True)
    }
    for name in AVAILABILITY_PROMPTS:
        target = "ignore" if name.casefold() in existing_prompts else "create"
        destination = ignored if target == "ignore" else proposals
        destination.append(_proposal(
            "Knowledge Base / Prompt Library", name, target,
            reason="Availability orchestration prompt; content must enforce its configured mapping and no free DAX.",
        ))

    # Question and few-shot generation is counted from configured active metrics and filters.
    question_matrix = [
        ("simple_kpi", 2),
        ("one_filter", 4),
        ("multiple_filters", 4),
        ("time", 4),
        ("comparison", 4),
        ("trend", 4),
        ("ranking", 4),
        ("diagnostic", 2),
        ("clarification", 2),
        ("unavailable", 2),
    ]
    existing_questions = KnowledgeQuestion.objects.filter(section=section).count()
    for family, count in question_matrix:
        proposals.append(_proposal(
            "Knowledge Base / Question Library",
            f"{family}: {count} bilingual examples",
            reason=f"Generated only for KPI={TARGET_KPI_CODE} and its configured filters; {existing_questions} questions already exist and will not be overwritten.",
        ))
    proposals.append(_proposal(
        "AI Config / Few Shot Examples", "12 bilingual Availability examples",
        reason="Covers Availability filters, trend, comparison, ranking, ambiguity, typo and no-data behavior.",
    ))

    reports_with_visuals = set(
        PowerBIVisual.objects.filter(
            page__report__report_name__in=ALLOWED_REPORT_NAMES
        ).values_list("page__report__report_name", flat=True)
    )
    reports_missing_visuals = [
        report_name
        for report_name in ALLOWED_REPORT_NAMES
        if report_name not in reports_with_visuals
    ]
    if reports_missing_visuals:
        missing.append({
            "section": "Power BI Interaction / Visuals and Slicers",
            "item": ", ".join(reports_missing_visuals),
            "reason": "REST metadata does not expose report visuals; JavaScript discovery must run from an embedded report.",
        })

    proposed_sections = {item["section"] for item in proposals}
    for label, data in inventory.items():
        governance = data["governance"]
        if (
            label in proposed_sections
            and not governance["has_validation_status"]
            and label.startswith(("AI Config", "Power BI Interaction"))
        ):
            conflicts.append({
                "section": label,
                "type": "Governance schema gap",
                "reason": "Generated content cannot be safely marked To Review until Validation Status is added.",
            })

    counts = Counter(item["section"] for item in proposals)
    report = {
        "mode": "Preview",
        "batch_id": f"kb-preview-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "section": section.code,
            "kpi_code": TARGET_KPI_CODE,
            "reports": list(ALLOWED_REPORT_NAMES),
        },
        "powerbi": {
            "workspace_id": env_value("POWERBI_WORKSPACE_ID"),
            "reports": [
                {
                    "report_name": report_name,
                    "display_name": (
                        configured_reports[report_name].display_name
                        if report_name in configured_reports
                        else report_name
                    ),
                    "report_id": (
                        configured_reports[report_name].report_id
                        if report_name in configured_reports
                        else getattr(live_reports.get(report_name), "id", "")
                    ),
                    "semantic_model_id": (
                        configured_reports[report_name].semantic_model_id
                        if report_name in configured_reports
                        else ""
                    ),
                    "embed_url_available": bool(
                        getattr(live_reports.get(report_name), "embed_url", "")
                    ),
                }
                for report_name in ALLOWED_REPORT_NAMES
            ],
        },
        "technical_tests": tests,
        "inventory": inventory,
        "summary": {
            "proposed_creates_or_groups": len(proposals),
            "proposed_updates": 0,
            "ignored_existing": len(ignored),
            "conflicts": len(conflicts),
            "missing_information": len(missing),
            "proposals_by_section": dict(sorted(counts.items())),
            "database_writes": 0,
        },
        "proposals": proposals,
        "ignored": ignored,
        "conflicts": conflicts,
        "missing_information": missing,
        "apply_preconditions": [
            "User approval of this Preview.",
            "Add governance fields to AI Config and navigation mapping models that lack Validation Status and Source.",
            "Resolve or authorize INFO metadata access, or run embedded JavaScript discovery for visuals and slicers.",
            "Keep all generated business content To Review.",
            "Do not update the validated Availability KPI or validated synonyms automatically.",
            "Create Availability navigation mappings only for Fleet Performance Report and Mine Monthly Report New.",
        ],
    }
    return report


def preview_as_markdown(report):
    lines = [
        "# Knowledge Base Population Report",
        "",
        f"- Mode: **{report['mode']}**",
        f"- Batch ID: `{report['batch_id']}`",
        f"- Section: `{report['scope']['section']}`",
        f"- Reports: `{', '.join(report['scope']['reports'])}`",
        f"- Database writes: **{report['summary']['database_writes']}**",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        if key != "proposals_by_section":
            lines.append(f"- {key.replace('_', ' ').title()}: {value}")
    lines.extend(["", "## Proposed Population", ""])
    for section, count in report["summary"]["proposals_by_section"].items():
        lines.append(f"- **{section}**: {count}")
    lines.extend(["", "## Technical Tests", ""])
    for name, test in report["technical_tests"].items():
        lines.append(f"- **{name}**: {test['status']} ({test['rows']} rows)")
        if test["error"]:
            lines.append(f"  - {test['error']}")
    for title, key in [
        ("Conflicts", "conflicts"),
        ("Missing Information", "missing_information"),
        ("Apply Preconditions", "apply_preconditions"),
    ]:
        lines.extend(["", f"## {title}", ""])
        for item in report[key]:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('section', '')}**: {item.get('item', item.get('type', ''))}")
                lines.append(f"  - {item.get('reason', '')}")
            else:
                lines.append(f"- {item}")
    return "\n".join(lines) + "\n"
