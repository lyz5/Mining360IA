from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0129_index_order_snapshot_header")]

    operations = [
        migrations.AddField(
            model_name="reconciliationorderheader",
            name="semantic_order_key",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name="reconciliationorderline",
            name="semantic_order_key",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
    ]
