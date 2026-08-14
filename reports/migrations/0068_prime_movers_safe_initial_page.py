from django.db import migrations, models


SAFE_PAGE = "59d3dc50bee68205bebb"


def configure_safe_initial_page(apps, schema_editor):
    configuration = apps.get_model("reports", "PrimeMoversIntegrationConfiguration")
    configuration.objects.filter(
        code__in=["prime-movers-operational-status", "prime-movers-operational-status-v2"]
    ).update(powerbi_safe_initial_page_internal_name=SAFE_PAGE)


class Migration(migrations.Migration):
    dependencies = [("reports", "0067_prime_movers_dual_workspace")]

    operations = [
        migrations.AddField(
            model_name="primemoversintegrationconfiguration",
            name="powerbi_safe_initial_page_internal_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(configure_safe_initial_page, migrations.RunPython.noop),
    ]
