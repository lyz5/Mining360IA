from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('reports','0151_parts_sales_model_source')]
    operations = [
        migrations.AlterField(model_name='partsaledetail', name='allocated_revenue_eur',
            field=models.DecimalField(max_digits=28,decimal_places=10,default=0)),
        migrations.AlterField(model_name='partssalessynchronizationrun', name='allocated_revenue_eur',
            field=models.DecimalField(max_digits=28,decimal_places=10,default=0)),
    ]
