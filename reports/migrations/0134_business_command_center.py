from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("reports", "0133_index_order_customer")]

    operations = [
        migrations.AddField(model_name="revenuesourcesnapshot", name="business_date", field=models.DateField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="revenuesourcesnapshot", name="source_lob", field=models.CharField(blank=True, db_index=True, max_length=120)),
        migrations.AddField(model_name="revenuesourcesnapshot", name="revenue_eur", field=models.DecimalField(decimal_places=2, default=0, max_digits=20)),
        migrations.AddIndex(model_name="revenuesourcesnapshot", index=models.Index(fields=["active", "business_date", "lob"], name="bm_revenue_date_lob_idx")),
        migrations.AddField(model_name="businessreviewsnapshot", name="business_line_mapping_version", field=models.CharField(default="1.0", max_length=80)),
        migrations.AddField(model_name="businessreviewsnapshot", name="exchange_rate_version", field=models.CharField(default="SOURCE_CA_EURO", max_length=80)),
        migrations.AddField(model_name="businessreviewsnapshot", name="data_through_date", field=models.DateField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="businessreviewsnapshot", name="currency", field=models.CharField(default="EUR", max_length=12)),
        migrations.AddField(model_name="businessreviewsnapshot", name="reconciliation_status", field=models.CharField(db_index=True, default="Not Evaluated", max_length=30)),
        migrations.AddField(model_name="businessreviewsavedview", name="is_default", field=models.BooleanField(db_index=True, default=False)),
        migrations.AlterModelOptions(name="businessreviewsnapshot", options={"ordering": ["-generated_at"], "permissions": [("view_business_review", "Can view Business Review"), ("view_business_review_financials", "Can view Business Review financials"), ("view_business_review_fleet", "Can view Business Review fleet"), ("compare_business_entities", "Can compare Business Review entities"), ("export_business_review", "Can export Business Review"), ("create_business_review_action", "Can create Business Review actions"), ("assign_business_review_action", "Can assign Business Review actions"), ("complete_business_review_action", "Can complete Business Review actions"), ("create_business_decision", "Can create Business Review decisions"), ("view_business_review_data_confidence", "Can view Business Review data confidence"), ("preview_business_review_draft", "Can preview Business Review with unpublished mappings"), ("view_business_command_center", "Can view Business Command Center"), ("view_group_revenue", "Can view Group Revenue"), ("view_country_revenue", "Can view Country Revenue"), ("view_customer_revenue", "Can view Customer Revenue"), ("view_key_account_revenue", "Can view Key Account Revenue"), ("view_business_line_revenue", "Can view Business Line Revenue"), ("view_business_data_confidence", "Can view Business data confidence"), ("compare_business_periods", "Can compare Business periods"), ("export_business_command_center", "Can export Business Command Center"), ("copy_business_visual", "Can copy Business visuals"), ("manage_business_saved_views", "Can manage Business saved views"), ("view_business_command_center_ai", "Can use AI from Business Command Center")]}),
        migrations.CreateModel(
            name="BusinessCommandCenterUserVisit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filter_hash", models.CharField(db_index=True, max_length=64)),
                ("first_opened_at", models.DateTimeField(auto_now_add=True)),
                ("last_opened_at", models.DateTimeField(auto_now=True)),
                ("marked_reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_metrics_json", models.JSONField(blank=True, default=dict)),
                ("saved_view", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="visits", to="reports.businessreviewsavedview")),
                ("snapshot", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="command_center_visits", to="reports.businessreviewsnapshot")),
                ("source_synchronization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="command_center_visits", to="reports.mappingsynchronizationrun")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="business_command_center_visits", to="auth.user")),
            ],
            options={"db_table": "br_command_center_visit", "ordering": ["-last_opened_at"]},
        ),
        migrations.AddConstraint(model_name="businesscommandcenteruservisit", constraint=models.UniqueConstraint(fields=("user", "filter_hash"), name="br_unique_user_filter_visit")),
        migrations.CreateModel(
            name="BusinessCommandCenterWatchlist",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("entity_type", models.CharField(choices=[("Customer", "Customer"), ("Country", "Country"), ("Key Account", "Key Account"), ("Business Line", "Business Line")], db_index=True, max_length=30)),
                ("entity_id", models.CharField(db_index=True, max_length=255)),
                ("display_name", models.CharField(max_length=500)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="business_command_center_watchlist", to="auth.user")),
            ],
            options={"db_table": "br_command_center_watchlist", "ordering": ["entity_type", "display_name"]},
        ),
        migrations.AddConstraint(model_name="businesscommandcenterwatchlist", constraint=models.UniqueConstraint(fields=("user", "entity_type", "entity_id"), name="br_unique_user_watch_entity")),
    ]
