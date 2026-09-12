from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


def seed_cbg_country_override(apps, schema_editor):
    Override = apps.get_model("reports", "SourceAccountFieldOverride")
    SourceAccount = apps.get_model("reports", "SourceAccountRecord")
    for source_id in ("23-12278", "27-12278"):
        Override.objects.update_or_create(
            source_system="MiningAccounts",
            source_record_id=source_id,
            field_name="country",
            defaults={
                "source_value": "US",
                "corrected_value": "GN",
                "reason": "Business validation: CBG CONTRAT MARC is located in Guinea.",
                "active": True,
            },
        )
        for record in SourceAccount.objects.filter(source_system="MiningAccounts", source_record_id=source_id):
            record.country = "GN"
            record.source_payload_json = {
                **(record.source_payload_json or {}),
                "source_country": "US",
                "country_override_applied": True,
            }
            record.save(update_fields=["country", "source_payload_json"])
            if record.canonical_account_id:
                account = record.canonical_account
                account.country = "GN"
                account.save(update_fields=["country", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("reports", "0112_business_review_control_tower")]

    operations = [
        migrations.CreateModel(
            name="SourceAccountFieldOverride",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("source_system", models.CharField(max_length=120, db_index=True)),
                ("source_record_id", models.CharField(max_length=255, db_index=True)),
                ("field_name", models.CharField(max_length=80, db_index=True)),
                ("source_value", models.CharField(max_length=500, blank=True)),
                ("corrected_value", models.CharField(max_length=500)),
                ("reason", models.TextField()),
                ("active", models.BooleanField(default=True, db_index=True)),
                ("validated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("validated_by", models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="validated_source_account_overrides", to="auth.user")),
            ],
            options={"ordering": ["source_system", "source_record_id", "field_name"], "db_table": "bm_source_account_field_override"},
        ),
        migrations.AddConstraint(
            model_name="sourceaccountfieldoverride",
            constraint=models.UniqueConstraint(fields=("source_system", "source_record_id", "field_name"), name="bm_unique_source_account_field_override"),
        ),
        migrations.RunPython(seed_cbg_country_override, migrations.RunPython.noop),
    ]
