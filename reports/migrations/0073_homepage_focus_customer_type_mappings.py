from django.db import migrations


def seed_homepage_scope_mappings(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIFilterMapping = apps.get_model("reports", "AIFilterMapping")
    section = AIConfigSection.objects.filter(code="performance").first()
    if not section:
        return
    mappings = {
        "focus": ("Focus", "Focus"),
        "customer_type": ("Customer Type", "CustomerType"),
    }
    for code, (label, column) in mappings.items():
        AIFilterMapping.objects.update_or_create(
            section=section,
            filter_code=code,
            defaults={
                "filter_label": label,
                "powerbi_table_name": "MineSiteList_MiningProd",
                "powerbi_column_name": column,
                "data_type": "Text",
                "is_required": False,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0072_homepage_availability_dax_templates")]

    operations = [migrations.RunPython(seed_homepage_scope_mappings, migrations.RunPython.noop)]
