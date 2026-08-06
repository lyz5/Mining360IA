from django.db import migrations


def merge_case_insensitive_provider_models(apps, schema_editor):
    ProviderModel = apps.get_model("reports", "AIProviderModel")
    UseCase = apps.get_model("reports", "AIUseCaseConfiguration")
    AgentConfiguration = apps.get_model("reports", "AIAgentProviderConfiguration")
    alias = schema_editor.connection.alias

    grouped = {}
    queryset = ProviderModel.objects.using(alias).order_by(
        "provider_id", "-is_default_for_provider", "-updated_at", "pk"
    )
    for provider_model in queryset.iterator():
        key = (provider_model.provider_id, provider_model.model_code.strip().casefold())
        keeper = grouped.get(key)
        if keeper is None:
            grouped[key] = provider_model
            continue

        UseCase.objects.using(alias).filter(primary_model_id=provider_model.pk).update(
            primary_model_id=keeper.pk
        )
        AgentConfiguration.objects.using(alias).filter(model_id=provider_model.pk).update(
            model_id=keeper.pk
        )
        provider_model.delete(using=alias)


class Migration(migrations.Migration):
    dependencies = [("reports", "0051_miningprod_rollback_test_audit")]

    operations = [
        migrations.RunPython(
            merge_case_insensitive_provider_models,
            migrations.RunPython.noop,
        ),
    ]
