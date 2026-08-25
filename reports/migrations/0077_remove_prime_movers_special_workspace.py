from django.db import migrations, models


def use_generic_powerbi_viewer(apps, schema_editor):
    PowerBIReport = apps.get_model("reports", "PowerBIReport")
    PowerBIReport.objects.filter(launch_mode="prime_movers_workspace").update(
        launch_mode="generic_powerbi",
        authentication_mode="app_owns_data",
        contains_powerapps_visual=False,
        requires_user_identity=False,
        powerapps_app_name="",
        powerapps_environment="",
        access_instructions="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0076_premium_reporting_hub"),
    ]

    operations = [
        migrations.RunPython(use_generic_powerbi_viewer, migrations.RunPython.noop),
        migrations.DeleteModel(name="PrimeMoversIntegrationExecutionLog"),
        migrations.DeleteModel(name="PowerAppsLaunchContext"),
        migrations.DeleteModel(name="PrimeMoversIntegrationConfiguration"),
        migrations.AlterField(
            model_name="powerbireport",
            name="launch_mode",
            field=models.CharField(
                choices=[("generic_powerbi", "Generic Power BI viewer")],
                default="generic_powerbi",
                max_length=40,
            ),
        ),
    ]
