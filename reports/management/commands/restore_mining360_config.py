import os

from django.core.management.base import BaseCommand

from reports.mining360_repository import restore_django_config_tables_from_sqlserver
from reports.sqlserver import DEFAULT_SERVER


class Command(BaseCommand):
    help = "Restore Mining360 configuration cache from SQL Server Mining360 tables."

    def add_arguments(self, parser):
        parser.add_argument("--server", default=os.getenv("MINING360_SQL_SERVER", DEFAULT_SERVER))
        parser.add_argument("--database", default=os.getenv("MINING360_SQL_DATABASE", "Mining360"))
        parser.add_argument("--user", default=os.getenv("MINING360_SQL_USER"))
        parser.add_argument("--password", default=os.getenv("MINING360_SQL_PASSWORD") or os.getenv("SQLSERVER_PASSWORD"))

    def handle(self, *args, **options):
        os.environ["MINING360_SQL_SERVER"] = options["server"]
        os.environ["MINING360_SQL_DATABASE"] = options["database"]
        if options["user"]:
            os.environ["MINING360_SQL_USER"] = options["user"]
        if options["password"]:
            os.environ["MINING360_SQL_PASSWORD"] = options["password"]
        os.environ["MINING360_SQL_CONFIG_STORE"] = "0"

        self.stdout.write(
            f"Restauration depuis SQL Server: serveur={options['server']}, base={options['database']}"
        )
        counts = restore_django_config_tables_from_sqlserver()
        total = sum(counts.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"Restauration terminee: {len(counts)} tables, {total} lignes."
            )
        )
