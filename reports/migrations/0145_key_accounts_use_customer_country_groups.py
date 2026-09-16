import uuid

from django.db import migrations


def connect_customer_country_groups_to_key_accounts(apps, schema_editor):
    DirectMembership = apps.get_model("reports", "KeyAccountMembership")
    CountryMembership = apps.get_model("reports", "CountryAccountMembership")
    KeyCountryMembership = apps.get_model("reports", "KeyAccountCountryMembership")

    for direct in DirectMembership.objects.filter(active=True, key_account__active=True).iterator():
        country_membership = CountryMembership.objects.filter(
            business_account_id=direct.business_account_id,
            active=True,
            country_account__active=True,
        ).first()
        if not country_membership:
            continue
        existing = KeyCountryMembership.objects.filter(
            country_account_id=country_membership.country_account_id,
            active=True,
        ).first()
        if existing:
            continue
        historical = KeyCountryMembership.objects.filter(
            key_account_id=direct.key_account_id,
            country_account_id=country_membership.country_account_id,
        ).first()
        if historical:
            historical.active = True
            historical.created_by_id = direct.created_by_id
            historical.removed_by_id = None
            historical.removed_at = None
            historical.save(update_fields=["active", "created_by", "removed_by", "removed_at"])
        else:
            KeyCountryMembership.objects.create(
                id=uuid.uuid4(),
                key_account_id=direct.key_account_id,
                country_account_id=country_membership.country_account_id,
                active=True,
                created_by_id=direct.created_by_id,
            )


class Migration(migrations.Migration):
    dependencies = [("reports", "0144_customer_country_groups")]

    operations = [
        migrations.RunPython(connect_customer_country_groups_to_key_accounts, migrations.RunPython.noop),
    ]
