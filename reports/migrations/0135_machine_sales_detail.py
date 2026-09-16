from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("reports", "0134_business_command_center")]

    operations = [
        migrations.CreateModel(
            name="MachineSalesSynchronizationRun",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(default="Customer Fleet & Revenue Planning Model", max_length=120)),
                ("status", models.CharField(choices=[("Running", "Running"), ("Completed", "Completed"), ("Completed with Warnings", "Completed with Warnings"), ("Failed", "Failed")], db_index=True, default="Running", max_length=30)),
                ("incremental_from", models.DateField(blank=True, null=True)),
                ("data_through_date", models.DateField(blank=True, db_index=True, null=True)),
                ("records_read", models.PositiveIntegerField(default=0)),
                ("records_created", models.PositiveIntegerField(default=0)),
                ("records_updated", models.PositiveIntegerField(default=0)),
                ("records_unchanged", models.PositiveIntegerField(default=0)),
                ("warnings_json", models.JSONField(blank=True, default=list)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "bcc_machine_sales_sync_run", "ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="MachineSaleDetail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_record_id", models.CharField(max_length=64, unique=True)),
                ("source_system", models.CharField(default="NMBEPM", max_length=40)),
                ("business_date", models.DateField(db_index=True)),
                ("customer_code", models.CharField(blank=True, db_index=True, max_length=160)),
                ("customer_name", models.CharField(blank=True, db_index=True, max_length=500)),
                ("equipment_key", models.CharField(blank=True, db_index=True, max_length=160)),
                ("equipment_code", models.CharField(blank=True, db_index=True, max_length=160)),
                ("serial_number", models.CharField(blank=True, db_index=True, max_length=255)),
                ("model_code", models.CharField(blank=True, db_index=True, max_length=160)),
                ("model_name", models.CharField(blank=True, db_index=True, max_length=255)),
                ("invoice_number", models.CharField(blank=True, db_index=True, max_length=160)),
                ("distribution_channel", models.CharField(blank=True, db_index=True, max_length=20)),
                ("sale_status_code", models.CharField(blank=True, db_index=True, max_length=20)),
                ("new_used_code", models.CharField(blank=True, max_length=20)),
                ("net_revenue_eur", models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ("source_hash", models.CharField(db_index=True, max_length=64)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("source_last_seen_at", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("synchronization_run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="machine_sales", to="reports.machinesalessynchronizationrun")),
            ],
            options={"db_table": "bcc_machine_sale_detail", "ordering": ["-business_date", "-net_revenue_eur", "serial_number"]},
        ),
        migrations.AddIndex(model_name="machinesaledetail", index=models.Index(fields=["active", "business_date"], name="bcc_machine_sale_date_idx")),
        migrations.AddIndex(model_name="machinesaledetail", index=models.Index(fields=["active", "customer_code"], name="bcc_machine_sale_customer_idx")),
        migrations.AddIndex(model_name="machinesaledetail", index=models.Index(fields=["active", "invoice_number"], name="bcc_machine_sale_invoice_idx")),
    ]
