from __future__ import annotations

from collections import defaultdict

from django.db.models import Case, IntegerField, Value, When

from .models import (
    AIBusinessRule,
    AIBusinessVocabulary,
    AIConfigSection,
    AIDaxTemplate,
    AIFilterMapping,
    AIFewShotExample,
    AIKPITarget,
    AIMetricMapping,
    AIRecommendedAction,
    AISemanticColumn,
    AISemanticMeasure,
    AISemanticRelationship,
    AISemanticTable,
    AIVisualMapping,
    AIPromptTemplate,
    AIQuestionExample,
    AISynonym,
    KnowledgeBusinessGlossary,
    KnowledgeBusinessRule,
    KnowledgeKPIDictionary,
    KnowledgePrompt,
    KnowledgeQuestion,
    KnowledgeRecommendedAction,
    KnowledgeSynonym,
)


def _section_queryset():
    return AIConfigSection.objects.annotate(
        display_order=Case(
            When(code="performance", then=Value(0)),
            When(code="parts_sales", then=Value(1)),
            When(code="planned_component_rebuild", then=Value(2)),
            default=Value(999),
            output_field=IntegerField(),
        )
    ).order_by("display_order", "name")


def get_active_section_objects() -> list[AIConfigSection]:
    return list(_section_queryset().filter(is_active=True))


def get_section_by_code(section_code: str | None) -> AIConfigSection | None:
    code = str(section_code or "").strip()
    if not code:
        return None
    return AIConfigSection.objects.filter(code=code, is_active=True).first()


def get_active_sections() -> list[dict]:
    return [
        {
            "id": section.id,
            "name": section.name,
            "code": section.code,
            "description": section.description,
            "is_active": section.is_active,
        }
        for section in get_active_section_objects()
    ]


def get_question_examples(section_code: str) -> list[dict]:
    section = get_section_by_code(section_code)
    if not section:
        return []
    items = [
        {
            "id": item.id,
            "section": section.code,
            "question_text": item.question_text,
            "language": item.language,
            "expected_json_intent": item.expected_json_intent,
            "is_active": item.is_active,
        }
        for item in section.question_examples.all()
    ]
    items.extend(
        {
            "id": item.id,
            "section": section.code,
            "question_text": item.question_text,
            "language": item.language,
            "expected_json_intent": item.expected_json_intent,
            "is_active": item.is_active,
            "source": "knowledge_base",
        }
        for item in KnowledgeQuestion.objects.filter(section=section, validation_status="Validated", is_active=True)
    )
    return items


def get_synonyms(section_code: str) -> list[dict]:
    section = get_section_by_code(section_code)
    if not section:
        return []
    items = [
        {
            "id": item.id,
            "section": section.code,
            "entity_type": item.entity_type,
            "canonical_value": item.canonical_value,
            "synonym_value": item.synonym_value,
            "language": item.language,
            "is_active": item.is_active,
        }
        for item in section.synonyms.all()
    ]
    items.extend(
        {
            "id": item.id,
            "section": section.code,
            "entity_type": item.entity_type.lower().replace(" ", "_"),
            "canonical_value": item.canonical_term,
            "synonym_value": item.synonym,
            "language": item.language,
            "is_active": item.is_active,
            "source": "knowledge_base",
        }
        for item in KnowledgeSynonym.objects.filter(section=section, validation_status="Validated", is_active=True)
    )
    return items


def get_metric_mapping(section_code: str) -> list[dict]:
    section = get_section_by_code(section_code)
    if not section:
        return []
    return [
        {
            "id": item.id,
            "section": section.code,
            "metric_code": item.metric_code,
            "metric_label": item.metric_label,
            "powerbi_measure_name": item.powerbi_measure_name,
            "description": item.description,
            "is_active": item.is_active,
        }
        for item in section.metric_mappings.all()
    ]


def get_filter_mapping(section_code: str) -> list[dict]:
    section = get_section_by_code(section_code)
    if not section:
        return []
    return [
        {
            "id": item.id,
            "section": section.code,
            "filter_code": item.filter_code,
            "filter_label": item.filter_label,
            "powerbi_table_name": item.powerbi_table_name,
            "powerbi_column_name": item.powerbi_column_name,
            "data_type": item.data_type,
            "is_required": item.is_required,
            "is_active": item.is_active,
        }
        for item in section.filter_mappings.all()
    ]


def get_dax_template(section_code: str, template_code: str | None = None) -> dict | None:
    section = get_section_by_code(section_code)
    if not section:
        return None
    queryset = section.dax_templates.filter(is_active=True)
    if template_code:
        template = queryset.filter(template_code=template_code).first()
        if template:
            return {
                "id": template.id,
                "section": section.code,
                "template_name": template.template_name,
                "template_code": template.template_code,
                "dax_template": template.dax_template,
                "description": template.description,
                "is_active": template.is_active,
            }
    template = queryset.first()
    if not template:
        return None
    return {
        "id": template.id,
        "section": section.code,
        "template_name": template.template_name,
        "template_code": template.template_code,
        "dax_template": template.dax_template,
        "description": template.description,
        "is_active": template.is_active,
    }


def get_prompt_template(section_code: str, prompt_type: str) -> dict | None:
    section = get_section_by_code(section_code)
    if not section:
        return None
    prompt_label = {
        "intent_extraction": "Intent Extraction",
        "response_generation": "Business Response",
        "business_explanation": "Business Response",
        "recommendation": "Recommendation",
        "executive_summary": "Executive Summary",
        "comparison": "Comparison",
        "trend_analysis": "Trend Analysis",
    }.get(prompt_type, prompt_type.replace("_", " ").title())
    kb_template = (
        KnowledgePrompt.objects
        .filter(section=section, prompt_type__iexact=prompt_label, validation_status="Validated", is_active=True)
        .order_by("-updated_at")
        .first()
    )
    if kb_template:
        return {
            "id": kb_template.id,
            "section": section.code,
            "prompt_type": prompt_type,
            "template_name": kb_template.prompt_name,
            "prompt_template": kb_template.prompt_content,
            "description": "",
            "is_active": kb_template.is_active,
            "source": "knowledge_base",
        }
    template = (
        AIPromptTemplate.objects
        .filter(section=section, prompt_type=prompt_type, is_active=True)
        .order_by("template_name")
        .first()
    )
    if not template:
        return None
    return {
        "id": template.id,
        "section": section.code,
        "prompt_type": template.prompt_type,
        "template_name": template.template_name,
        "prompt_template": template.prompt_template,
        "description": template.description,
        "is_active": template.is_active,
    }


def build_section_catalog(section_code: str | None = None) -> dict:
    sections = _section_queryset()
    if section_code:
        sections = sections.filter(code=section_code)
    payload = []
    for section in sections:
        payload.append(
            {
                "id": section.id,
                "name": section.name,
                "code": section.code,
                "description": section.description,
                "is_active": section.is_active,
                "question_examples": get_question_examples(section.code),
                "synonyms": get_synonyms(section.code),
                "metrics": get_metric_mapping(section.code),
                "filters": get_filter_mapping(section.code),
                "dax_templates": [
                    {
                        "id": item.id,
                        "section": section.code,
                        "template_name": item.template_name,
                        "template_code": item.template_code,
                        "dax_template": item.dax_template,
                        "description": item.description,
                        "is_active": item.is_active,
                    }
                    for item in section.dax_templates.all()
                ],
                "semantic_tables": [
                    {"table_name": item.table_name, "display_name": item.display_name, "description": item.description}
                    for item in AISemanticTable.objects.filter(section=section, is_active=True)
                ],
                "semantic_columns": [
                    {
                        "table_name": item.table_name,
                        "column_name": item.column_name,
                        "display_name": item.display_name,
                        "data_type": item.data_type,
                        "is_filter": item.is_filter,
                        "description": item.description,
                    }
                    for item in AISemanticColumn.objects.filter(section=section, is_active=True)
                ],
                "semantic_measures": [
                    {
                        "measure_name": item.measure_name,
                        "display_name": item.display_name,
                        "dax_name": item.dax_name,
                        "unit": item.unit,
                        "category": item.category,
                        "description": item.description,
                    }
                    for item in AISemanticMeasure.objects.filter(section=section, is_active=True)
                ],
                "semantic_relationships": [
                    {
                        "parent_table": item.parent_table,
                        "parent_column": item.parent_column,
                        "child_table": item.child_table,
                        "child_column": item.child_column,
                        "relationship_type": item.relationship_type,
                    }
                    for item in AISemanticRelationship.objects.filter(section=section, is_active=True)
                ],
                "business_vocabulary": [
                    {
                        "business_term": item.business_term,
                        "business_definition": item.business_definition,
                        "category": item.category,
                    }
                    for item in AIBusinessVocabulary.objects.filter(section=section, is_active=True)
                ] + [
                    {
                        "business_term": item.term,
                        "business_definition": item.business_definition,
                        "category": item.category,
                        "related_kpi": item.related_kpi,
                    }
                    for item in KnowledgeBusinessGlossary.objects.filter(section=section, validation_status="Validated", is_active=True)
                ],
                "few_shot_examples": [
                    {
                        "question": item.question,
                        "expected_json_intent": item.expected_json_intent,
                        "expected_dax": item.expected_dax,
                        "expected_response": item.expected_response,
                        "explanation": item.explanation,
                    }
                    for item in AIFewShotExample.objects.filter(section=section, is_active=True)
                ],
                "business_rules": [
                    {
                        "metric_code": item.metric_code,
                        "rule_name": item.rule_name,
                        "condition": item.condition,
                        "action": item.action,
                        "default_value": item.default_value,
                        "priority": item.priority,
                    }
                    for item in AIBusinessRule.objects.filter(section=section, is_active=True)
                ] + [
                    {
                        "metric_code": item.kpi,
                        "rule_name": item.rule_name,
                        "condition": item.condition,
                        "action": item.rule_description or item.default_behavior,
                        "default_value": item.default_behavior,
                        "priority": 100,
                    }
                    for item in KnowledgeBusinessRule.objects.filter(section=section, validation_status="Validated", is_active=True)
                ],
                "visual_mappings": [
                    {
                        "metric_code": item.metric_code,
                        "recommended_visual": item.recommended_visual,
                        "priority": item.priority,
                    }
                    for item in AIVisualMapping.objects.filter(section=section, is_active=True)
                ],
                "kpi_targets": [
                    {
                        "metric_code": item.metric_code,
                        "target": str(item.target),
                        "warning_threshold": str(item.warning_threshold),
                        "critical_threshold": str(item.critical_threshold),
                        "unit": item.unit,
                    }
                    for item in AIKPITarget.objects.filter(section=section, is_active=True)
                ] + [
                    {
                        "metric_code": item.kpi_code,
                        "target": str(item.target or ""),
                        "warning_threshold": str(item.warning_threshold or ""),
                        "critical_threshold": str(item.critical_threshold or ""),
                        "unit": item.unit,
                    }
                    for item in KnowledgeKPIDictionary.objects.filter(section=section, validation_status="Validated", is_active=True)
                ],
                "recommended_actions": [
                    {
                        "metric_code": item.metric_code,
                        "condition": item.condition,
                        "recommendations": item.recommendations,
                        "priority": item.priority,
                    }
                    for item in AIRecommendedAction.objects.filter(section=section, is_active=True)
                ] + [
                    {
                        "metric_code": item.kpi,
                        "condition": item.condition,
                        "recommendations": item.recommended_action,
                        "priority": item.priority,
                    }
                    for item in KnowledgeRecommendedAction.objects.filter(section=section, validation_status="Validated", is_active=True)
                ],
            }
        )
    return {"sections": payload}


def serialize_active_glossary(section_code: str | None = None) -> dict:
    section = get_section_by_code(section_code) if section_code else None
    if section_code and not section:
        return {}
    sections = [section] if section else list(_section_queryset().filter(is_active=True))
    glossary = defaultdict(lambda: defaultdict(list))
    for item in AISynonym.objects.filter(section__in=sections, is_active=True).select_related("section"):
        glossary[item.section.code][item.entity_type].append(
            {
                "canonical_value": item.canonical_value,
                "synonym_value": item.synonym_value,
                "language": item.language,
            }
        )
    return {section.code: dict(glossary[section.code]) for section in sections}
