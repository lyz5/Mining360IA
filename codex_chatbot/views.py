from __future__ import annotations

import json

from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from .access import codex_chatbot_access_required
from .async_service import RunConflictError, enqueue_run, request_cancellation, run_payload
from .fleet_export import artifact_path, create_fleet_csv
from .models import CodexArtifact, CodexConversation, CodexRun
from .orchestrator import ask


def _conversation_payload(conversation: CodexConversation) -> dict:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "status": conversation.status,
        "updated_at": conversation.updated_at.isoformat(),
        "messages": [
            {
                "id": str(message.id),
                "role": message.role,
                "content": message.content,
                "answer_status": message.answer_status,
                "created_at": message.created_at.isoformat(),
            }
            for message in conversation.messages.all()
        ],
        "runs": [run_payload(run) for run in conversation.runs.all()],
    }


@require_GET
@codex_chatbot_access_required
def home(request, conversation_id=None):
    conversations = CodexConversation.objects.filter(owner=request.user, status="ACTIVE")[:50]
    selected = None
    if conversation_id:
        selected = get_object_or_404(CodexConversation, id=conversation_id, owner=request.user)
    active_run = None
    if selected:
        active_run = selected.runs.filter(
            status__in=["QUEUED", "RUNNING", "CANCEL_REQUESTED"]
        ).order_by("-created_at").first()
    return render(
        request,
        "codex_chatbot/home.html",
        {
            "active_section": "codex-chatbot",
            "conversations": conversations,
            "selected_conversation": selected,
            "active_run": active_run,
        },
    )


@require_GET
@codex_chatbot_access_required
def conversation_api(request, conversation_id):
    conversation = get_object_or_404(
        CodexConversation.objects.prefetch_related("messages", "runs__evidence", "runs__artifacts"),
        id=conversation_id,
        owner=request.user,
    )
    return JsonResponse({"ok": True, "conversation": _conversation_payload(conversation)})


@require_POST
@codex_chatbot_access_required
def ask_api(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)
    question = str(payload.get("question") or "").strip()
    if not question:
        return JsonResponse({"ok": False, "error": "Question is required."}, status=400)
    conversation = None
    conversation_id = payload.get("conversation_id")
    if conversation_id:
        conversation = get_object_or_404(CodexConversation, id=conversation_id, owner=request.user)
    try:
        result = ask(user=request.user, question=question, conversation=conversation)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **result})


@require_POST
@codex_chatbot_access_required
def submit_run_api(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)
    conversation = None
    conversation_id = payload.get("conversation_id")
    if conversation_id:
        conversation = get_object_or_404(CodexConversation, id=conversation_id, owner=request.user)
    try:
        run, created = enqueue_run(
            user=request.user,
            question=str(payload.get("question") or ""),
            request_id=str(payload.get("request_id") or ""),
            conversation=conversation,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except RunConflictError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=409)
    return JsonResponse({"ok": True, "created": created, "run": run_payload(run)}, status=202)


@require_GET
@codex_chatbot_access_required
def run_status_api(request, run_id):
    run = get_object_or_404(
        CodexRun.objects.select_related("result_message", "conversation").prefetch_related("evidence"),
        id=run_id,
        user=request.user,
    )
    return JsonResponse({"ok": True, "run": run_payload(run)})


@require_POST
@codex_chatbot_access_required
def cancel_run_api(request, run_id):
    run = get_object_or_404(CodexRun, id=run_id, user=request.user)
    run = request_cancellation(run)
    return JsonResponse({"ok": True, "run": run_payload(run)})


@require_POST
@codex_chatbot_access_required
def create_export_api(request, run_id):
    run = get_object_or_404(CodexRun, id=run_id, user=request.user)
    try:
        artifact = create_fleet_csv(run)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({
        "ok": True,
        "artifact": {
            "id": str(artifact.id),
            "title": artifact.title,
            "row_count": artifact.row_count,
            "download_url": f"/codex-chatbot/api/artifacts/{artifact.id}/download/",
        },
    })


@require_GET
@codex_chatbot_access_required
def download_artifact(request, artifact_id):
    artifact = get_object_or_404(CodexArtifact, id=artifact_id, owner=request.user)
    path = artifact_path(artifact)
    if not path.is_file():
        return JsonResponse({"ok": False, "error": "The export file is unavailable."}, status=404)
    return FileResponse(path.open("rb"), content_type=artifact.content_type, as_attachment=True, filename=artifact.title)
