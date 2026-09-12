from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("reports", "0121_company_code_reference"),
    ]
    operations = [
        migrations.AddField(
            model_name="businessaccount",
            name="assigned_operating_country",
            field=models.CharField(blank=True, db_index=True, max_length=12),
        ),
        migrations.AddField(
            model_name="businessaccount",
            name="operating_country_assigned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="businessaccount",
            name="operating_country_assigned_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_business_account_operating_countries",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
