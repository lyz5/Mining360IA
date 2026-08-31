from django.db import migrations


QUESTIONS = (
    (
        "What are YTD Parts Sales for customer Fekola?",
        "en",
        {"section": "parts_sales", "metric": "parts_sales_ytd", "filters": {"customer": "Fekola", "period": "year to date"}},
    ),
    (
        "Quel est le chiffre d'affaires pièces YTD du client Fekola ?",
        "fr",
        {"section": "parts_sales", "metric": "parts_sales_ytd", "filters": {"customer": "Fekola", "period": "year to date"}},
    ),
    (
        "Show YTD Parts Sales by MineSite",
        "en",
        {"section": "parts_sales", "metric": "parts_sales_ytd", "filters": {"period": "year to date"}, "group_by": ["minesite"]},
    ),
    (
        "Donne les ventes pièces YTD par client",
        "fr",
        {"section": "parts_sales", "metric": "parts_sales_ytd", "filters": {"period": "year to date"}, "group_by": ["customer"]},
    ),
)


def configure_parts_sales(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIMetricMapping = apps.get_model("reports", "AIMetricMapping")
    AIFilterMapping = apps.get_model("reports", "AIFilterMapping")
    AIQuestionExample = apps.get_model("reports", "AIQuestionExample")

    section, _ = AIConfigSection.objects.update_or_create(
        code="parts_sales",
        defaults={
            "name": "Parts Sales",
            "description": "Official Parts Sales from the Mine Logistics & AfterMarket semantic model.",
            "is_active": True,
        },
    )
    AIMetricMapping.objects.update_or_create(
        section=section,
        metric_code="parts_sales_ytd",
        defaults={
            "metric_label": "Parts Sales YTD",
            "powerbi_measure_name": "CA Facture EU",
            "description": "Official invoice revenue in euro, filtered to the PARTS LOB and current year.",
            "is_active": True,
        },
    )
    mappings = (
        ("customer", "Customer", "GlobalCA", "Nom client", "Text"),
        ("minesite", "MineSite", "GlobalCA", "Territoire analytique", "Text"),
        ("period", "Period", "GlobalCA", "Année", "Text"),
    )
    for code, label, table, column, data_type in mappings:
        AIFilterMapping.objects.update_or_create(
            section=section,
            filter_code=code,
            defaults={
                "filter_label": label,
                "powerbi_table_name": table,
                "powerbi_column_name": column,
                "data_type": data_type,
                "is_required": False,
                "is_active": True,
            },
        )
    for question, language, expected in QUESTIONS:
        AIQuestionExample.objects.update_or_create(
            section=section,
            question_text=question,
            defaults={"language": language, "expected_json_intent": expected, "is_active": True},
        )


def unconfigure_parts_sales(apps, schema_editor):
    AIConfigSection = apps.get_model("reports", "AIConfigSection")
    AIMetricMapping = apps.get_model("reports", "AIMetricMapping")
    AIFilterMapping = apps.get_model("reports", "AIFilterMapping")
    AIQuestionExample = apps.get_model("reports", "AIQuestionExample")
    section = AIConfigSection.objects.filter(code="parts_sales").first()
    if not section:
        return
    AIMetricMapping.objects.filter(section=section, metric_code="parts_sales_ytd").delete()
    AIFilterMapping.objects.filter(section=section, filter_code="minesite").delete()
    AIFilterMapping.objects.filter(section=section, filter_code="customer").update(
        filter_label="Customer", powerbi_table_name="Customer", powerbi_column_name="CustomerName"
    )
    AIFilterMapping.objects.filter(section=section, filter_code="period").update(
        filter_label="Period", powerbi_table_name="Date", powerbi_column_name="Year Month"
    )
    AIQuestionExample.objects.filter(section=section, question_text__in=[item[0] for item in QUESTIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0096_use_direct_sales_channel")]

    operations = [migrations.RunPython(configure_parts_sales, unconfigure_parts_sales)]
