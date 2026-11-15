import json
from django.core.management.base import BaseCommand,CommandError
from reports import revenue_history_catchup as maintenance
from reports import revenue_history_retention as retention


class Command(BaseCommand):
    help = 'One-time authorized cleanup of expired Revenue versions; no change to daily retention.'

    def add_arguments(self,parser):
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--reclaim-data',action='store_true')

    def handle(self,*args,**options):
        if not options['apply']:
            context=retention.plan()
            self.stdout.write(json.dumps({'retention_days':3,'cutoff':context['cutoff'],'eligible_versions':len(context['runs']),
                                         'protected_versions':len(context['protected']),'last_maintenance':retention._read('catchup.json')},default=str))
            return
        try:
            maintenance.catch_up(reclaim=options['reclaim_data'],progress=lambda value:self.stdout.write(json.dumps(value,default=str)))
        except retention.RetentionStopped as exc:raise CommandError(str(exc)) from None
        except Exception:raise CommandError('MAINTENANCE_UNAVAILABLE; review the private maintenance state') from None
