from collections import defaultdict

from django.db import migrations, models


COMPANIES = [
    ("22", "NEEMBA International", "Vivea Business Park, Bloc B", "MU", "MU", "International"),
    ("23", "NEEMBA Group", "c/o Interface International Ltd", "MU", "MU", "Group"),
    ("24", "UP2I", "c/o Interface International Ltd", "MU", "MU", "Shared Service"),
    ("25", "NEEMBA Sangaredi France", "Mines Equipements et Services", "FR", "GN", "Operating Company"),
    ("27", "NEEMBA France", "17 rue Vauban", "FR", "FR", "Operating Company"),
    ("29", "DELMAS INVESTISSEMENTS ET PART", "17 rue Vauban", "FR", "FR", "Holding"),
    ("30", "NEEMBA Benin", "ZI Akpakpa - Pk3", "BJ", "BJ", "Operating Company"),
    ("31", "NEEMBA Burkina", "Gampela 1 route de Niamey", "BF", "BF", "Operating Company"),
    ("32", "NEEMBA Cote d'Ivoire", "Route de Dabou", "CI", "CI", "Operating Company"),
    ("33", "NEEMBA MINING GUINEE", "Route du Niger, Km 10", "GN", "GN", "Mining Company"),
    ("34", "NEEMBA Guinee", "Carrefour Miniere - Belle-Vue", "GN", "GN", "Operating Company"),
    ("35", "BISSAU EQUIPAMENTOS", "Rua Eng. Q. Quinhones", "GW", "GW", "Operating Company"),
    ("36", "NEEMBA Mali", "Zone Industrielle - Sotuba", "ML", "ML", "Operating Company"),
    ("37", "NEEMBA Mauritanie", "Ilot 12 - Las Palmas", "MR", "MR", "Operating Company"),
    ("38", "NEEMBA Free Zone", "No 1 ZAC, Boulevard maritime", "MU", "MU", "Free Zone"),
    ("39", "NEEMBA Niger", "2 av de la Chambre de Commerce", "NE", "NE", "Operating Company"),
    ("40", "NEEMBA Senegal", "keur Daouda Sarr", "SN", "SN", "Operating Company"),
    ("41", "NEEMBA Togo", "2556 Boulevard de la paix", "TG", "TG", "Operating Company"),
    ("42", "UTIL EQUIP INTERNATIONAL", "Vivea Business Park, Bloc B", "MU", "MU", "International"),
    ("43", "UTILEQUIP CAMEROUN", "59, Rue Victoria", "CM", "CM", "Operating Company"),
    ("44", "NEEMBA FINANCE CI", "bd giscard d estaing zone 4 A", "CI", "CI", "Finance Company"),
    ("45", "NEEMBA Finance Burkina", "Gampela 1 route de Niamey", "BF", "BF", "Finance Company"),
    ("46", "NEEMBA FINANCE SENEGAL", "keur Daouda Sarr", "SN", "SN", "Finance Company"),
    ("47", "NEEMBA Finance Mali", "Zone Industrielle - Sotuba", "ML", "ML", "Finance Company"),
    ("48", "NEEMBA Finance France", "17 rue Vauban", "FR", "FR", "Finance Company"),
    ("49", "NEEMBA Finance Guinee", "Carrefour Miniere - Belle-Vue", "GN", "GN", "Finance Company"),
    ("61", "NEEMBA Mining Burkina", "Gampela 1 route de Niamey", "BF", "BF", "Mining Company"),
    ("62", "ERSUM", "Gampela, 01 route de Niamey", "BF", "BF", "Operating Company"),
    ("66", "NEEMBA MINING MALI", "Zone Industrielle - Sotuba", "ML", "ML", "Mining Company"),
]


def load_company_codes(apps, schema_editor):
    Reference = apps.get_model("reports", "BusinessCompanyCodeReference")
    Revenue = apps.get_model("reports", "RevenueSourceSnapshot")
    SourceAccount = apps.get_model("reports", "SourceAccountRecord")
    BusinessAccount = apps.get_model("reports", "BusinessAccount")

    references = {}
    for code, name, address, legal_country, operating_country, classification_type in COMPANIES:
        reference, _ = Reference.objects.update_or_create(
            company_code=code,
            defaults={
                "legal_entity_name": name,
                "address": address,
                "legal_country_code": legal_country,
                "operating_country_code": operating_country,
                "classification_type": classification_type,
                "source_reference": "Code Societe.xlsx",
                "validation_status": "Validated",
                "active": True,
            },
        )
        references[code] = reference
        Revenue.objects.filter(company_code=code).update(operating_country=operating_country)

    for record in SourceAccount.objects.all().iterator():
        payload = dict(record.source_payload_json or {})
        codes = set(payload.get("revenue_company_code_values") or [])
        if record.company_code:
            codes.add(record.company_code)
        matched = [references[code] for code in codes if code in references]
        if not matched:
            continue
        countries = sorted({item.operating_country_code for item in matched if item.operating_country_code})
        payload["revenue_company_name_values"] = sorted({item.legal_entity_name for item in matched})
        payload["company_code_reference_source"] = "Code Societe.xlsx"
        record.operating_countries_json = countries
        record.source_payload_json = payload
        record.save(update_fields=["operating_countries_json", "source_payload_json"])

    countries_by_account = defaultdict(set)
    for account_id, countries in SourceAccount.objects.exclude(canonical_account_id=None).values_list(
        "canonical_account_id", "operating_countries_json"
    ):
        countries_by_account[account_id].update(countries or [])
    accounts = list(BusinessAccount.objects.filter(pk__in=countries_by_account))
    for account in accounts:
        account.operating_countries_json = sorted(countries_by_account[account.pk])
    BusinessAccount.objects.bulk_update(accounts, ["operating_countries_json"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("reports", "0120_retire_country_accounts")]
    operations = [
        migrations.CreateModel(
            name="BusinessCompanyCodeReference",
            fields=[
                ("company_code", models.CharField(max_length=120, primary_key=True, serialize=False)),
                ("legal_entity_name", models.CharField(db_index=True, max_length=255)),
                ("address", models.CharField(blank=True, max_length=500)),
                ("legal_country_code", models.CharField(blank=True, db_index=True, max_length=12)),
                ("operating_country_code", models.CharField(blank=True, db_index=True, max_length=12)),
                ("classification_type", models.CharField(db_index=True, default="Operating Company", max_length=40)),
                ("source_reference", models.CharField(default="Code Societe.xlsx", max_length=255)),
                ("validation_status", models.CharField(db_index=True, default="Validated", max_length=20)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "bm_company_code_reference", "ordering": ["company_code"]},
        ),
        migrations.RunPython(load_company_codes, migrations.RunPython.noop),
    ]
