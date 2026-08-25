from django.db import migrations


DESCRIPTIONS = (
    (("prime movers operational status v3",), "Use the latest interactive Prime Movers operational status workspace."),
    (("prime movers",), "Monitor machine operational status and submit MineSite updates."),
    (("fuel",), "Track fuel consumption, idle time, connectivity and operational efficiency."),
    (("connected asset", "poca"), "Monitor fleet connectivity and identify assets with missing data."),
    (("lcc", "lifecycle cost"), "Monitor equipment lifecycle cost, cost drivers and ownership performance."),
    (("fleet performance", "fpr global", "fpr "), "Monitor availability, reliability, downtime and fleet performance."),
    (("sos",), "Analyze oil-sample results, alerts and emerging maintenance risks."),
    (("oil interval", "component hot sheet", "technician"), "Analyze maintenance condition, alerts and emerging reliability risks."),
    (("operator induced",), "Analyze operator-induced events and their impact on fleet performance."),
    (("logistics", "minesite", "efficience mine"), "Monitor operational status, logistics activity and site movement."),
    (("monthly",), "Review monthly fleet KPIs, trends and performance indicators."),
    (("management report", "usage metrics"), "Review consolidated performance indicators and management trends."),
    (("parts", "aftermarket"), "Track parts revenue, customer performance and aftermarket opportunities."),
    (("customer fleet",), "Review customer fleet performance, revenue planning and commercial outlook."),
    (("new tech sales", "tender"), "Explore customer opportunities, sales planning and commercial performance."),
)


def refine_descriptions(apps, schema_editor):
    Preference = apps.get_model("reports", "ReportingReportPreference")
    for preference in Preference.objects.exclude(visual_identity_status="complete"):
        name = f"{preference.report_name} {preference.display_name}".casefold()
        selected = next((description for terms, description in DESCRIPTIONS if any(term in name for term in terms)), None)
        if selected and preference.short_description != selected:
            preference.short_description = selected
            preference.save(update_fields=["short_description"])


class Migration(migrations.Migration):
    dependencies = [("reports", "0083_enrich_legacy_report_visual_identities")]

    operations = [migrations.RunPython(refine_descriptions, migrations.RunPython.noop)]
