from django.core.management.base import BaseCommand
from codex_chatbot.history_import import import_history


class Command(BaseCommand):
    help='Import legacy chatbot history without deleting originals or duplicating prior imports.'
    def handle(self,*args,**options):
        result=import_history()
        self.stdout.write(f"Imported {result['conversations']} conversations and {result['messages']} messages.")
