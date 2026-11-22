from datetime import date
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from reports.parts_sales_model_sync import PartsSalesModelSynchronizationService


class Command(BaseCommand):
    help = 'Refresh Parts classification from the configured Mine Logistics invoice/accounting-date fact.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True, help='Existing authorized unrestricted administrator. No role is granted.')
        parser.add_argument('--start-date', type=date.fromisoformat)
        parser.add_argument('--end-date', type=date.fromisoformat)

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options['username'], is_active=True).first()
        if not user: raise CommandError('An existing active authorized user is required.')
        try:
            run = PartsSalesModelSynchronizationService(user).synchronize(options.get('start_date'), options.get('end_date'))
        except Exception:
            raise CommandError('Parts classification was not updated. Check source permissions, fields and the import validation record.') from None
        self.stdout.write(self.style.SUCCESS(f'{run.status}: records={run.records_read}, accounting coverage={run.data_through_date}, run={run.pk}'))
