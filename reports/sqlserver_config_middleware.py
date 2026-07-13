from .sqlserver_config_store import flush_pending_config_syncs_async


class SQLServerConfigSyncMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        flush_pending_config_syncs_async()
        return response
