from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from reports.downtime_mapping_check_service import DowntimeEventRepository, SOURCE_COLUMNS
from reports.external_data_browsers import _quote_identifier, _quote_object_name, external_browser_connection
from reports.models import DescriptionCATReference


class Command(BaseCommand):
    help = "Import distinct Description CAT values from the governed downtime source as To Review references."

    def add_arguments(self, parser):
        parser.add_argument("--validation-status", choices=[value for value, _ in DescriptionCATReference.VALIDATION_STATUSES], default="To Review")

    def handle(self, *args, **options):
        browser = DowntimeEventRepository().browser()
        column = _quote_identifier(SOURCE_COLUMNS["current_description_cat"])
        source = _quote_object_name(browser.source_view_name)
        with external_browser_connection(browser) as connection:
            cursor = connection.cursor()
            cursor.execute(f"SELECT DISTINCT LTRIM(RTRIM(CAST({column} AS NVARCHAR(500)))) FROM {source} WHERE {column} IS NOT NULL AND LTRIM(RTRIM(CAST({column} AS NVARCHAR(500)))) <> '' ORDER BY 1")
            names = [str(row[0]).strip() for row in cursor.fetchall()]
        if not names:
            raise CommandError("No Description CAT values were returned by the source.")
        created = updated = 0
        for name in names:
            base = slugify(name)[:130] or "description-cat"
            code = base
            suffix = 2
            while DescriptionCATReference.objects.exclude(name=name).filter(code=code).exists():
                code = f"{base[:125]}-{suffix}"
                suffix += 1
            _, was_created = DescriptionCATReference.objects.update_or_create(
                name=name,
                defaults={"code": code, "display_name": name, "validation_status": options["validation_status"], "active": True},
            )
            created += int(was_created)
            updated += int(not was_created)
        self.stdout.write(self.style.SUCCESS(f"Description CAT reference synchronized: {created} created, {updated} updated ({options['validation_status']})."))
