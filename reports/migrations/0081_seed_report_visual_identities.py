from django.db import migrations


CATEGORIES = (
    ("fleet_performance", "Fleet Performance", "activity", "fleet_performance", "emerald", 10),
    ("maintenance_reliability", "Maintenance & Reliability", "flask", "sos_analysis", "purple", 20),
    ("operations", "Operations", "truck", "logistics", "amber", 30),
    ("fuel_connectivity", "Fuel & Connectivity", "signal", "connectivity", "blue", 40),
    ("parts_aftermarket", "Parts & Aftermarket", "package", "parts_aftermarket", "rose", 50),
    ("management_reports", "Management Reports", "calendar", "monthly_report", "slate", 60),
    ("lifecycle_cost", "Lifecycle Cost", "calculator", "lifecycle_cost", "cyan", 70),
    ("customer_performance", "Customer Performance", "users", "customer_performance", "blue", 80),
    ("other", "Other", "chart", "generic_analytics", "yellow", 90),
)


IDENTITIES = (
    (("fleet performance", "fpr"), "fleet_performance", "fleet_performance", "activity", "emerald", "Monitor availability, reliability, downtime and fleet performance.", ["Availability", "Reliability"], ""),
    (("fuel monitoring",), "fuel_connectivity", "fuel_monitoring", "droplet", "blue", "Track fuel consumption, idle time, connectivity and operational efficiency.", ["Fuel", "Idle"], ""),
    (("lcc dashboard", "lifecycle cost"), "lifecycle_cost", "lifecycle_cost", "calculator", "cyan", "Monitor equipment lifecycle cost, cost drivers and ownership performance.", ["Lifecycle Cost", "Financial"], ""),
    (("mine logistics",), "operations", "logistics", "truck", "amber", "Monitor operational status, logistics activity and site movement.", ["Operations", "Logistics"], ""),
    (("operator induced",), "operations", "operator_induced", "hard-hat", "amber", "Analyze operator-induced events and their impact on fleet performance.", ["Operator Events", "Downtime"], ""),
    (("monthly", "customer"), "management_reports", "monthly_report_customer", "calendar", "slate", "Review monthly fleet performance through the customer reporting view.", ["Monthly Review", "Customer"], "Executive"),
    (("monthly", "neember"), "management_reports", "monthly_report_internal", "dashboard", "slate", "Review monthly fleet KPIs and internal performance indicators.", ["Monthly Review", "Internal"], "Executive"),
    (("sos",), "maintenance_reliability", "sos_analysis", "flask", "purple", "Analyze oil-sample results, alerts and emerging maintenance risks.", ["SOS", "Maintenance"], ""),
    (("connected assets", "poca"), "fuel_connectivity", "connectivity", "signal", "blue", "Monitor fleet connectivity and identify assets with missing data.", ["Connectivity", "Fleet"], ""),
    (("prime movers operational status v3",), "operations", "prime_movers_v3", "engine", "amber", "Use the latest interactive Prime Movers operational status workspace.", ["Prime Movers", "Status"], "Interactive"),
    (("prime movers operational status",), "operations", "prime_movers", "engine", "amber", "Monitor machine operational status and submit MineSite updates.", ["Prime Movers", "Status"], "Interactive"),
    (("aftermarket", "parts"), "parts_aftermarket", "parts_aftermarket", "package", "rose", "Track parts revenue, customer performance and aftermarket opportunities.", ["Parts", "Revenue"], ""),
)


def seed_visual_identities(apps, schema_editor):
    Category = apps.get_model("reports", "ReportCategory")
    Preference = apps.get_model("reports", "ReportingReportPreference")
    for code, name, icon, illustration, accent, order in CATEGORIES:
        Category.objects.update_or_create(
            code=code,
            defaults={
                "display_name": name,
                "icon_code": icon,
                "illustration_code": illustration,
                "accent_code": accent,
                "display_order": order,
                "active": True,
                "validation_status": "To Review",
            },
        )

    for preference in Preference.objects.all():
        name = f"{preference.report_name} {preference.display_name}".casefold()
        selected = None
        for identity in IDENTITIES:
            terms = identity[0]
            if all(term in name for term in terms):
                selected = identity
                break
        if not selected:
            continue
        _, category, illustration, icon, accent, description, tags, badge = selected
        changed = []
        if preference.category == "other":
            preference.category = category
            changed.append("category")
        if not preference.illustration_code:
            preference.illustration_code = illustration
            changed.append("illustration_code")
        if not preference.icon_code:
            preference.icon_code = icon
            changed.append("icon_code")
        if not preference.accent_code:
            preference.accent_code = accent
            changed.append("accent_code")
        if not preference.short_description:
            preference.short_description = preference.description or description
            changed.append("short_description")
        if not preference.description:
            preference.description = description
            changed.append("description")
        if not preference.tags_json:
            preference.tags_json = tags
            changed.append("tags_json")
        if badge and not preference.card_badge:
            preference.card_badge = badge
            changed.append("card_badge")
        if preference.visual_identity_status in {"default", "needs_review"}:
            preference.visual_identity_status = "needs_review"
            changed.append("visual_identity_status")
        if changed:
            preference.save(update_fields=list(dict.fromkeys(changed)))


class Migration(migrations.Migration):
    dependencies = [("reports", "0080_report_card_personalization")]

    operations = [migrations.RunPython(seed_visual_identities, migrations.RunPython.noop)]
