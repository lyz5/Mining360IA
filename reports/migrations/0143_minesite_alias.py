import re
import unicodedata

from django.db import migrations, models
import django.db.models.deletion


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or "").strip()).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def seed_canonical_aliases(apps, schema_editor):
    MineSite = apps.get_model("reports", "MineSite")
    MineSiteAlias = apps.get_model("reports", "MineSiteAlias")
    sites = list(MineSite.objects.filter(active=True))
    short_names = {}
    for site in sites:
        name = site.canonical_minesite_name.strip()
        MineSiteAlias.objects.get_or_create(
            minesite=site,
            normalized_alias=_normalize(name),
            source_system="Mining360 Canonical",
            defaults={
                "alias": name,
                "validation_status": "Validated",
                "active": True,
            },
        )
        short = re.split(r"\s*/\s*|\s+-\s+", name, maxsplit=1)[0].strip()
        short_names.setdefault(_normalize(short), []).append((site, short))
    for normalized, values in short_names.items():
        if not normalized or len(values) != 1:
            continue
        site, short = values[0]
        if normalized == _normalize(site.canonical_minesite_name):
            continue
        MineSiteAlias.objects.get_or_create(
            minesite=site,
            normalized_alias=normalized,
            source_system="Canonical Short Name",
            defaults={
                "alias": short,
                "validation_status": "Validated",
                "active": True,
            },
        )


def remove_seeded_aliases(apps, schema_editor):
    apps.get_model("reports", "MineSiteAlias").objects.filter(
        source_system__in=["Mining360 Canonical", "Canonical Short Name"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0142_use_availability_per_equipment_measure")]
    operations = [
        migrations.CreateModel(
            name="MineSiteAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alias", models.CharField(max_length=500)),
                ("normalized_alias", models.CharField(db_index=True, max_length=500)),
                ("source_system", models.CharField(blank=True, max_length=120)),
                ("language", models.CharField(blank=True, max_length=12)),
                ("validation_status", models.CharField(choices=[("Draft", "Draft"), ("To Review", "To Review"), ("Validated", "Validated"), ("Rejected", "Rejected"), ("Archived", "Archived")], db_index=True, default="To Review", max_length=20)),
                ("validated_at", models.DateTimeField(blank=True, null=True)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("minesite", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="aliases", to="reports.minesite")),
                ("validated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="validated_minesite_aliases", to="auth.user")),
            ],
            options={"db_table": "bm_minesite_alias", "ordering": ["normalized_alias"]},
        ),
        migrations.AddConstraint(
            model_name="minesitealias",
            constraint=models.UniqueConstraint(fields=("minesite", "normalized_alias", "source_system"), name="bm_unique_minesite_alias"),
        ),
        migrations.AddIndex(
            model_name="minesitealias",
            index=models.Index(fields=["active", "validation_status", "normalized_alias"], name="bm_site_alias_lookup"),
        ),
        migrations.RunPython(seed_canonical_aliases, remove_seeded_aliases),
    ]
