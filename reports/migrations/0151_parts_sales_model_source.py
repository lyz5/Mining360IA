import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('reports', '0150_email_code_signin')]
    operations = [
        migrations.AlterField(model_name='partssalessynchronizationrun', name='reconciliation_run',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='parts_sales_runs', to='reports.reconciliationrun')),
        migrations.AddField(model_name='partssalessynchronizationrun', name='source_context_json',
            field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='partsaledetail', name='invoice_key',
            field=models.CharField(blank=True, db_index=True, max_length=255)),
        migrations.AddField(model_name='partsaledetail', name='source_line_count',
            field=models.PositiveIntegerField(default=1)),
    ]
