from django.db import migrations, models


def configure_development_dataverse_context(apps, schema_editor):
    configuration = apps.get_model("reports", "PrimeMoversIntegrationConfiguration")
    configuration.objects.filter(code="prime-movers-operational-status").update(
        dataverse_environment_url="https://org0458b935.crm12.dynamics.com",
        dataverse_context_entity_set="pbi_mining360primemoverscontexts",
        context_transfer_mode="dataverse_context",
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0069_configure_prime_movers_canvas_app")]

    operations = [
        migrations.AddField(
            model_name="primemoversintegrationconfiguration",
            name="dataverse_environment_url",
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name="primemoversintegrationconfiguration",
            name="dataverse_context_entity_set",
            field=models.CharField(default="pbi_mining360primemoverscontexts", max_length=255),
        ),
        migrations.AddField(
            model_name="powerappslaunchcontext",
            name="transfer_status",
            field=models.CharField(db_index=True, default="pending", max_length=30),
        ),
        migrations.AddField(
            model_name="powerappslaunchcontext",
            name="transfer_error_code",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="powerappslaunchcontext",
            name="transfer_error_message",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="powerappslaunchcontext",
            name="transferred_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(configure_development_dataverse_context, migrations.RunPython.noop),
    ]
