from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from codex_chatbot.async_service import process_next_run


class Command(BaseCommand):
    help = "Process persisted M360 Chatbot runs."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll-seconds", type=float, default=1.0)

    def handle(self, *args, **options):
        while True:
            run = process_next_run()
            if run:
                self.stdout.write(f"Processed Codex run {run.id}")
            elif options["once"]:
                return
            else:
                time.sleep(max(0.2, options["poll_seconds"]))
            if options["once"]:
                return
