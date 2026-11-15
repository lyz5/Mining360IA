import json
from django.core.management.base import BaseCommand, CommandError
from reports import revenue_history_retention as retention


class Command(BaseCommand):
    help = 'Inspect or apply the authorized 72-hour inactive Revenue import-copy retention.'

    def add_arguments(self, parser):
        actions = parser.add_mutually_exclusive_group()
        actions.add_argument('--activate', action='store_true')
        actions.add_argument('--disable', action='store_true')
        actions.add_argument('--apply', action='store_true')
        actions.add_argument('--plan', action='store_true')
        parser.add_argument('--backup-file')
        parser.add_argument('--protect-run', action='append', default=[])
        parser.add_argument('--max-batches', type=int, default=100)
        parser.add_argument('--seconds', type=int, default=40)

    def handle(self, *args, **options):
        try:
            if options['activate']: result = retention.set_enabled(True, options['backup_file'], options['protect_run'])
            elif options['disable']: result = retention.set_enabled(False)
            elif options['apply']: result = retention.run_pass(max_batches=options['max_batches'], seconds=options['seconds'])
            elif options['plan']:
                context = retention.plan()
                result = {'retention_days': 3, 'cutoff': context['cutoff'], 'eligible_versions': len(context['runs']),
                          'protected_versions': len(context['protected']), 'active_versions': len(context['active'])}
            else: result = retention.status()
        except (retention.RetentionStopped, ValueError) as exc: raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result, default=str))
