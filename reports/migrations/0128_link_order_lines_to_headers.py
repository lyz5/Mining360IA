from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("reports", "0127_materialize_order_billing_status")]

    operations = [
        migrations.AddField(
            model_name="reconciliationorderline",
            name="order_header",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="order_lines", to="reports.reconciliationorderheader",
            ),
        ),
    ]
