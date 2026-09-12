from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0132_order_line_customer_name")]

    operations = [
        migrations.AddIndex(
            model_name="reconciliationorderline",
            index=models.Index(
                fields=["snapshot", "customer_number"],
                name="rec_order_snap_customer_idx",
            ),
        ),
    ]
