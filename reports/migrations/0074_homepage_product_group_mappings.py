from django.db import migrations


def seed_homepage_product_group_mappings(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIFilterMapping = apps.get_model("reports", "AIFilterMapping")
    section = AIConfigSection.objects.filter(code="performance").first()
    if not section:
        return
    mappings = {
        "homepage_product_group": ("Homepage Product Group", "PrimeMovers"),
        "homepage_model_reference": ("Homepage Model Reference", "Model"),
    }
    for code, (label, column) in mappings.items():
        AIFilterMapping.objects.update_or_create(
            section=section,
            filter_code=code,
            defaults={
                "filter_label": label,
                "powerbi_table_name": "ModelList_MiningProd",
                "powerbi_column_name": column,
                "data_type": "Text",
                "is_required": False,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0073_homepage_focus_customer_type_mappings")]

    operations = [
        migrations.RunPython(seed_homepage_product_group_mappings, migrations.RunPython.noop)
    ]
