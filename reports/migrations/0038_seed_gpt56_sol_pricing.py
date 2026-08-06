from decimal import Decimal
from datetime import datetime, timezone

from django.db import migrations


def seed_pricing(apps, schema_editor):
    pricing = apps.get_model("reports", "OpenAIModelPricing")
    pricing.objects.update_or_create(
        model_name="gpt-5.6-sol",
        effective_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
        defaults={
            "effective_to": None,
            "input_cost_per_million_tokens": Decimal("5.000000"),
            "cached_input_cost_per_million_tokens": Decimal("0.500000"),
            "output_cost_per_million_tokens": Decimal("30.000000"),
            "currency": "USD",
            "source": "OpenAI official pricing",
            "active": True,
        },
    )


def remove_pricing(apps, schema_editor):
    pricing = apps.get_model("reports", "OpenAIModelPricing")
    pricing.objects.filter(
        model_name="gpt-5.6-sol",
        effective_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0037_resource_knowledge_base")]
    operations = [migrations.RunPython(seed_pricing, remove_pricing)]
