from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("reports", "0124_reconciliation_buffer_sync")]

    operations = [
        migrations.AlterField(
            model_name="reconciliationsourcesnapshot",
            name="source_kind",
            field=models.CharField(
                choices=[
                    ("ORDER_HEADERS", "ORDER_HEADERS"), ("ORDERS", "ORDERS"),
                    ("DELIVERY_INVOICE", "DELIVERY_INVOICE"), ("INVOICES", "INVOICES"),
                    ("ACCOUNTING_REVENUE", "ACCOUNTING_REVENUE"),
                ],
                db_index=True, max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="ReconciliationOrderHeader",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_record_id", models.CharField(max_length=255)),
                ("company_code", models.CharField(db_index=True, max_length=40)),
                ("branch_code", models.CharField(db_index=True, max_length=40)),
                ("order_number", models.CharField(db_index=True, max_length=120)),
                ("customer_number", models.CharField(blank=True, db_index=True, max_length=120)),
                ("customer_name", models.CharField(blank=True, db_index=True, max_length=255)),
                ("order_date", models.DateField(blank=True, db_index=True, null=True)),
                ("eta", models.DateField(blank=True, db_index=True, null=True)),
                ("order_type", models.CharField(blank=True, db_index=True, max_length=80)),
                ("urgency", models.CharField(blank=True, max_length=80)),
                ("line_count", models.PositiveIntegerField(blank=True, null=True)),
                ("currency", models.CharField(blank=True, max_length=12)),
                ("transport", models.CharField(blank=True, max_length=120)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("invoicing_status", models.CharField(blank=True, db_index=True, max_length=80)),
                ("order_status", models.CharField(blank=True, db_index=True, max_length=80)),
                ("order_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True)),
                ("amount_eur", models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True)),
                ("operation_type", models.CharField(blank=True, max_length=80)),
                ("subsidiary_reference", models.CharField(blank=True, max_length=160)),
                ("international_reference", models.CharField(blank=True, max_length=160)),
                ("source_payload_json", models.JSONField(blank=True, default=dict)),
                ("snapshot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="order_headers", to="reports.reconciliationsourcesnapshot")),
            ],
            options={"db_table": "rec_order_header", "ordering": ["company_code", "branch_code", "order_number"]},
        ),
        migrations.AddConstraint(
            model_name="reconciliationorderheader",
            constraint=models.UniqueConstraint(fields=("snapshot", "source_record_id"), name="rec_unique_order_header_source_row"),
        ),
        migrations.AddIndex(
            model_name="reconciliationorderheader",
            index=models.Index(fields=["snapshot", "company_code", "branch_code", "order_number"], name="rec_order_header_key_idx"),
        ),
    ]
