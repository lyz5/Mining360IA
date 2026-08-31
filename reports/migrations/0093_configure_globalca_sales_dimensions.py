from django.db import migrations


def configure_globalca_dimensions(apps, schema_editor):
    Mapping = apps.get_model("reports", "BusinessPerformanceMapping")
    dimensions = (
        ("customer", "Customer", "Nom client", "filter", "text", True),
        ("customer_code", "Customer Code", "Code client Irium", "parts", "text", False),
        ("year", "Year", "Année", "filter", "integer", True),
        ("period", "Month", "Mois", "filter", "integer", True),
        ("division", "Division", "Division", "filter", "text", False),
        ("company", "Company", "Libellé Société", "filter", "text", False),
        ("branch", "Branch", "Libellé Succursale", "filter", "text", False),
        ("territory", "Analytical Territory", "Territoire analytique", "filter", "text", False),
        ("manufacturer", "Manufacturer", "Libellé constructeur", "filter", "text", False),
        ("product_detail", "Product Detail", "Produits détails", "parts", "text", False),
        ("accounting_family", "Accounting Family", "Libellé famille comptable", "parts", "text", False),
        ("service_billed", "Billed Service", "Service facturé", "parts", "text", False),
        ("customer_category", "Customer Category", "Catégorie client", "filter", "text", False),
        ("distribution_channel", "Distribution Channel", "Canal de distribution", "filter", "text", False),
        ("invoice", "Invoice", "Facture", "parts", "text", False),
        ("posting_date", "Posting Date", "Date ecritures", "parts", "date", False),
        ("equipment_number", "Equipment Code", "Code Equipement", "parts", "text", False),
        ("serial_number", "Serial Number", "N° de série", "parts", "text", False),
    )
    for order, (logical, display, column, category, data_type, required) in enumerate(dimensions, 400):
        Mapping.objects.update_or_create(
            logical_name=logical,
            defaults={
                "display_name": display,
                "category": category,
                "object_type": "column",
                "table_name": "GlobalCA",
                "object_name": column,
                "data_type": data_type,
                "description": "Validated GlobalCA semantic field.",
                "is_required": required,
                "is_visible": True,
                "display_order": order,
                "is_active": True,
            },
        )
    Mapping.objects.filter(
        logical_name__in=["parts_revenue", "prime_revenue", "total_revenue"]
    ).update(
        is_active=False,
        description="Legacy placeholder superseded by official CA Facture currency measures.",
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0092_map_official_invoice_revenue_measures")]

    operations = [
        migrations.RunPython(configure_globalca_dimensions, migrations.RunPython.noop),
    ]
