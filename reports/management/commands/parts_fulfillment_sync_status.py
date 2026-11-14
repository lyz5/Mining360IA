"""Read the daily Parts execution state without launching a source query."""
import json

from django.core.management.base import BaseCommand

from reports.parts_fulfillment_auto_sync import synchronization_state


class Command(BaseCommand):
    help = 'Show the daily Parts measure-read schedule and last completion; read-only.'

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(synchronization_state()))
