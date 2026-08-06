import json
from collections import Counter

from reports.models import (
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
    SupportedPowerBIAction,
)
from reports.powerbi import list_workspace_reports, resolve_workspace_dataset_id


section = AIConfigSection.objects.get(code="performance")
models = {
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

inventory = {}
for label, model in models.items():
    queryset = model.objects.all()
    if any(field.name == "section" for field in model._meta.fields):
        queryset = queryset.filter(section=section)
    statuses = {}
    if any(field.name == "validation_status" for field in model._meta.fields):
        statuses = dict(
            Counter(queryset.values_list("validation_status", flat=True))
        )
    inventory[label] = {"total": queryset.count(), "statuses": statuses}

dataset_name = "FPR Global DB + RLS"
dataset_id = resolve_workspace_dataset_id(dataset_name)
report = next((item for item in list_workspace_reports() if item.name == dataset_name), None)
payload = {
    "section": {"id": section.id, "code": section.code, "name": section.name},
    "confirmed_powerbi": {
        "workspace_id": "a378c518-bfc4-4cd7-a49d-ba40394db80f",
        "dataset_name": dataset_name,
        "dataset_id": dataset_id,
        "report_id": report.id if report else "",
        "report_name": report.name if report else "",
        "report_dataset_id": report.dataset_id if report else "",
        "embed_url_available": bool(report and report.embed_url),
    },
    "inventory": inventory,
    "metric_mappings": list(
        AIMetricMapping.objects.filter(section=section).values(
            "metric_code", "metric_label", "powerbi_measure_name", "is_active"
        )
    ),
    "filter_mappings": list(
        AIFilterMapping.objects.filter(section=section).values(
            "filter_code", "filter_label", "powerbi_table_name",
            "powerbi_column_name", "data_type", "is_required", "is_active"
        )
    ),
    "kpi_dictionary": list(
        KnowledgeKPIDictionary.objects.filter(section=section).values(
            "id", "kpi_code", "kpi_name", "powerbi_measure_name",
            "powerbi_measure_table", "powerbi_semantic_model_id",
            "business_definition", "formula_description", "unit",
            "validation_status", "is_active"
        )
    ),
    "configured_pages": list(
        PowerBIPage.objects.filter(section=section).values(
            "id", "report__report_name", "page_internal_name",
            "page_display_name", "validation_status", "is_active"
        )
    ),
    "configured_visuals": list(
        PowerBIVisual.objects.filter(section=section).values(
            "id", "page__page_display_name", "visual_internal_name",
            "visual_title", "visual_type", "related_metric_code",
            "validation_status", "is_active"
        )
    ),
}
print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
