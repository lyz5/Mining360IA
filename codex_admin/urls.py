from django.urls import path

from . import views


app_name = "codex_admin"

urlpatterns = [
    path("", views.home, name="home"),
    path("diagnostics/run/", views.run_diagnostic, name="run-diagnostic"),
]
