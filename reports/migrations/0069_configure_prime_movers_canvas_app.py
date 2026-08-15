from django.db import migrations


APP_ID = "f344207c-d3a7-45b9-ae09-6cd27f1f18f6"
ENVIRONMENT_ID = "90957e36-9c41-e969-ac5d-62bcb48b58f8"
TENANT_ID = "7a1b77be-dbd5-45cb-8e11-b01cbec06667"
LAUNCH_URL = f"https://apps.powerapps.com/play/e/{ENVIRONMENT_ID}/a/{APP_ID}"


def configure_canvas_app(apps, schema_editor):
    configuration = apps.get_model("reports", "PrimeMoversIntegrationConfiguration")
    configuration.objects.filter(
        code__in=["prime-movers-operational-status", "prime-movers-operational-status-v2"]
    ).update(
        powerapps_app_id=APP_ID,
        powerapps_environment_id=ENVIRONMENT_ID,
        powerapps_tenant_id=TENANT_ID,
        powerapps_launch_url=LAUNCH_URL,
        iframe_enabled=True,
        new_tab_fallback=True,
        validation_status="Validated",
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0068_prime_movers_safe_initial_page")]

    operations = [migrations.RunPython(configure_canvas_app, migrations.RunPython.noop)]
