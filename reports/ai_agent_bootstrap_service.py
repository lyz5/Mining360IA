from __future__ import annotations

from django.db import transaction

from .models import (
    AIAgent,
    AIAgentCapability,
    AIAgentDataSource,
    AIAgentIntent,
    AIAgentPermission,
    AIAgentPrompt,
    AIAgentRoutingConfiguration,
    AIAgentRoutingRule,
    AIAgentTool,
    SystemParameter,
)


MACHINE_SYSTEM_PROMPT = """You are the Mining 360 Machine Performance Agent.

Analyze operational mining equipment data using approved Power BI semantic
models and configured business knowledge. Use only configured measures,
filters, DAX templates and Power BI mappings. Never invent a KPI, value,
target, filter or DAX expression. If required filters are missing or
ambiguous, ask for clarification."""

KNOWLEDGE_SYSTEM_PROMPT = """You are the Mining 360 Mining Knowledge Agent.

Answer questions using approved Best Practices, procedures, terminology,
business rules and knowledge documents. Use only retrieved sources. Preserve
traceability and cite the document, section and page when available. Do not
invent a procedure, recommendation or technical rule. State clearly when
sources are insufficient or conflicting."""

COMBINED_PROMPT = """Combine operational findings and documentary guidance
without mixing their sources. Structure the response into Operational
Findings, Best-Practice Guidance, Recommended Next Analysis, and Sources.
Never present documentary guidance as observed operational fact."""


AGENT_DEFINITIONS = {
    "machine_performance": {
        "name": "Machine Performance",
        "description": (
            "Analyze fleet KPIs, equipment performance, downtime, failures, "
            "trends and operational root causes using approved Power BI semantic models."
        ),
        "priority": 100,
        "system_prompt": MACHINE_SYSTEM_PROMPT,
        "capabilities": [
            "kpi_query", "trend_analysis", "comparison", "ranking",
            "downtime_analysis", "root_cause_explorer", "equipment_analysis",
            "event_analysis", "smcs_analysis", "powerbi_navigation",
            "recommended_operational_actions",
        ],
        "intents": [
            "get_kpi_value", "show_kpi_trend", "compare_kpi", "rank_entities",
            "show_downtime_drivers", "open_downtime_root_cause",
            "show_affected_equipment", "show_downtime_events", "analyze_comments",
            "show_repeated_failures", "show_smcs_components", "open_powerbi_report",
        ],
        "tools": {
            "powerbi_query": "reports.powerbi_interaction_orchestrator.process_user_question",
            "metrics_mapping": "reports.ai_config_service.get_metric_mapping",
            "filters_mapping": "reports.ai_config_service.get_filter_mapping",
            "dax_template": "reports.dax_generator_service.generate_dax_from_intent",
            "downtime_root_cause": "reports.downtime_explorer_service.DowntimeRootCauseExplorerService",
            "smcs_classification": "reports.downtime_smcs_classification_service.DowntimeSMCSClassificationService",
            "powerbi_navigation": "reports.powerbi_interaction_service.resolve_navigation",
        },
        "sources": [
            ("semantic_model", "configured", "Approved Power BI Semantic Models"),
            ("kpi_dictionary", "validated", "Validated KPI Dictionary"),
            ("synonym_library", "validated", "Validated Synonym Library"),
            ("dax_templates", "validated", "Validated DAX Templates"),
            ("powerbi_interaction", "validated", "Power BI Interaction"),
            ("business_rules", "operational_validated", "Validated Operational Business Rules"),
            ("smcs_reference", "validated", "Validated SMCS Reference"),
        ],
    },
    "mining_knowledge": {
        "name": "Mining Knowledge",
        "description": (
            "Search and explain validated mining best practices, procedures, "
            "terminology, business rules and technical knowledge from approved resources."
        ),
        "priority": 90,
        "system_prompt": KNOWLEDGE_SYSTEM_PROMPT,
        "capabilities": [
            "document_search", "best_practice_answer", "glossary_lookup",
            "terminology_lookup", "procedure_search", "business_rule_search",
            "recommendation_search", "source_citation", "document_summary",
        ],
        "intents": [
            "search_best_practice", "define_business_term", "explain_mining_term",
            "search_procedure", "summarize_document", "find_recommendation",
            "find_business_rule", "compare_documents", "show_source_reference",
        ],
        "tools": {
            "knowledge_search": "reports.resource_knowledge_search_service.search_resource_knowledge",
            "knowledge_document": "reports.models.ResourceKnowledgeDocument",
            "knowledge_citation": "reports.resource_knowledge_search_service.search_resource_knowledge",
            "business_glossary": "reports.models.KnowledgeBusinessGlossary",
            "mining_terminology": "reports.models.KnowledgeMiningTerminology",
            "business_rules": "reports.models.KnowledgeBusinessRule",
            "recommended_actions": "reports.models.KnowledgeRecommendedAction",
        },
        "sources": [
            ("knowledge_resource_category", "Best Practices", "Best Practices Resources"),
            ("knowledge_document", "validated", "Validated Knowledge Documents"),
            ("business_glossary", "validated", "Validated Business Glossary"),
            ("mining_terminology", "validated", "Validated Mining Terminology"),
            ("business_rules", "validated", "Validated Business Rules"),
            ("synonym_library", "validated", "Validated Synonym Library"),
        ],
    },
}


ROUTING_RULES = [
    {
        "rule_code": "operational_and_recommendation",
        "name": "Operational analysis with documentary guidance",
        "selected_agent": "combined",
        "priority": 110,
        "condition_json": {"requires": ["operational_signal", "knowledge_signal"]},
    },
    {
        "rule_code": "kpi_or_operational_filter",
        "name": "KPI or operational filter",
        "selected_agent": "machine_performance",
        "priority": 100,
        "condition_json": {"requires": ["operational_signal"]},
    },
    {
        "rule_code": "best_practice_or_document",
        "name": "Best Practice or document request",
        "selected_agent": "mining_knowledge",
        "priority": 100,
        "condition_json": {"requires": ["knowledge_signal"]},
    },
    {
        "rule_code": "ambiguous_business_concept",
        "name": "Ambiguous business concept",
        "selected_agent": "clarification_required",
        "priority": 80,
        "condition_json": {"requires": ["ambiguous_concept"]},
    },
]


def _title(code: str) -> str:
    return code.replace("_", " ").title()


def _parameter(key, label, value, value_type="Boolean"):
    SystemParameter.objects.get_or_create(
        key=key,
        defaults={
            "category": "AI Agents",
            "label": label,
            "description": "Multi-agent runtime configuration.",
            "value_type": value_type,
            "value_json": value,
            "default_value_json": value,
            "is_runtime_editable": True,
            "is_active": True,
        },
    )


@transaction.atomic
def bootstrap_ai_agents(*, user=None) -> dict:
    created_agents = 0
    counters = {"capabilities": 0, "intents": 0, "tools": 0, "sources": 0, "prompts": 0}
    agents = {}
    for code, definition in AGENT_DEFINITIONS.items():
        agent, created = AIAgent.objects.get_or_create(
            code=code,
            defaults={
                "name": definition["name"],
                "description": definition["description"],
                "agent_type": code,
                "system_instructions": definition["system_prompt"],
                "response_instructions": (
                    "Return a factual, concise response and preserve source separation."
                ),
                "clarification_instructions": (
                    "Ask a concise clarification question when required context is missing."
                ),
                "combined_execution_instructions": COMBINED_PROMPT,
                "priority": definition["priority"],
                "minimum_confidence": 85,
                "active": True,
                "allow_combined_execution": True,
                "validation_status": "To Review",
                "created_by": user if getattr(user, "is_authenticated", False) else None,
                "updated_by": user if getattr(user, "is_authenticated", False) else None,
            },
        )
        created_agents += int(created)
        agents[code] = agent
        AIAgentPermission.objects.get_or_create(
            agent=agent,
            defaults={
                "can_export": code == "machine_performance",
                "can_access_comments": code == "machine_performance",
                "can_access_debug": False,
            },
        )
        for priority, capability in enumerate(definition["capabilities"], start=1):
            _, made = AIAgentCapability.objects.get_or_create(
                agent=agent,
                capability_code=capability,
                defaults={
                    "display_name": _title(capability),
                    "priority": 200 - priority,
                    "validation_status": "To Review",
                },
            )
            counters["capabilities"] += int(made)
        for priority, intent in enumerate(definition["intents"], start=1):
            _, made = AIAgentIntent.objects.get_or_create(
                agent=agent,
                intent_code=intent,
                defaults={
                    "display_name": _title(intent),
                    "priority": 200 - priority,
                    "validation_status": "To Review",
                },
            )
            counters["intents"] += int(made)
        for priority, (tool_code, service_path) in enumerate(definition["tools"].items(), start=1):
            _, made = AIAgentTool.objects.get_or_create(
                agent=agent,
                tool_code=tool_code,
                defaults={
                    "display_name": _title(tool_code),
                    "service_path": service_path,
                    "priority": 200 - priority,
                    "validation_status": "To Review",
                },
            )
            counters["tools"] += int(made)
        for priority, (source_type, reference, name) in enumerate(definition["sources"], start=1):
            _, made = AIAgentDataSource.objects.get_or_create(
                agent=agent,
                source_type=source_type,
                source_reference=reference,
                defaults={
                    "source_name": name,
                    "priority": 200 - priority,
                    "read_only": True,
                    "validation_status": "To Review",
                },
            )
            counters["sources"] += int(made)
        prompt_seeds = [
            ("system", "system", f"{code}-system", definition["system_prompt"]),
            ("response", "response", f"{code}-response", agent.response_instructions),
            ("clarification", "clarification", f"{code}-clarification", agent.clarification_instructions),
            ("combined", "combined", f"{code}-combined", COMBINED_PROMPT),
        ]
        for prompt_type, name, prompt_code, content in prompt_seeds:
            _, made = AIAgentPrompt.objects.get_or_create(
                agent=agent,
                prompt_code=prompt_code,
                defaults={
                    "prompt_type": prompt_type,
                    "name": _title(name),
                    "content": content,
                    "validation_status": "To Review",
                },
            )
            counters["prompts"] += int(made)

    config, _ = AIAgentRoutingConfiguration.objects.get_or_create(
        name="Default",
        defaults={
            "feature_mode": "Admin Only",
            "routing_enabled": True,
            "deterministic_routing_enabled": True,
            "ai_fallback_enabled": False,
            "default_agent": agents["machine_performance"],
            "minimum_confidence": 85,
            "combined_execution_enabled": True,
            "manual_selection_enabled": True,
            "clarification_behavior": (
                "Ask whether the user wants an operational value or documented guidance."
            ),
        },
    )
    created_rules = 0
    for rule in ROUTING_RULES:
        _, made = AIAgentRoutingRule.objects.get_or_create(
            rule_code=rule["rule_code"],
            defaults={**rule, "validation_status": "To Review", "active": True},
        )
        created_rules += int(made)

    _parameter("enable-multi-agent-architecture", "Enable Multi-Agent Architecture", "Admin Only", "Text")
    _parameter("enable-agent-router", "Enable Agent Router", True)
    _parameter("enable-combined-agent-execution", "Enable Combined Agent Execution", True)
    _parameter("enable-manual-agent-selection", "Enable Manual Agent Selection", True)
    _parameter("agent-router-minimum-confidence", "Agent Router Minimum Confidence", 85, "Integer")
    _parameter("agent-router-ai-fallback", "Agent Router AI Fallback", False)

    return {
        "agents_created": created_agents,
        "agents_total": len(agents),
        "routing_configuration_id": config.pk,
        "routing_rules_created": created_rules,
        **counters,
    }
