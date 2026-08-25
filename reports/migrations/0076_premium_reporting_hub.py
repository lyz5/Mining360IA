from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0075_homepage_equipment_mapping"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportingreportpreference",
            name="business_owner",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="category",
            field=models.CharField(
                choices=[
                    ("fleet_performance", "Fleet Performance"),
                    ("maintenance_reliability", "Maintenance & Reliability"),
                    ("operations", "Operations"),
                    ("fuel_connectivity", "Fuel & Connectivity"),
                    ("parts_aftermarket", "Parts & Aftermarket"),
                    ("management_reports", "Management Reports"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="featured",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="freshness_threshold_hours",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="tags_json",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="thumbnail_status",
            field=models.CharField(
                choices=[
                    ("fallback", "Category fallback"),
                    ("configured", "Configured"),
                    ("pending", "Pending"),
                    ("failed", "Failed"),
                ],
                default="fallback",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="thumbnail_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="reportingreportpreference",
            name="validation_status",
            field=models.CharField(
                choices=[
                    ("Imported", "Imported"),
                    ("To Review", "To Review"),
                    ("Validated", "Validated"),
                    ("Deprecated", "Deprecated"),
                ],
                default="To Review",
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="UserReportFavorite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="user_favorites", to="reports.reportingreportpreference")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="report_favorites", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "reporting_user_favorites", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="UserReportActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                ("launch_mode", models.CharField(blank=True, max_length=40)),
                ("source", models.CharField(choices=[("reporting_hub", "Reporting Hub"), ("chatbot", "Chatbot"), ("homepage", "Homepage"), ("direct", "Direct")], default="reporting_hub", max_length=30)),
                ("context_json", models.JSONField(blank=True, default=dict)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="user_activities", to="reports.reportingreportpreference")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="report_activities", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "reporting_user_activity",
                "ordering": ["-opened_at"],
                "indexes": [
                    models.Index(fields=["user", "-opened_at"], name="report_activity_user_time_idx"),
                    models.Index(fields=["report", "-opened_at"], name="report_act_report_time_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="userreportfavorite",
            constraint=models.UniqueConstraint(fields=("user", "report"), name="unique_user_report_favorite"),
        ),
    ]
