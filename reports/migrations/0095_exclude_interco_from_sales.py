from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0094_use_euro_currency_label")]

    operations = [
        migrations.AddField(
            model_name="businessperformanceconfig",
            name="excluded_sales_channels",
            field=models.CharField(blank=True, default="Interco", max_length=500),
        ),
    ]
