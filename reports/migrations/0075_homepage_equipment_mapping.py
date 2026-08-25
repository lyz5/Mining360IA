from django.db import migrations


def seed_homepage_equipment_mapping(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIFilterMapping = apps.get_model("reports", "AIFilterMapping")
    section = AIConfigSection.objects.filter(code="performance").first()
    if not section:
        return
    AIFilterMapping.objects.update_or_create(
        section=section,
        filter_code="equipment",
        defaults={
            "filter_label": "Equipment",
            "powerbi_table_name": "EquipmentList_MiningProd",
            "powerbi_column_name": "Equipment",
            "data_type": "Text",
            "is_required": False,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0074_homepage_product_group_mappings")]

    operations = [migrations.RunPython(seed_homepage_equipment_mapping, migrations.RunPython.noop)]
