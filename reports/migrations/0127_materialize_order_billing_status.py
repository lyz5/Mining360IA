from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0126_allow_source_order_header_line_count")]

    operations = [
        migrations.AddField(
            model_name="reconciliationorderline",
            name="billing_status",
            field=models.CharField(blank=True, db_index=True, max_length=30),
        ),
        migrations.AddField(
            model_name="reconciliationorderline",
            name="ca_combine_present",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
