import uuid

from django.db import migrations


VALID_COUNTRIES = {"SN", "CI", "GN", "ML", "BF", "NE", "BJ", "TG", "MR", "FR", "CM", "GW", "MU"}


def _country(account):
    assigned = str(account.assigned_operating_country or "").strip().upper()
    if assigned in VALID_COUNTRIES:
        return assigned
    inferred = {
        str(value or "").strip().upper()
        for value in (account.operating_countries_json or [])
        if str(value or "").strip().upper() in VALID_COUNTRIES
    }
    return next(iter(inferred)) if len(inferred) == 1 else "UNASSIGNED"


def _normalized(value):
    return " ".join(str(value or "").casefold().split())


def assign_every_canonical_account(apps, schema_editor):
    BusinessAccount = apps.get_model("reports", "BusinessAccount")
    CountryAccount = apps.get_model("reports", "CountryAccount")
    Membership = apps.get_model("reports", "CountryAccountMembership")

    for account in BusinessAccount.objects.filter(active=True).iterator():
        current = Membership.objects.filter(
            business_account_id=account.pk,
            active=True,
            country_account__active=True,
        ).first()
        country = _country(account)
        if current and current.country_account.country == country:
            continue
        if current:
            current.active = False
            current.save(update_fields=["active"])

        base_name = str(account.canonical_account_name or account.canonical_account_code).strip()
        name = base_name
        if CountryAccount.objects.filter(
            active=True,
            country=country,
            normalized_country_account_name=_normalized(name),
        ).exists():
            name = f"{base_name} · {account.canonical_account_code}"
        group = CountryAccount.objects.create(
            id=uuid.uuid4(),
            country_account_code=f"CCG-{uuid.uuid4().hex.upper()}",
            country_account_name=name,
            normalized_country_account_name=_normalized(name),
            country=country,
            description="Automatically created canonical Account group.",
            active=True,
            version=1,
        )
        Membership.objects.create(
            id=uuid.uuid4(),
            country_account_id=group.pk,
            business_account_id=account.pk,
            active=True,
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0143_minesite_alias")]

    operations = [
        migrations.RunPython(assign_every_canonical_account, migrations.RunPython.noop),
    ]
