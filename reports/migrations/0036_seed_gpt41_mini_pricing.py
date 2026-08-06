from datetime import datetime, timezone
from decimal import Decimal

from django.db import migrations


def seed_pricing(apps, schema_editor):
    Pricing = apps.get_model('reports', 'OpenAIModelPricing')
    Pricing.objects.update_or_create(
        model_name='gpt-4.1-mini',
        effective_from=datetime(2025, 4, 14, tzinfo=timezone.utc),
        defaults={
            'effective_to': None,
            'input_cost_per_million_tokens': Decimal('0.40'),
            'cached_input_cost_per_million_tokens': Decimal('0.10'),
            'output_cost_per_million_tokens': Decimal('1.60'),
            'currency': 'USD',
            'source': 'OpenAI official model pricing',
            'active': True,
        },
    )


def remove_pricing(apps, schema_editor):
    apps.get_model('reports', 'OpenAIModelPricing').objects.filter(
        model_name='gpt-4.1-mini',
        effective_from=datetime(2025, 4, 14, tzinfo=timezone.utc),
        source='OpenAI official model pricing',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('reports', '0035_smcs_classification_preview')]
    operations = [migrations.RunPython(seed_pricing, remove_pricing)]
