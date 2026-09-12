from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0125_reconciliation_order_header")]

    operations = [
        migrations.AlterField(
            model_name="reconciliationorderheader",
            name="line_count",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
