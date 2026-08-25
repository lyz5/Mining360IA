from django.db import migrations


NEW_SITE_NAME = "Kouroussa/Corica"
LEGACY_SITE_NAME = "Kouroussa"


def add_site_alias(apps, schema_editor):
    PowerBISlicer = apps.get_model("reports", "PowerBISlicer")
    for slicer in PowerBISlicer.objects.all().iterator():
        mapping = dict(slicer.value_mapping or {})
        if LEGACY_SITE_NAME not in mapping:
            continue
        if NEW_SITE_NAME in mapping:
            continue
        mapping[NEW_SITE_NAME] = mapping[LEGACY_SITE_NAME]
        slicer.value_mapping = mapping
        slicer.save(update_fields=["value_mapping"])


def remove_site_alias(apps, schema_editor):
    PowerBISlicer = apps.get_model("reports", "PowerBISlicer")
    for slicer in PowerBISlicer.objects.all().iterator():
        mapping = dict(slicer.value_mapping or {})
        if NEW_SITE_NAME not in mapping:
            continue
        mapping.pop(NEW_SITE_NAME, None)
        slicer.value_mapping = mapping
        slicer.save(update_fields=["value_mapping"])


class Migration(migrations.Migration):
    dependencies = [("reports", "0085_premium_generic_report_viewer")]

    operations = [migrations.RunPython(add_site_alias, remove_site_alias)]
