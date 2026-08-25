from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_homepage_configuration(apps, schema_editor):
    HomepageConfiguration = apps.get_model("reports", "HomepageConfiguration")
    HomepageConfiguration.objects.update_or_create(
        code="availability-command-center",
        defaults={
            "default_kpi": "availability",
            "default_period": "ytd",
            "default_breakdown": "overall",
            "show_target": True,
            "show_comparison": True,
            "show_top_performers": True,
            "show_bottom_performers": True,
            "show_ai_insight": False,
            "maximum_cards": 5,
            "equipment_page_size": 25,
            "animation_enabled": True,
            "animation_intensity": "standard",
            "cache_duration_seconds": 300,
            "freshness_threshold_hours": 24,
            "active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0070_prime_movers_dataverse_context"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HomepageConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(default="availability-command-center", max_length=120, unique=True)),
                ("default_kpi", models.CharField(default="availability", max_length=120)),
                ("default_period", models.CharField(choices=[("ytd", "Year to Date"), ("last_12_months", "Last 12 Months")], default="ytd", max_length=30)),
                ("default_breakdown", models.CharField(choices=[("overall", "Overall"), ("minesite", "Mine Site"), ("model", "Model"), ("equipment", "Equipment")], default="overall", max_length=30)),
                ("show_target", models.BooleanField(default=True)),
                ("show_comparison", models.BooleanField(default=True)),
                ("show_top_performers", models.BooleanField(default=True)),
                ("show_bottom_performers", models.BooleanField(default=True)),
                ("show_ai_insight", models.BooleanField(default=False)),
                ("maximum_cards", models.PositiveSmallIntegerField(default=5)),
                ("equipment_page_size", models.PositiveSmallIntegerField(default=25)),
                ("animation_enabled", models.BooleanField(default=True)),
                ("animation_intensity", models.CharField(choices=[("subtle", "Subtle"), ("standard", "Standard"), ("reduced", "Reduced")], default="standard", max_length=20)),
                ("cache_duration_seconds", models.PositiveIntegerField(default=300)),
                ("freshness_threshold_hours", models.PositiveIntegerField(default=24)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "homepage_configuration", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="HomepageInteractionEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("page_view", "Page view"), ("period_change", "Period change"), ("breakdown_change", "Breakdown change"), ("filter_change", "Filter change"), ("drill_down", "Drill down"), ("ask_ai", "Ask AI"), ("open_report", "Open report"), ("open_downtime", "Open downtime drivers")], db_index=True, max_length=40)),
                ("context_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="homepage_interaction_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "homepage_interaction_event", "ordering": ["-created_at"]},
        ),
        migrations.RunPython(seed_homepage_configuration, migrations.RunPython.noop),
    ]
