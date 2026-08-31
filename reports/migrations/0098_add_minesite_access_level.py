from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0097_configure_parts_sales_chatbot")]

    operations = [
        migrations.AlterField(
            model_name="platformuser",
            name="business_performance_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "No access"),
                    ("Executive", "Executive"),
                    ("Business Manager", "Business Manager"),
                    ("Country Manager", "Country Manager"),
                    ("Account Manager", "Account Manager"),
                    ("MineSite", "MineSite User"),
                    ("Viewer", "Viewer"),
                    ("Administrator", "Administrator"),
                ],
                default="",
                max_length=40,
            ),
        ),
    ]
