from django.db import migrations
from django.utils import timezone


def retire_country_accounts(apps, schema_editor):
    CountryAccount = apps.get_model("reports", "CountryAccount")
    CountryAccountMembership = apps.get_model("reports", "CountryAccountMembership")
    KeyAccountCountryMembership = apps.get_model("reports", "KeyAccountCountryMembership")
    KeyAccountMembership = apps.get_model("reports", "KeyAccountMembership")

    now = timezone.now()
    for key_country in KeyAccountCountryMembership.objects.filter(active=True):
        account_ids = CountryAccountMembership.objects.filter(
            country_account_id=key_country.country_account_id,
            active=True,
        ).values_list("business_account_id", flat=True)
        for account_id in account_ids:
            active_membership = KeyAccountMembership.objects.filter(
                business_account_id=account_id,
                active=True,
            ).first()
            if active_membership:
                continue
            membership = KeyAccountMembership.objects.filter(
                key_account_id=key_country.key_account_id,
                business_account_id=account_id,
            ).first()
            if membership:
                membership.active = True
                membership.removed_by_id = None
                membership.removed_at = None
                membership.save(update_fields=["active", "removed_by", "removed_at"])
            else:
                KeyAccountMembership.objects.create(
                    key_account_id=key_country.key_account_id,
                    business_account_id=account_id,
                    created_by_id=key_country.created_by_id,
                )

    KeyAccountCountryMembership.objects.filter(active=True).update(active=False, removed_at=now)
    CountryAccountMembership.objects.filter(active=True).update(active=False, removed_at=now)
    CountryAccount.objects.filter(active=True).update(active=False, updated_at=now)


class Migration(migrations.Migration):
    dependencies = [("reports", "0119_revenue_snapshot_period_year")]
    operations = [migrations.RunPython(retire_country_accounts, migrations.RunPython.noop)]
