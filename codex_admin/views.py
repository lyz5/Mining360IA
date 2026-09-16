from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .access import codex_admin_access_required
from .diagnostics import build_read_only_diagnostic
from .models import CodexDiagnosticRun


@require_GET
@codex_admin_access_required
def home(request):
    return render(
        request,
        "codex_admin/home.html",
        {
            "active_section": "codex-admin",
            "latest_run": CodexDiagnosticRun.objects.filter(requested_by=request.user).first(),
        },
    )


@require_POST
@codex_admin_access_required
def run_diagnostic(request):
    run = CodexDiagnosticRun.objects.create(
        requested_by=request.user,
        summary_json=build_read_only_diagnostic(),
    )
    return render(
        request,
        "codex_admin/home.html",
        {
            "active_section": "codex-admin",
            "latest_run": run,
        },
    )
