from django.db import migrations, models
import django.db.models.deletion


def seed_business_performance(apps, schema_editor):
    Config = apps.get_model("reports", "BusinessPerformanceConfig")
    Mapping = apps.get_model("reports", "BusinessPerformanceMapping")
    PlatformUser = apps.get_model("reports", "PlatformUser")

    Config.objects.get_or_create(name="Business Performance")
    PlatformUser.objects.filter(is_platform_admin=True).update(business_performance_role="Administrator")

    mappings = [
        ("active_fleet", "Active Fleet", "metric", "measure", "Fleet", "integer", "#,##0", True),
        ("fleet_share", "Fleet Share %", "metric", "measure", "Fleet Share %", "percentage", "0.0%", False),
        ("parts_revenue", "Parts Revenue", "metric", "measure", "CA Parts", "currency", "€ #,##0", True),
        ("parts_contribution", "Parts Contribution %", "metric", "measure", "Parts Contribution %", "percentage", "0.0%", False),
        ("parts_revenue_per_fleet", "Parts Revenue per Fleet", "metric", "measure", "Parts/Fleet", "currency", "€ #,##0", True),
        ("prime_revenue", "Prime Revenue", "metric", "measure", "CA Prime", "currency", "€ #,##0", True),
        ("prime_revenue_per_fleet", "Prime Revenue per Fleet", "metric", "measure", "Prime/Fleet", "currency", "€ #,##0", False),
        ("total_revenue", "Total Revenue", "metric", "measure", "Total CA", "currency", "€ #,##0", True),
        ("total_revenue_per_fleet", "Total Revenue per Fleet", "metric", "measure", "Total CA/Fleet", "currency", "€ #,##0", False),
        ("top3_contribution", "Top 3 Customer Contribution", "metric", "measure", "Top 3 Contribution", "percentage", "0.0%", False),
        ("active_customers", "Number of Active Customers", "metric", "measure", "Active Customers", "integer", "#,##0", False),
        ("customer", "Customer", "filter", "column", "", "text", "", True),
        ("year", "Year", "filter", "column", "", "integer", "0", True),
        ("period", "Period", "filter", "column", "", "text", "", False),
        ("lob", "LOB", "filter", "column", "", "text", "", False),
        ("division", "Division", "filter", "column", "", "text", "", False),
        ("company", "Company", "filter", "column", "", "text", "", False),
        ("branch", "Branch", "filter", "column", "", "text", "", False),
        ("country", "Country", "filter", "column", "", "text", "", False),
        ("minesite", "Mine Site", "filter", "column", "", "text", "", False),
        ("equipment_type", "Equipment Type", "filter", "column", "", "text", "", False),
        ("model", "Model", "filter", "column", "", "text", "", False),
        ("fleet_status", "Fleet Status", "filter", "column", "", "integer", "0", False),
        ("customer_category", "Customer Category", "filter", "column", "", "text", "", False),
        ("distribution_channel", "Distribution Channel", "filter", "column", "", "text", "", False),
        ("serial_number", "Serial Number", "fleet", "column", "", "text", "", False),
        ("equipment_number", "Equipment Number", "fleet", "column", "", "text", "", False),
        ("invoice", "Invoice", "parts", "column", "", "text", "", False),
        ("posting_date", "Posting Date", "parts", "column", "", "date", "yyyy-mm-dd", False),
        ("machine_count", "Machines Sold", "metric", "measure", "Machines Sold", "integer", "#,##0", False),
    ]
    for order, item in enumerate(mappings, 1):
        logical_name, display_name, category, object_type, object_name, data_type, fmt, required = item
        Mapping.objects.get_or_create(
            logical_name=logical_name,
            defaults={
                "display_name": display_name,
                "category": category,
                "object_type": object_type,
                "object_name": object_name,
                "data_type": data_type,
                "format_string": fmt,
                "is_required": required,
                "display_order": order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0014_platformuser_module_roles")]

    operations = [
        migrations.AddField(
            model_name="platformuser",
            name="business_performance_role",
            field=models.CharField(blank=True, choices=[("", "No access"), ("Executive", "Executive"), ("Business Manager", "Business Manager"), ("Country Manager", "Country Manager"), ("Account Manager", "Account Manager"), ("Viewer", "Viewer"), ("Administrator", "Administrator")], default="", max_length=40),
        ),
        migrations.AddField(
            model_name="platformuser",
            name="business_performance_scope",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name="BusinessPerformanceConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="Business Performance", max_length=120, unique=True)),
                ("workspace_id", models.CharField(blank=True, max_length=128)),
                ("semantic_model_name", models.CharField(default="Customer Fleet & Revenue Planning Model", max_length=255)),
                ("semantic_model_id", models.CharField(blank=True, max_length=128)),
                ("report_id", models.CharField(blank=True, max_length=128)),
                ("tenant_id", models.CharField(blank=True, max_length=128)),
                ("authentication_mode", models.CharField(choices=[("Existing Power BI connection", "Existing Power BI connection"), ("Service Principal", "Service Principal"), ("Power Automate", "Power Automate")], default="Power Automate", max_length=80)),
                ("api_endpoint", models.CharField(blank=True, max_length=500)),
                ("xmla_endpoint", models.CharField(blank=True, max_length=500)),
                ("default_currency", models.CharField(default="EUR", max_length=16)),
                ("default_date_range", models.CharField(default="Current Year", max_length=80)),
                ("default_lob", models.CharField(blank=True, max_length=120)),
                ("default_division", models.CharField(blank=True, max_length=120)),
                ("cache_duration_seconds", models.PositiveIntegerField(default=300)),
                ("query_timeout_seconds", models.PositiveIntegerField(default=300)),
                ("top_n_default", models.PositiveIntegerField(default=20)),
                ("active_fleet_status_value", models.CharField(default="-1", max_length=20)),
                ("opportunity_threshold_mode", models.CharField(default="median", max_length=20)),
                ("opportunity_fleet_threshold", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("opportunity_revenue_threshold", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("last_successful_refresh", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "bp_config"},
        ),
        migrations.CreateModel(
            name="BusinessPerformanceMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("logical_name", models.SlugField(max_length=120, unique=True)),
                ("display_name", models.CharField(max_length=255)),
                ("category", models.CharField(choices=[("metric", "Metric"), ("filter", "Filter"), ("customer", "Customer"), ("parts", "Parts Sales"), ("prime", "Machine Sales"), ("fleet", "Fleet")], max_length=40)),
                ("object_type", models.CharField(choices=[("measure", "Measure"), ("column", "Column")], max_length=20)),
                ("table_name", models.CharField(blank=True, max_length=255)),
                ("object_name", models.CharField(blank=True, max_length=255)),
                ("data_type", models.CharField(default="text", max_length=40)),
                ("format_string", models.CharField(blank=True, max_length=80)),
                ("description", models.TextField(blank=True)),
                ("is_required", models.BooleanField(default=False)),
                ("is_visible", models.BooleanField(default=True)),
                ("display_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "bp_mappings", "ordering": ["category", "display_order", "display_name"]},
        ),
        migrations.CreateModel(
            name="BusinessPerformanceQueryLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("page", models.CharField(max_length=80)),
                ("action", models.CharField(max_length=120)),
                ("filters", models.JSONField(blank=True, default=dict)),
                ("dax_query", models.TextField(blank=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(default="Completed", max_length=30)),
                ("error_message", models.TextField(blank=True)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="auth.user")),
            ],
            options={"db_table": "bp_query_logs", "ordering": ["-created_at"]},
        ),
        migrations.RunPython(seed_business_performance, migrations.RunPython.noop),
    ]
