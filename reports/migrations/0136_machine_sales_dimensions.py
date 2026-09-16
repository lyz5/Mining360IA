from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0135_machine_sales_detail")]

    operations = [
        migrations.AddField(model_name="machinesaledetail", name="product_category", field=models.CharField(blank=True, db_index=True, max_length=255)),
        migrations.AddField(model_name="machinesaledetail", name="equipment_family", field=models.CharField(blank=True, db_index=True, max_length=255)),
        migrations.AddField(model_name="machinesaledetail", name="family_code", field=models.CharField(blank=True, db_index=True, max_length=20)),
        migrations.AddField(model_name="machinesaledetail", name="brand", field=models.CharField(blank=True, db_index=True, max_length=120)),
    ]
