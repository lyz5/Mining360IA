from django.db import migrations


RULES = (
    (("prime movers operational status v3",), "operations", "prime_movers_v3", "engine", "amber", "Use the latest interactive Prime Movers operational status workspace.", ["Prime Movers", "Status"], "Interactive"),
    (("prime movers",), "operations", "prime_movers", "engine", "amber", "Monitor machine operational status and submit MineSite updates.", ["Prime Movers", "Status"], "Interactive"),
    (("fuel",), "fuel_connectivity", "fuel_monitoring", "droplet", "blue", "Track fuel consumption, idle time, connectivity and operational efficiency.", ["Fuel", "Idle"], ""),
    (("connected asset", "poca"), "fuel_connectivity", "connectivity", "signal", "blue", "Monitor fleet connectivity and identify assets with missing data.", ["Connectivity", "Fleet"], ""),
    (("lcc", "lifecycle cost"), "lifecycle_cost", "lifecycle_cost", "calculator", "cyan", "Monitor equipment lifecycle cost, cost drivers and ownership performance.", ["Lifecycle Cost", "Financial"], ""),
    (("fleet performance", "fpr global", "fpr "), "fleet_performance", "fleet_performance", "activity", "emerald", "Monitor availability, reliability, downtime and fleet performance.", ["Availability", "Reliability"], ""),
    (("sos", "oil interval", "component hot sheet", "technician"), "maintenance_reliability", "sos_analysis", "flask", "purple", "Analyze maintenance condition, alerts and emerging reliability risks.", ["Maintenance", "Reliability"], ""),
    (("operator induced",), "operations", "operator_induced", "hard-hat", "amber", "Analyze operator-induced events and their impact on fleet performance.", ["Operator Events", "Downtime"], ""),
    (("logistics", "minesite", "efficience mine"), "operations", "logistics", "truck", "amber", "Monitor operational status, logistics activity and site movement.", ["Operations", "Logistics"], ""),
    (("monthly", "management report", "usage metrics"), "management_reports", "monthly_report", "calendar", "slate", "Review consolidated performance indicators and management trends.", ["Monthly Review", "Performance"], "Executive"),
    (("parts", "aftermarket"), "parts_aftermarket", "parts_aftermarket", "package", "rose", "Track parts revenue, customer performance and aftermarket opportunities.", ["Parts", "Revenue"], ""),
    (("customer fleet", "new tech sales", "tender"), "customer_performance", "customer_performance", "users", "blue", "Review customer performance, planning and commercial opportunities.", ["Customer", "Performance"], ""),
)


def enrich_legacy_identities(apps, schema_editor):
    Preference = apps.get_model("reports", "ReportingReportPreference")
    for preference in Preference.objects.exclude(visual_identity_status="complete"):
        name = f"{preference.report_name} {preference.display_name}".casefold()
        selected = next((rule for rule in RULES if any(term in name for term in rule[0])), None)
        if selected is None:
            continue
        _, category, illustration, icon, accent, description, tags, badge = selected
        preference.category = category
        preference.illustration_code = preference.illustration_code or illustration
        preference.icon_code = preference.icon_code or icon
        preference.accent_code = accent
        preference.short_description = preference.short_description or preference.description or description
        preference.description = preference.description or description
        preference.tags_json = preference.tags_json or tags
        preference.card_badge = preference.card_badge or badge
        preference.visual_identity_status = "needs_review"
        preference.save(update_fields=[
            "category", "illustration_code", "icon_code", "accent_code",
            "short_description", "description", "tags_json", "card_badge",
            "visual_identity_status",
        ])


class Migration(migrations.Migration):
    dependencies = [("reports", "0082_report_visual_asset_selection")]

    operations = [migrations.RunPython(enrich_legacy_identities, migrations.RunPython.noop)]
