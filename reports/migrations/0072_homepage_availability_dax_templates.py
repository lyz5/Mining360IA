from django.db import migrations


TEMPLATES = [
    (
        "HOME_AVAILABILITY_COMMAND_CENTER",
        "Homepage Availability Command Center",
        "{{QUERY_DEFINITIONS}}\nEVALUATE\n{{QUERY_RESULT}}",
        "Controlled wrapper for the aggregated homepage summary, monthly trend, breakdown and filter options query.",
    ),
    (
        "HOME_AVAILABILITY_SUMMARY",
        "Homepage Availability Summary",
        "ROW(\"Availability\", CALCULATE({{MEASURE}}, {{PERIOD_FILTER}}, {{CONTEXT_FILTERS}}))",
        "Reference fragment for the governed Availability summary query.",
    ),
    (
        "HOME_AVAILABILITY_TREND",
        "Homepage Availability Trend",
        "SUMMARIZECOLUMNS({{MONTH_NUMBER}}, {{MONTH_LABEL}}, {{PERIOD_FILTER}}, {{CONTEXT_FILTERS}}, \"Availability\", {{MEASURE}})",
        "Reference fragment for the monthly Availability trend.",
    ),
    (
        "HOME_AVAILABILITY_BREAKDOWN",
        "Homepage Availability Breakdown",
        "SUMMARIZECOLUMNS({{DIMENSIONS}}, {{PERIOD_FILTER}}, {{CONTEXT_FILTERS}}, \"Availability\", {{MEASURE}})",
        "Reference fragment shared by MineSite, Model and Equipment breakdowns.",
    ),
]


def seed_templates(apps, schema_editor):
    Section = apps.get_model("reports", "AIConfigSection")
    Template = apps.get_model("reports", "AIDaxTemplate")
    section = Section.objects.filter(code="performance").first()
    if not section:
        return
    for code, name, dax, description in TEMPLATES:
        Template.objects.update_or_create(
            section=section,
            template_code=code,
            defaults={
                "template_name": name,
                "dax_template": dax,
                "description": description,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0071_homepage_availability_command_center")]

    operations = [migrations.RunPython(seed_templates, migrations.RunPython.noop)]
