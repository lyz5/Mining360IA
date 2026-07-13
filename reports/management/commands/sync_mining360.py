import getpass
import os

from django.core.management.base import BaseCommand

from reports.mining360_repository import sync_mining360_tables
from reports.sqlserver import DEFAULT_DATABASE, DEFAULT_SERVER


class Command(BaseCommand):
    help = "Create and synchronize Mining360IA SQL Server tables."

    def add_arguments(self, parser):
        parser.add_argument("--server", default=DEFAULT_SERVER)
        parser.add_argument("--database", default=DEFAULT_DATABASE)
        parser.add_argument("--driver", default=None)
        parser.add_argument("--user", default=os.getenv("MINING360_SQL_USER"))
        parser.add_argument(
            "--password",
            default=os.getenv("MINING360_SQL_PASSWORD") or os.getenv("SQLSERVER_PASSWORD"),
        )
        parser.add_argument(
            "--trusted",
            action="store_true",
            help="Use Windows integrated authentication instead of SQL authentication.",
        )

    def handle(self, *args, **options):
        os.environ["MINING360_SQL_SERVER"] = options["server"]
        os.environ["MINING360_SQL_DATABASE"] = options["database"]
        if options["driver"]:
            os.environ["MINING360_SQL_DRIVER"] = options["driver"]
        if options["trusted"]:
            os.environ.pop("MINING360_SQL_USER", None)
            os.environ.pop("MINING360_SQL_PASSWORD", None)
        elif options["user"]:
            os.environ["MINING360_SQL_USER"] = options["user"]
            password = options["password"] or getpass.getpass("SQL Server password: ")
            os.environ["MINING360_SQL_PASSWORD"] = password

        self.stdout.write(
            f"Connexion SQL Server: serveur={options['server']}, base={options['database']}"
        )
        result = sync_mining360_tables()
        config_total = sum(result.get("config_tables", {}).values())
        live_sources = result.get("live_sources", {})
        self.stdout.write(
            self.style.SUCCESS(
                "Synchronisation terminee: "
                f"{result['aliases']} alias de rapports, "
                f"{result['resources']} ressources, "
                f"{len(result.get('config_tables', {}))} tables de configuration "
                f"({config_total} lignes), "
                f"{live_sources.get('sources', 0)} sources, "
                f"{live_sources.get('custom_views', 0)} custom views."
            )
        )
