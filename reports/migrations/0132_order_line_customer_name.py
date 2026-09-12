from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0131_index_semantic_order_keys")]

    operations = [
        migrations.AddField(
            model_name="reconciliationorderline",
            name="customer_name",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
    ]
