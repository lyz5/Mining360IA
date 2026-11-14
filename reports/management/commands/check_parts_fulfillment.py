"""Read-only live acceptance check; never imports data or alters Power BI."""
import json
import time
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from reports.parts_fulfillment_service import PartsFulfillmentService, FulfillmentUnavailable


class Command(BaseCommand):
    help = 'Check Parts Fulfillment aggregates using an existing administrator and configured source.'

    def add_arguments(self, parser):
        parser.add_argument('--month', default='')
        parser.add_argument('--user', default='')
        parser.add_argument('--save', default='', help='Optional private JSON evidence file; do not commit business data.')

    def handle(self, **options):
        users = get_user_model().objects.filter(is_active=True, is_superuser=True)
        user = users.filter(username=options['user']).first() if options['user'] else users.first()
        if not user:
            raise CommandError('An existing active administrator is required; no account was changed.')
        started = time.monotonic()
        try:
            payload = PartsFulfillmentService(user).summary(options['month'] or None)
        except (FulfillmentUnavailable, ValueError) as exc:
            payload = {'ready': False, 'code': getattr(exc, 'code', 'INVALID_CONTEXT'), 'message': str(exc)}
        payload['validation_seconds'] = round(time.monotonic()-started, 3)
        if options['save']:
            Path(options['save']).write_text(json.dumps(payload, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(payload, ensure_ascii=True))
