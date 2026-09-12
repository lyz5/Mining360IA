from django.db import migrations


CAPABILITIES = [
    {
        "code": "fleet_inventory", "agent": "machine_performance", "domain": "machine_performance",
        "category": "fleet_equipment", "order": 10, "status": "Ready",
        "name_en": "Fleet & Equipment", "name_fr": "Flotte et équipements",
        "description_en": "View authorized Site fleets, find equipment and export fleet lists.",
        "description_fr": "Afficher les flottes autorisées, rechercher un équipement et exporter les listes.",
        "entities": ["minesite", "model", "equipment"],
        "operations": ["lookup", "group_by_model", "export", "follow_up"],
        "examples_en": ["Give me the {site} fleet.", "Show details for serial {serial_number}."],
        "examples_fr": ["Donne-moi la flotte de {site}.", "Affiche les informations du numéro de série {serial_number}."],
        "feature_flag": "ENABLE_FLEET_INVENTORY_CHAT", "export": True,
    },
    {
        "code": "fleet_performance", "agent": "machine_performance", "domain": "machine_performance",
        "category": "performance_reliability", "order": 20, "status": "Limited",
        "name_en": "Performance & Reliability", "name_fr": "Performance et fiabilité",
        "description_en": "Analyze configured Availability, MTBS, MTBF, MTTR and downtime metrics.",
        "description_fr": "Analyser la disponibilité, le MTBS, le MTBF, le MTTR et les downtime configurés.",
        "entities": ["minesite", "model", "equipment"],
        "operations": ["value", "comparison", "trend", "ranking", "follow_up"],
        "examples_en": ["Show {site} fleet performance YTD.", "What is the MTBF of {equipment}?"],
        "examples_fr": ["Affiche la performance YTD de {site}.", "Quel est le MTBF de {equipment} ?"],
        "feature_flag": "ENABLE_COMPLETE_FLEET_PERFORMANCE_CHAT", "trend": True,
        "comparison": True, "ranking": True,
    },
    {
        "code": "downtime_analysis", "agent": "machine_performance", "domain": "machine_performance",
        "category": "downtime_causes", "order": 30, "status": "Limited",
        "name_en": "Downtime & Causes", "name_fr": "Downtime et causes",
        "description_en": "Identify configured downtime drivers, affected equipment and component evidence.",
        "description_fr": "Identifier les downtime drivers, équipements impactés et composants configurés.",
        "entities": ["minesite", "model", "equipment"],
        "operations": ["drivers", "ranking", "root_cause_explorer"],
        "examples_en": ["Show {site} top downtime drivers.", "Analyze downtime for {equipment}."],
        "examples_fr": ["Affiche les principaux downtime drivers de {site}.", "Analyse le downtime de {equipment}."],
        "requires_validated_report": True, "ranking": True,
    },
    {
        "code": "validated_knowledge", "agent": "mining_knowledge", "domain": "mining_knowledge",
        "category": "knowledge", "order": 40, "status": "Limited",
        "name_en": "Knowledge & Best Practices", "name_fr": "Knowledge et Best Practices",
        "description_en": "Search validated Mining 360 documents, KPI definitions and recommendations.",
        "description_fr": "Rechercher les documents, définitions KPI et recommandations validés dans Mining 360.",
        "entities": [], "operations": ["search", "definition", "citation"],
        "examples_en": ["What is MTBF?", "Show validated preventive maintenance best practices."],
        "examples_fr": ["C’est quoi le MTBF ?", "Affiche les Best Practices validées de maintenance préventive."],
        "requires_validated_knowledge": True,
    },
    {
        "code": "reporting_navigation", "agent": "machine_performance", "domain": "reporting",
        "category": "reporting", "order": 50, "status": "Ready",
        "name_en": "Reporting", "name_fr": "Reporting",
        "description_en": "Find and open authorized reports and configured Power BI pages.",
        "description_fr": "Rechercher et ouvrir les rapports et pages Power BI autorisés.",
        "entities": ["minesite", "model", "equipment"], "operations": ["search", "navigation"],
        "examples_en": ["Open the Fleet Performance report.", "Open the Benchmark page."],
        "examples_fr": ["Ouvre le rapport Fleet Performance.", "Ouvre la page Benchmark."],
        "requires_validated_report": True, "permissions": ["module:reporting"], "navigation": True,
    },
]


FIELDS = [
    ("site", "Site", "Site", ["MineSite", "mine site"], "Site", "Text", False),
    ("equipment", "Equipment", "Équipement", ["machine", "engin", "equipment code"], "Equipment", "Text", False),
    ("model", "Model", "Modèle", ["equipment model", "modèle d’équipement"], "Model", "Text", True),
    ("serial_number", "Serial Number", "Numéro de série", ["serial", "serial no", "SN", "S/N", "numéro de série"], "SN", "Text", True),
    ("equipment_family", "Equipment Family", "Famille d’équipement", ["parent product group", "famille machine"], "ParentProductGroup", "Text", True),
    ("brand", "Brand", "Marque", ["manufacturer", "constructeur"], "Brand", "Text", True),
    ("equipment_id", "Equipment ID", "Identifiant équipement", ["EquipID", "identifiant machine"], "EquipID", "Text", True),
    ("smu", "SMU", "SMU", ["service meter", "hours meter", "compteur horaire"], "SMU.SMU", "Decimal", True),
]


ABSTENTION_TEMPLATES = [
    ("capability_overview", "Capability Overview", "capability_overview"),
    ("information_not_available", "Information Not Available", "answerability"),
    ("field_value_missing", "Field Value Missing", "answerability"),
    ("entity_not_found", "Entity Not Found", "answerability"),
    ("access_restricted", "Access Restricted", "answerability"),
    ("temporarily_unavailable", "Temporarily Unavailable", "answerability"),
    ("insufficient_evidence", "Insufficient Evidence", "answerability"),
    ("conflicting_sources", "Conflicting Sources", "answerability"),
    ("capability_not_configured", "Capability Not Configured", "answerability"),
    ("out_of_scope", "Out of Scope", "answerability"),
    ("unsupported_action", "Unsupported Action", "answerability"),
]


def seed(apps, schema_editor):
    AIAgent = apps.get_model("reports", "AIAgent")
    AIAgentCapability = apps.get_model("reports", "AIAgentCapability")
    AIAgentIntent = apps.get_model("reports", "AIAgentIntent")
    BusinessDataField = apps.get_model("reports", "BusinessDataField")
    AIAnswerabilityConfiguration = apps.get_model("reports", "AIAnswerabilityConfiguration")
    AIResponseTemplate = apps.get_model("reports", "AIResponseTemplate")

    agents = {
        agent.code: agent for agent in AIAgent.objects.filter(
            code__in=["machine_performance", "mining_knowledge"]
        )
    }

    for item in CAPABILITIES:
        if item["agent"] not in agents:
            continue
        configuration = {
            key: item[key] for key in ("feature_flag", "requires_validated_report", "requires_validated_knowledge")
            if item.get(key)
        }
        AIAgentCapability.objects.update_or_create(
            agent=agents[item["agent"]], capability_code=item["code"],
            defaults={
                "display_name": item["name_en"], "description": item["description_en"],
                "domain_code": item["domain"], "category": item["category"],
                "display_name_en": item["name_en"], "display_name_fr": item["name_fr"],
                "short_description_en": item["description_en"], "short_description_fr": item["description_fr"],
                "supported_entities_json": item["entities"], "supported_operations_json": item["operations"],
                "required_permissions_json": item.get("permissions", []),
                "example_questions_en_json": item["examples_en"], "example_questions_fr_json": item["examples_fr"],
                "supports_comparison": item.get("comparison", False), "supports_trend": item.get("trend", False),
                "supports_ranking": item.get("ranking", False), "supports_export": item.get("export", False),
                "supports_navigation": item.get("navigation", False), "supports_follow_up": True,
                "readiness_score": 100 if item["status"] == "Ready" else 80,
                "readiness_status": item["status"], "display_order": item["order"],
                "enabled": True, "configuration_json": configuration, "priority": 100 - item["order"],
                "validation_status": "Validated",
            },
        )

    for code in (
        "capability_overview", "capability_by_domain", "capability_for_current_context", "help_request",
        "equipment_field_lookup", "information_not_in_configured_sources", "field_available_but_value_missing",
        "entity_not_found", "access_restricted", "temporarily_unavailable", "insufficient_evidence",
        "conflicting_sources", "unsupported_action", "out_of_scope", "low_confidence_abstention",
    ):
        if "machine_performance" in agents:
            AIAgentIntent.objects.update_or_create(
                agent=agents["machine_performance"], intent_code=code,
                defaults={"display_name": code.replace("_", " ").title(), "enabled": True, "validation_status": "Validated"},
            )

    for code, en, fr, synonyms, column, data_type, nullable in FIELDS:
        BusinessDataField.objects.update_or_create(
            canonical_field_code=code, entity_type="equipment",
            defaults={
                "display_name_en": en, "display_name_fr": fr, "synonyms_json": synonyms,
                "data_type": data_type, "source_type": "semantic_column",
                "table_name": "EquipmentList_MiningProd", "column_name": column,
                "nullable": nullable, "configuration_status": "Configured", "active": True,
                "validation_status": "Validated", "source_priority": 10,
            },
        )
    BusinessDataField.objects.update_or_create(
        canonical_field_code="commissioning_date", entity_type="equipment",
        defaults={
            "display_name_en": "Commissioning Date", "display_name_fr": "Date de mise en service",
            "description": "Validated date on which an equipment unit entered operational service.",
            "synonyms_json": [
                "commissioning date", "in-service date", "service start date", "date placed in service",
                "operational start date", "commissioned", "placed in service",
                "date de mise en service", "date mise en service", "mis en service", "mise en service",
                "date d’entrée en service", "date d'activation de la machine", "date de démarrage de l’équipement",
            ],
            "data_type": "Date", "source_type": "none", "nullable": True,
            "configuration_status": "Not Configured", "active": True,
            "validation_status": "Validated", "source_priority": 10,
        },
    )
    AIAnswerabilityConfiguration.objects.get_or_create(name="Default")
    for code, name, component in ABSTENTION_TEMPLATES:
        AIResponseTemplate.objects.update_or_create(
            code=code,
            defaults={
                "name": name, "description": "Deterministic governed chatbot response.",
                "domain": "conversation", "supported_intent_types": [code],
                "primary_component": component, "component_order_json": [component],
                "active": True, "validation_status": "Validated", "version": "1.0",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0102_chatbot_capability_answerability")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
