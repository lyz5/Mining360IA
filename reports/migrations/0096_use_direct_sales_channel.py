from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0095_exclude_interco_from_sales")]

    operations = [
        migrations.RemoveField(
            model_name="businessperformanceconfig",
            name="excluded_sales_channels",
        ),
        migrations.AddField(
            model_name="businessperformanceconfig",
            name="direct_sales_channel_values",
            field=models.CharField(blank=True, default="Onshore,Offshore", max_length=500),
        ),
    ]
