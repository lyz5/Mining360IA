from django.db import migrations, models


SEMANTIC_MODEL_NAME = "Mine Logistics & AfterMarket"
SEMANTIC_MODEL_ID = "59dba3f4-1661-460a-9d6a-c07440eaf383"


def prepare_sales_domains(apps, schema_editor):
    BusinessPerformanceConfig = apps.get_model("reports", "BusinessPerformanceConfig")
    BusinessPerformanceMapping = apps.get_model("reports", "BusinessPerformanceMapping")

    config = BusinessPerformanceConfig.objects.filter(is_active=True).first()
    if config and config.semantic_model_name in {"", "Customer Fleet & Revenue Planning Model"}:
        config.semantic_model_name = SEMANTIC_MODEL_NAME
        if not config.semantic_model_id:
            config.semantic_model_id = SEMANTIC_MODEL_ID
        config.save(update_fields=["semantic_model_name", "semantic_model_id", "updated_at"])

    defaults = (
        ("service_revenue", "Services Revenue", "decimal", 300),
        ("service_order_count", "Service Orders", "integer", 310),
    )
    for logical_name, display_name, data_type, display_order in defaults:
        BusinessPerformanceMapping.objects.get_or_create(
            logical_name=logical_name,
            defaults={
                "display_name": display_name,
                "category": "services",
                "object_type": "measure",
                "table_name": "",
                "object_name": "",
                "data_type": data_type,
                "description": "GlobalCA mapping pending semantic-model validation.",
                "is_required": False,
                "is_visible": True,
                "display_order": display_order,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0086_add_kouroussa_corica_alias")]

    operations = [
        migrations.AlterField(
            model_name="businessperformancemapping",
            name="category",
            field=models.CharField(
                choices=[
                    ("metric", "Metric"),
                    ("filter", "Filter"),
                    ("customer", "Customer"),
                    ("parts", "Parts Sales"),
                    ("prime", "Machine Sales"),
                    ("services", "Services Sales"),
                    ("fleet", "Fleet"),
                ],
                max_length=40,
            ),
        ),
        migrations.RunPython(prepare_sales_domains, migrations.RunPython.noop),
    ]
