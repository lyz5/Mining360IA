from django.db import migrations


GENERIC_COMMENTS = (
    ("Machine down", "en"), ("Breakdown", "en"), ("Still down", "en"),
    ("In progress", "en"), ("Under repair", "en"), ("Waiting", "en"),
    ("Done", "en"), ("No comment", "en"), ("Machine en panne", "fr"),
    ("En cours", "fr"), ("Toujours en panne", "fr"),
    ("Réparation en cours", "fr"),
)


def bootstrap(apps, schema_editor):
    GenericRule = apps.get_model("reports", "GenericDowntimeCommentRule")
    UseCase = apps.get_model("reports", "AIUseCaseConfiguration")
    Provider = apps.get_model("reports", "AIProvider")
    ProviderModel = apps.get_model("reports", "AIProviderModel")
    for expression, language in GENERIC_COMMENTS:
        GenericRule.objects.get_or_create(
            expression=expression,
            language=language,
            defaults={"match_type": "Exact", "active": True, "validation_status": "Validated"},
        )
    provider = Provider.objects.filter(code__iexact="openai", active=True).first()
    model = ProviderModel.objects.filter(provider=provider, active=True, supports_structured_output=True).order_by("-is_default_for_provider", "display_name").first() if provider else None
    UseCase.objects.update_or_create(
        use_case_code="downtime_mapping_check",
        defaults={
            "display_name": "Downtime Mapping Check",
            "description": "Blind classification of downtime comments against validated Description CAT candidates.",
            "primary_provider": provider,
            "primary_model": model,
            "selection_mode": "priority",
            "fallback_enabled": True,
            "required_capabilities_json": ["text_generation", "structured_output", "multilingual_classification"],
            "temperature": 0,
            "maximum_output_tokens": 900,
            "timeout_seconds": 60,
            "retry_count": 1,
            "structured_output_required": True,
            "active": True,
            "validation_status": "Validated",
            "configuration_json": {"prompt_version": "DOWNTIME_DESCRIPTION_CAT_CLASSIFICATION_V1"},
        },
    )


def reverse(apps, schema_editor):
    apps.get_model("reports", "AIUseCaseConfiguration").objects.filter(use_case_code="downtime_mapping_check").delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0060_genericdowntimecommentrule_descriptioncatreference_and_more")]
    operations = [migrations.RunPython(bootstrap, reverse)]
