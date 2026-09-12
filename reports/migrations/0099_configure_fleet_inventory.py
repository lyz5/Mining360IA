from django.db import migrations


FIELD_MAPPINGS = (
    ("fleet_site", "Fleet Site", "Site"),
    ("fleet_equipment", "Fleet Equipment", "Equipment"),
    ("fleet_model", "Fleet Model", "Model"),
    ("fleet_family", "Fleet Equipment Family", "ParentProductGroup"),
    ("fleet_serial_number", "Fleet Serial Number", "SN"),
    ("fleet_brand", "Fleet Brand", "Brand"),
    ("fleet_equipment_id", "Fleet Equipment ID", "EquipID"),
    ("fleet_status", "Fleet Status", "Status"),
    ("fleet_smu", "Fleet SMU", "SMU.SMU"),
)

INTENT_TEMPLATES = {
    "get_site_fleet": "fleet_site_inventory",
    "get_site_fleet_by_model": "fleet_site_inventory",
    "get_site_model_fleet": "fleet_model_inventory",
    "get_fleet_count": "fleet_count_summary",
    "lookup_equipment_by_serial": "equipment_master_detail",
    "lookup_equipment_by_code": "equipment_master_detail",
}

TEMPLATES = {
    "fleet_site_inventory": ["fleet_summary", "fleet_model_summary", "fleet_equipment_table", "contextual_actions"],
    "fleet_model_inventory": ["fleet_summary", "fleet_equipment_table", "contextual_actions"],
    "fleet_count_summary": ["fleet_summary", "fleet_model_summary", "contextual_actions"],
    "equipment_master_detail": ["equipment_master_detail", "contextual_actions"],
}

SYNONYMS = {
    "fleet": {
        "fr": ("flotte", "parc", "parc machines", "parc d'équipements", "parc matériel", "liste des machines", "liste des équipements", "composition de la flotte"),
        "en": ("fleet", "equipment fleet", "machine fleet", "asset fleet", "fleet inventory", "equipment inventory", "machine inventory", "equipment list", "machine list", "fleet composition"),
    },
    "equipment": {
        "fr": ("engin", "équipement", "matériel"),
        "en": ("equipment", "machine", "asset", "unit"),
    },
    "serial_number": {
        "fr": ("numéro de série", "numero de serie", "série"),
        "en": ("serial", "serial number", "serial no", "SN", "S/N"),
    },
    "model": {"fr": ("modèle", "modèle d'équipement"), "en": ("model", "equipment model")},
}


def configure_fleet_inventory(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIFilterMapping = apps.get_model("reports", "AIFilterMapping")
    AIDaxTemplate = apps.get_model("reports", "AIDaxTemplate")
    AIResponseTemplate = apps.get_model("reports", "AIResponseTemplate")
    AIIntentResponseTemplateMapping = apps.get_model("reports", "AIIntentResponseTemplateMapping")
    KnowledgeSynonym = apps.get_model("reports", "KnowledgeSynonym")
    section = AIConfigSection.objects.get(code="performance")
    for code, label, column in FIELD_MAPPINGS:
        AIFilterMapping.objects.update_or_create(
            section=section,
            filter_code=code,
            defaults={
                "filter_label": label,
                "powerbi_table_name": "EquipmentList_MiningProd",
                "powerbi_column_name": column,
                "data_type": "Text" if code != "fleet_smu" else "Decimal",
                "is_required": False,
                "is_active": True,
            },
        )
    dax_templates = {
        "FLEET_SITE_DETAILS": "Governed EquipmentList_MiningProd detail query bound to validated Site.",
        "FLEET_SITE_MODEL_DETAILS": "Governed equipment detail query bound to validated Site and exact Model text.",
        "EQUIPMENT_BY_SERIAL": "Governed exact Serial Number lookup with controlled normalized fallback.",
        "EQUIPMENT_BY_CODE": "Governed exact Equipment identifier lookup.",
        "FLEET_DISTINCT_VALUES": "Governed distinct Site and Model value resolution query.",
    }
    for code, description in dax_templates.items():
        AIDaxTemplate.objects.update_or_create(
            section=section,
            template_code=code,
            defaults={"template_name": code.replace("_", " ").title(), "dax_template": description, "description": description, "is_active": True},
        )
    created_templates = {}
    for code, components in TEMPLATES.items():
        template, _ = AIResponseTemplate.objects.update_or_create(
            code=code,
            defaults={
                "name": code.replace("_", " ").title(),
                "description": "Deterministic Fleet Inventory response from EquipmentList_MiningProd.",
                "domain": "machine_performance",
                "supported_intent_types": [intent for intent, mapped in INTENT_TEMPLATES.items() if mapped == code],
                "primary_component": components[0],
                "component_order_json": components,
                "required_data_fields_json": ["equipment_identity"] if code == "equipment_master_detail" else ["rows"],
                "fallback_template_code": "generic_analytical",
                "active": True,
                "validation_status": "Validated",
                "version": "1.0",
            },
        )
        created_templates[code] = template
    for intent, code in INTENT_TEMPLATES.items():
        AIIntentResponseTemplateMapping.objects.update_or_create(
            domain="machine_performance", intent_type=intent, scope_type="", metric_code="", response_template=created_templates[code],
            defaults={"priority": 200, "active": True, "validation_status": "Validated"},
        )
    entity_types = {"fleet": "Business Term", "equipment": "Business Term", "serial_number": "Serial Number", "model": "Model"}
    for canonical, languages in SYNONYMS.items():
        for language, values in languages.items():
            for synonym in values:
                KnowledgeSynonym.objects.update_or_create(
                    section=section, entity_type=entity_types[canonical], language=language, synonym=synonym,
                    defaults={
                        "canonical_term": canonical,
                        "normalized_value": canonical,
                        "validation_status": "To Review",
                        "synonym_source": "System Generated",
                        "match_type": "Phrase",
                        "confidence": 100,
                        "resolution_priority": 70,
                        "is_active": True,
                    },
                )


def remove_fleet_inventory(apps, schema_editor):
    section = apps.get_model("reports", "AIConfigSection").objects.filter(code="performance").first()
    if not section:
        return
    apps.get_model("reports", "AIFilterMapping").objects.filter(section=section, filter_code__in=[item[0] for item in FIELD_MAPPINGS]).delete()
    apps.get_model("reports", "AIDaxTemplate").objects.filter(section=section, template_code__in=["FLEET_SITE_DETAILS", "FLEET_SITE_MODEL_DETAILS", "EQUIPMENT_BY_SERIAL", "EQUIPMENT_BY_CODE", "FLEET_DISTINCT_VALUES"]).delete()
    apps.get_model("reports", "AIIntentResponseTemplateMapping").objects.filter(domain="machine_performance", intent_type__in=INTENT_TEMPLATES).delete()
    apps.get_model("reports", "AIResponseTemplate").objects.filter(code__in=TEMPLATES).delete()
    apps.get_model("reports", "KnowledgeSynonym").objects.filter(section=section, synonym_source="System Generated", canonical_term__in=SYNONYMS).delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0098_add_minesite_access_level")]
    operations = [migrations.RunPython(configure_fleet_inventory, remove_fleet_inventory)]
