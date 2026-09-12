from django.db import migrations


def add_prime_mover_filter(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIFilterMapping = apps.get_model("reports", "AIFilterMapping")
    section = AIConfigSection.objects.filter(code="performance").first()
    if not section:
        return
    AIFilterMapping.objects.update_or_create(
        section=section,
        filter_code="product_group",
        defaults={
            "filter_label": "Equipment Family",
            "powerbi_table_name": "ModelList_MiningProd",
            "powerbi_column_name": "PrimeMovers",
            "data_type": "Text",
            "is_required": False,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0104_extend_commissioning_date_synonyms")]
    operations = [migrations.RunPython(add_prime_mover_filter, migrations.RunPython.noop)]
