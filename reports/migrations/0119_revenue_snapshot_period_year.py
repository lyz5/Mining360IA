from django.db import migrations, models


def backfill_revenue_years(apps, schema_editor):
    Revenue = apps.get_model("reports", "RevenueSourceSnapshot")
    Run = apps.get_model("reports", "MappingSynchronizationRun")

    for run in Run.objects.all().iterator():
        context = run.source_context_json or {}
        current_year = context.get("revenue_period_year")
        try:
            current_year = int(current_year)
        except (TypeError, ValueError):
            continue

        current_rows = Revenue.objects.filter(synchronization_run=run, period_year__isnull=True)
        previous_rows = []
        for row in current_rows.iterator():
            previous_value = row.revenue_previous_year_eur or 0
            if previous_value:
                previous_rows.append(Revenue(
                    synchronization_run_id=row.synchronization_run_id,
                    source_record_id=f"{row.source_record_id}:year:{current_year - 1}",
                    source_account_code=row.source_account_code,
                    source_account_name=row.source_account_name,
                    normalized_account_name=row.normalized_account_name,
                    code_cic=row.code_cic,
                    company_code=row.company_code,
                    branch_code=row.branch_code,
                    operating_country=row.operating_country,
                    lob=row.lob,
                    division=row.division,
                    distribution_channel=row.distribution_channel,
                    period_year=current_year - 1,
                    revenue_ytd_eur=previous_value,
                    revenue_previous_year_eur=0,
                    invoice_count=0,
                    source_hash=f"legacy-{row.source_hash}"[:64],
                    active=row.active,
                    source_last_seen_at=row.source_last_seen_at,
                ))
        current_rows.update(period_year=current_year)
        Revenue.objects.bulk_create(previous_rows, batch_size=500, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("reports", "0118_operating_country_scope")]

    operations = [
        migrations.AddField(
            model_name="revenuesourcesnapshot",
            name="period_year",
            field=models.PositiveSmallIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddIndex(
            model_name="revenuesourcesnapshot",
            index=models.Index(fields=["active", "period_year", "lob"], name="bm_revenue_period_idx"),
        ),
        migrations.RunPython(backfill_revenue_years, migrations.RunPython.noop),
    ]
