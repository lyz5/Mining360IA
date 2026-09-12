from django.db import migrations


SYNONYMS = [
    "commissioning date",
    "in-service date",
    "service start date",
    "date placed in service",
    "operational start date",
    "commissioned",
    "placed in service",
    "date de mise en service",
    "date mise en service",
    "date d’entrée en service",
    "date d'activation de la machine",
    "date de démarrage de l’équipement",
    "mis en service",
    "mise en service",
]


def extend_synonyms(apps, schema_editor):
    BusinessDataField = apps.get_model("reports", "BusinessDataField")
    BusinessDataField.objects.filter(
        canonical_field_code="commissioning_date",
        entity_type="equipment",
    ).update(synonyms_json=SYNONYMS)


class Migration(migrations.Migration):
    dependencies = [("reports", "0103_seed_chatbot_capability_answerability")]
    operations = [migrations.RunPython(extend_synonyms, migrations.RunPython.noop)]
