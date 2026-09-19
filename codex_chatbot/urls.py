from django.urls import path

from . import views


app_name = "codex_chatbot"

urlpatterns = [
    path("api/conversations/<uuid:conversation_id>/status/", views.history_status, name="history-status"),
    path("api/conversations/<uuid:conversation_id>/download/", views.history_download, name="history-download"),
    path("", views.home, name="home"),
    path("c/<uuid:conversation_id>/", views.home, name="conversation"),
    path("api/ask/", views.ask_api, name="ask"),
    path("api/runs/", views.submit_run_api, name="submit-run"),
    path("api/runs/<uuid:run_id>/", views.run_status_api, name="run-status"),
    path("api/runs/<uuid:run_id>/cancel/", views.cancel_run_api, name="cancel-run"),
    path("api/runs/<uuid:run_id>/export/", views.create_export_api, name="create-export"),
    path("api/artifacts/<uuid:artifact_id>/download/", views.download_artifact, name="download-artifact"),
    path("api/conversations/<uuid:conversation_id>/", views.conversation_api, name="conversation-api"),
]
