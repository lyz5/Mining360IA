from django.db import migrations


QUESTIONS = (
    ("C'est quoi la flotte de Fekola ?", "fr", "get_site_fleet", {"minesite": "Fekola"}),
    ("Give me the Fekola fleet.", "en", "get_site_fleet", {"minesite": "Fekola"}),
    ("Show the Fekola fleet by model.", "en", "get_site_fleet_by_model", {"minesite": "Fekola"}),
    ("Give me the Fekola 777 fleet.", "en", "get_site_model_fleet", {"minesite": "Fekola", "model": "777"}),
    ("Give me details for serial L7K00442.", "en", "lookup_equipment_by_serial", {"serial_number": "L7K00442"}),
    ("Where is APX01656?", "en", "lookup_equipment_by_serial", {"serial_number": "APX01656"}),
)


def complete_configuration(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIDaxTemplate = apps.get_model("reports", "AIDaxTemplate")
    AIQuestionExample = apps.get_model("reports", "AIQuestionExample")
    AIResponseTemplate = apps.get_model("reports", "AIResponseTemplate")
    AIIntentResponseTemplateMapping = apps.get_model("reports", "AIIntentResponseTemplateMapping")
    section = AIConfigSection.objects.get(code="performance")
    query_templates = {
        "FLEET_SITE_DETAILS": "EVALUATE CALCULATETABLE(SUMMARIZE('EquipmentList_MiningProd', 'EquipmentList_MiningProd'[Site], 'EquipmentList_MiningProd'[Equipment], 'EquipmentList_MiningProd'[Model], 'EquipmentList_MiningProd'[SN]), TREATAS({{{site}}}, 'EquipmentList_MiningProd'[Site]))",
        "FLEET_SITE_MODEL_DETAILS": "EVALUATE CALCULATETABLE(SUMMARIZE('EquipmentList_MiningProd', 'EquipmentList_MiningProd'[Site], 'EquipmentList_MiningProd'[Equipment], 'EquipmentList_MiningProd'[Model], 'EquipmentList_MiningProd'[SN]), TREATAS({{{site}}}, 'EquipmentList_MiningProd'[Site]), TREATAS({{{model}}}, 'EquipmentList_MiningProd'[Model]))",
        "EQUIPMENT_BY_SERIAL": "EVALUATE CALCULATETABLE(SUMMARIZE('EquipmentList_MiningProd', 'EquipmentList_MiningProd'[Site], 'EquipmentList_MiningProd'[Equipment], 'EquipmentList_MiningProd'[Model], 'EquipmentList_MiningProd'[SN]), TREATAS({{{serial_number}}}, 'EquipmentList_MiningProd'[SN]))",
        "EQUIPMENT_BY_CODE": "EVALUATE CALCULATETABLE(SUMMARIZE('EquipmentList_MiningProd', 'EquipmentList_MiningProd'[Site], 'EquipmentList_MiningProd'[Equipment], 'EquipmentList_MiningProd'[Model], 'EquipmentList_MiningProd'[SN]), TREATAS({{{equipment}}}, 'EquipmentList_MiningProd'[Equipment]))",
    }
    for code, dax in query_templates.items():
        AIDaxTemplate.objects.filter(section=section, template_code=code).update(dax_template=dax)
    export_template, _ = AIResponseTemplate.objects.update_or_create(
        code="fleet_export_confirmation",
        defaults={
            "name": "Fleet Export Confirmation",
            "description": "Confirmation for an export generated from a saved authorized Fleet artifact.",
            "domain": "machine_performance",
            "supported_intent_types": ["export_current_fleet"],
            "primary_component": "fleet_export_confirmation",
            "component_order_json": ["fleet_export_confirmation", "contextual_actions"],
            "required_data_fields_json": ["rows"],
            "fallback_template_code": "fleet_site_inventory",
            "active": True,
            "validation_status": "Validated",
            "version": "1.0",
        },
    )
    AIIntentResponseTemplateMapping.objects.update_or_create(
        domain="machine_performance", intent_type="export_current_fleet", scope_type="", metric_code="", response_template=export_template,
        defaults={"priority": 200, "active": True, "validation_status": "Validated"},
    )
    for question, language, intent_type, filters in QUESTIONS:
        AIQuestionExample.objects.update_or_create(
            section=section, question_text=question,
            defaults={
                "language": language,
                "expected_json_intent": {"section": "performance", "intent_type": intent_type, "metric": None, "filters": filters},
                "is_active": True,
            },
        )


def remove_configuration(apps, schema_editor):
    section = apps.get_model("reports", "AIConfigSection").objects.filter(code="performance").first()
    if not section:
        return
    apps.get_model("reports", "AIQuestionExample").objects.filter(section=section, question_text__in=[item[0] for item in QUESTIONS]).delete()
    apps.get_model("reports", "AIIntentResponseTemplateMapping").objects.filter(domain="machine_performance", intent_type="export_current_fleet").delete()
    apps.get_model("reports", "AIResponseTemplate").objects.filter(code="fleet_export_confirmation").delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0099_configure_fleet_inventory")]
    operations = [migrations.RunPython(complete_configuration, remove_configuration)]
