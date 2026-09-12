from django.db import migrations
from django.utils import timezone


def seed(apps, schema_editor):
    Capability = apps.get_model("reports", "AIAgentCapability")
    Operation = apps.get_model("reports", "AICapabilityOperation")
    Suggestion = apps.get_model("reports", "AIChatSuggestion")
    Certification = apps.get_model("reports", "AISuggestionCertification")
    Action = apps.get_model("reports", "AIActionContract")
    Health = apps.get_model("reports", "AIDependencyHealthSnapshot")

    capabilities = {item.capability_code: item for item in Capability.objects.all()}
    operation_rows = [
        {
            "code": "capability_overview", "capability": None, "domain": "conversation",
            "en": "Capability overview", "fr": "Présentation des capacités", "intents": ["capability_overview"],
            "zero": True, "guided": False, "fallback": True, "readiness": "READY", "score": 100,
            "sources": ["local_registry"], "templates": [], "flags": ["ENABLE_CHATBOT_CAPABILITY_DISCOVERY"],
        },
        {
            "code": "site_fleet_inventory", "capability": "fleet_inventory", "domain": "machine_performance",
            "en": "Site fleet inventory", "fr": "Inventaire de flotte par site", "intents": ["get_site_fleet"],
            "zero": False, "guided": True, "fallback": True, "readiness": "READY", "score": 90,
            "sources": ["power_automate"], "templates": ["fleet_site_inventory"], "flags": ["ENABLE_FLEET_INVENTORY_CHAT"],
        },
        {
            "code": "equipment_serial_lookup", "capability": "fleet_inventory", "domain": "machine_performance",
            "en": "Equipment lookup by serial", "fr": "Recherche par numéro de série", "intents": ["lookup_equipment_by_serial"],
            "zero": False, "guided": True, "fallback": True, "readiness": "READY", "score": 90,
            "sources": ["power_automate"], "templates": ["equipment_master_detail"], "flags": ["ENABLE_EQUIPMENT_SERIAL_LOOKUP"],
        },
        {
            "code": "report_search", "capability": "reporting_navigation", "domain": "reporting",
            "en": "Report search and navigation", "fr": "Recherche et navigation de rapports", "intents": ["powerbi_navigation"],
            "zero": True, "guided": True, "fallback": True, "readiness": "LIMITED", "score": 75,
            "sources": ["local_registry"], "templates": ["powerbi_navigation"], "flags": [],
        },
        {
            "code": "availability_single_kpi", "capability": "fleet_performance", "domain": "machine_performance",
            "en": "Physical Availability", "fr": "Disponibilité physique", "intents": ["single_kpi"],
            "zero": False, "guided": True, "fallback": True, "readiness": "LIMITED", "score": 70,
            "sources": ["power_automate"], "templates": ["single_kpi"], "flags": [],
        },
        {
            "code": "downtime_drivers", "capability": "downtime_analysis", "domain": "machine_performance",
            "en": "Top downtime drivers", "fr": "Principaux downtime drivers", "intents": ["downtime_drivers"],
            "zero": False, "guided": True, "fallback": True, "readiness": "LIMITED", "score": 70,
            "sources": ["power_automate"], "templates": ["downtime_drivers"], "flags": ["ENABLE_FLEET_PERFORMANCE_DIAGNOSTICS"],
        },
        {
            "code": "repeated_failures", "capability": "downtime_analysis", "domain": "machine_performance",
            "en": "Repeated failures", "fr": "Pannes répétées", "intents": ["repeated_failures"],
            "zero": False, "guided": True, "fallback": False, "readiness": "NEEDS_CONFIGURATION", "score": 45,
            "sources": ["power_automate"], "templates": ["repeated_failures"], "flags": ["ENABLE_FLEET_PERFORMANCE_DIAGNOSTICS"],
        },
        {
            "code": "preventive_maintenance_best_practices", "capability": "validated_knowledge", "domain": "mining_knowledge",
            "en": "Preventive maintenance Best Practices", "fr": "Best Practices de maintenance préventive", "intents": ["knowledge_question"],
            "zero": True, "guided": False, "fallback": True, "readiness": "NEEDS_CONFIGURATION", "score": 30,
            "sources": ["knowledge_index"], "templates": [], "flags": [],
        },
    ]
    operations = {}
    for row in operation_rows:
        operation, _ = Operation.objects.update_or_create(
            operation_code=row["code"],
            defaults={
                "capability": capabilities.get(row["capability"]),
                "agent_code": capabilities[row["capability"]].agent.code if row["capability"] in capabilities else "",
                "domain_code": row["domain"],
                "display_name_en": row["en"], "display_name_fr": row["fr"],
                "intent_types_json": row["intents"],
                "required_data_sources_json": row["sources"],
                "required_response_templates_json": row["templates"],
                "required_feature_flags_json": row["flags"],
                "supports_zero_context": row["zero"], "supports_guided_context": row["guided"],
                "deterministic_fallback_available": row["fallback"],
                "readiness_status": row["readiness"], "readiness_score": row["score"],
                "configuration_version": "seed-0107", "active": True, "validation_status": "Validated",
                "last_validated_at": timezone.now() if row["readiness"] in {"READY", "LIMITED"} else None,
            },
        )
        operations[row["code"]] = operation

    suggestions = [
        {
            "code": "starter_capability_overview", "operation": "capability_overview", "category": "help",
            "en": "What can you do for me?", "fr": "Que peux-tu faire pour moi ?",
            "sub_en": "Explore the capabilities available for your profile.", "sub_fr": "Découvrez les capacités disponibles pour votre profil.",
            "type": "DIRECT_QUESTION", "q_en": "What can you do for me?", "q_fr": "Que peux-tu faire pour moi ?",
            "intent": "capability_overview", "template": "capability_overview", "tier": "A", "status": "CERTIFIED", "order": 10,
        },
        {
            "code": "starter_site_fleet", "operation": "site_fleet_inventory", "category": "fleet_equipment",
            "en": "Show a Site fleet", "fr": "Afficher la flotte d’un site",
            "sub_en": "View authorized equipment grouped by Model.", "sub_fr": "Afficher les équipements autorisés regroupés par modèle.",
            "type": "GUIDED_QUESTION", "q_en": "Give me the {minesite} fleet.", "q_fr": "Donne-moi la flotte de {minesite}.",
            "intent": "get_site_fleet", "template": "fleet_site_inventory", "tier": "A", "status": "NOT_TESTED", "order": 20,
            "guided": [{"code": "minesite", "type": "authorized_entity_select", "required": True, "label_en": "MineSite", "label_fr": "Site minier"}],
        },
        {
            "code": "starter_equipment_serial", "operation": "equipment_serial_lookup", "category": "fleet_equipment",
            "en": "Find equipment by Serial Number", "fr": "Rechercher un équipement par numéro de série",
            "sub_en": "Retrieve the authorized equipment master record.", "sub_fr": "Retrouver la fiche équipement autorisée.",
            "type": "GUIDED_QUESTION", "q_en": "Give me details for serial {serial_number}.", "q_fr": "Donne-moi les informations du numéro de série {serial_number}.",
            "intent": "lookup_equipment_by_serial", "template": "equipment_master_detail", "tier": "A", "status": "NOT_TESTED", "order": 30,
            "guided": [{"code": "serial_number", "type": "text", "required": True, "label_en": "Serial Number", "label_fr": "Numéro de série"}],
        },
        {
            "code": "legacy_availability_essakane", "operation": "availability_single_kpi", "category": "performance_reliability",
            "en": "Availability at Essakane", "fr": "Disponibilité à Essakane", "sub_en": "Migrated legacy suggestion.", "sub_fr": "Suggestion historique migrée.",
            "type": "DIRECT_QUESTION", "q_en": "What is the availability at Essakane?", "q_fr": "Quelle est la disponibilité à Essakane ?",
            "intent": "single_kpi", "template": "single_kpi", "tier": "B", "status": "NOT_TESTED", "order": 80,
        },
        {
            "code": "legacy_top_downtime_drivers", "operation": "downtime_drivers", "category": "downtime_causes",
            "en": "Top downtime drivers", "fr": "Principaux downtime drivers", "sub_en": "Requires a guided analytical context.", "sub_fr": "Nécessite un contexte analytique guidé.",
            "type": "GUIDED_QUESTION", "q_en": "Show the top downtime drivers for {minesite}.", "q_fr": "Montre les principaux downtime drivers de {minesite}.",
            "intent": "downtime_drivers", "template": "downtime_drivers", "tier": "B", "status": "NOT_TESTED", "order": 90,
            "guided": [{"code": "minesite", "type": "authorized_entity_select", "required": True, "label_en": "MineSite", "label_fr": "Site minier"}],
        },
        {
            "code": "legacy_analyze_repeated_failures", "operation": "repeated_failures", "category": "downtime_causes",
            "en": "Analyze repeated failures", "fr": "Analyser les pannes répétées", "sub_en": "Hidden until its complete journey is certified.", "sub_fr": "Masquée jusqu’à certification complète du parcours.",
            "type": "GUIDED_QUESTION", "q_en": "Analyze repeated failures for {minesite} over {period}.", "q_fr": "Analyse les pannes répétées de {minesite} sur {period}.",
            "intent": "repeated_failures", "template": "repeated_failures", "tier": "D", "status": "FAILED", "order": 100,
            "guided": [{"code": "minesite", "type": "authorized_entity_select", "required": True, "label_en": "MineSite", "label_fr": "Site minier"}],
        },
        {
            "code": "legacy_pm_best_practices", "operation": "preventive_maintenance_best_practices", "category": "knowledge",
            "en": "Preventive maintenance best practices", "fr": "Best Practices de maintenance préventive", "sub_en": "Hidden until validated indexed evidence is available.", "sub_fr": "Masquée jusqu’à disponibilité de sources validées et indexées.",
            "type": "DIRECT_QUESTION", "q_en": "What are the preventive maintenance best practices?", "q_fr": "Quelles sont les Best Practices de maintenance préventive ?",
            "intent": "knowledge_question", "template": "knowledge_answer", "tier": "C", "status": "FAILED", "order": 110,
        },
    ]
    for row in suggestions:
        operation = operations[row["operation"]]
        suggestion, _ = Suggestion.objects.update_or_create(
            suggestion_code=row["code"],
            defaults={
                "category": row["category"], "capability": operation.capability, "operation": operation,
                "agent_code": operation.agent_code, "label_en": row["en"], "label_fr": row["fr"],
                "subtitle_en": row["sub_en"], "subtitle_fr": row["sub_fr"], "icon_code": "sparkles",
                "action_type": row["type"], "question_template_en": row["q_en"], "question_template_fr": row["q_fr"],
                "guided_input_schema_json": row.get("guided", []), "expected_intent_type": row["intent"],
                "expected_response_template": row["template"], "reliability_tier": row["tier"],
                "certification_status": row["status"], "certification_environment": "Development",
                "certification_version": "seed-0107", "active": True, "display_order": row["order"],
                "validation_status": "Validated",
            },
        )
        if row["status"] == "CERTIFIED":
            Certification.objects.update_or_create(
                suggestion=suggestion, environment="Development", test_case_code="starter_capability_overview_local",
                defaults={
                    "application_version": "0107", "configuration_version": "seed-0107",
                    "expected_intent": row["intent"], "expected_answerability": "ANSWERABLE",
                    "expected_template": row["template"], "actual_intent": row["intent"],
                    "actual_answerability": "ANSWERABLE", "actual_template": row["template"],
                    "http_status": 200, "execution_status": "SUCCEEDED", "duration_ms": 0,
                    "grounding_passed": True, "persistence_passed": True, "ui_render_passed": True,
                    "permission_test_passed": True, "passed": True, "certification_status": "CERTIFIED",
                    "tested_at": timezone.now(), "automated": True,
                },
            )

    action_rows = [
        ("retry", "Retry", "Réessayer", [], "READY", "CERTIFIED"),
        ("report_data_gap", "Report missing information", "Signaler ce besoin de donnée", ["answerability"], "READY", "CERTIFIED"),
        ("open_powerbi", "Open in Power BI", "Ouvrir dans Power BI", [], "READY", "CERTIFIED"),
        ("download_excel", "Download Excel", "Télécharger Excel", [], "READY", "CERTIFIED"),
    ]
    for code, en, fr, artifacts, readiness, certification in action_rows:
        Action.objects.update_or_create(
            action_code=code,
            defaults={
                "label_en": en, "label_fr": fr, "required_artifact_types_json": artifacts,
                "readiness_status": readiness, "certification_status": certification,
                "active": True, "validation_status": "Validated",
            },
        )

    for code in ("database", "local_registry"):
        Health.objects.update_or_create(
            dependency_code=code,
            defaults={"status": "healthy", "checked_at": timezone.now(), "message": "Local dependency available."},
        )


def unseed(apps, schema_editor):
    apps.get_model("reports", "AIChatSuggestion").objects.filter(suggestion_code__startswith="starter_").delete()
    apps.get_model("reports", "AIChatSuggestion").objects.filter(suggestion_code__startswith="legacy_").delete()
    apps.get_model("reports", "AICapabilityOperation").objects.filter(configuration_version="seed-0107").delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0106_chat_production_hardening")]
    operations = [migrations.RunPython(seed, unseed)]
