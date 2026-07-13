from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = 'reports'

    def ready(self):
        from . import sqlserver_config_store  # noqa: F401
