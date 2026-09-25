from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from codex_integration.contracts import RunStatus

from .models import CodexConversation, CodexMessage, CodexRun
from .orchestrator import TERMINAL_RUN_STATUSES, _deterministic_answer, execute_persisted_run


ACTIVE_RUN_STATUSES = {
    RunStatus.QUEUED,
    RunStatus.RUNNING,
    RunStatus.CANCEL_REQUESTED,
}


class RunConflictError(RuntimeError):
    pass


def enqueue_run(*, user, question: str, request_id: str, conversation=None) -> tuple[CodexRun, bool]:
    question = (question or "").strip()
    if not question:
        raise ValueError("Question is required.")
    try:
        run_id = uuid.UUID(str(request_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("A valid request_id is required.") from exc
    if conversation is not None and conversation.owner_id != user.id:
        raise PermissionError("Conversation does not belong to this user.")

    with transaction.atomic():
        existing = CodexRun.objects.select_related("conversation").filter(id=run_id).first()
        if existing:
            if existing.user_id != user.id or existing.question != question:
                raise RunConflictError("The request identifier is already in use.")
            return existing, False
        if conversation is not None and conversation.runs.filter(status__in=ACTIVE_RUN_STATUSES).exists():
            raise RunConflictError("A request is already running in this conversation.")
        if conversation is None:
            conversation = CodexConversation.objects.create(
                owner=user,
                title=question[:177] + ("..." if len(question) > 177 else ""),
            )
        CodexMessage.objects.create(conversation=conversation, role="USER", content=question)
        run = CodexRun.objects.create(
            id=run_id,
            conversation=conversation,
            user=user,
            question=question,
            status=RunStatus.QUEUED,
            progress_percent=0,
            progress_label="Request saved, waiting for M360 AI.",
            heartbeat_at=timezone.now(),
        )
    return run, True


def run_payload(run: CodexRun) -> dict:
    message = run.result_message
    evidence = run.evidence.order_by("retrieved_at").first()
    provisional_message = None
    if evidence and evidence.value_json.get("kind") != "web_sources" and message is None and run.status in ACTIVE_RUN_STATUSES:
        provisional_message = {
            "role": "ASSISTANT",
            "content": _deterministic_answer(evidence.value_json),
            "answer_status": "VERIFIED_FACTS",
        }
    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "status": run.status,
        "progress_percent": run.progress_percent,
        "progress_label": run.progress_label,
        "terminal": run.status in TERMINAL_RUN_STATUSES,
        "can_cancel": run.status in {RunStatus.QUEUED, RunStatus.RUNNING},
        "message": None if message is None else {
            "id": str(message.id),
            "role": message.role,
            "content": message.content,
            "answer_status": message.answer_status,
        },
        "provisional_message": provisional_message,
        "runtime": {
            "native_thread_active": bool(run.native_thread_id),
            "native_turn_active": bool(run.native_turn_id),
        },
        "evidence_count": run.evidence.count(),
        "result": evidence.value_json if evidence else None,
        "artifacts": [
            {"id": str(item.id), "title": item.title, "row_count": item.row_count}
            for item in run.artifacts.all()
        ],
    }


def request_cancellation(run: CodexRun) -> CodexRun:
    with transaction.atomic():
        run = CodexRun.objects.select_for_update().get(id=run.id)
        if run.status == RunStatus.QUEUED:
            run.status = RunStatus.CANCELLED
            run.progress_percent = 100
            run.progress_label = "Request cancelled."
            run.completed_at = timezone.now()
        elif run.status == RunStatus.RUNNING:
            run.status = RunStatus.CANCEL_REQUESTED
            run.progress_label = "Cancellation requested..."
        run.heartbeat_at = timezone.now()
        run.save()
    return run


def process_next_run() -> CodexRun | None:
    with transaction.atomic():
        run = (
            CodexRun.objects.select_for_update()
            .select_related("conversation", "user")
            .filter(status=RunStatus.QUEUED)
            .order_by("created_at")
            .first()
        )
        if run is None:
            return None
        run.status = RunStatus.RUNNING
        run.started_at = run.started_at or timezone.now()
        run.progress_label = "Processing started."
        run.heartbeat_at = timezone.now()
        run.save(update_fields=["status", "started_at", "progress_label", "heartbeat_at"])

    try:
        execute_persisted_run(run)
    except Exception as exc:
        run.refresh_from_db()
        if run.status not in TERMINAL_RUN_STATUSES:
            run.status = RunStatus.FAILED
            run.error_code = "CODEX_RUN_FAILED"
            run.error_message = str(exc)
            run.progress_percent = 100
            run.progress_label = "Processing failed."
            run.completed_at = timezone.now()
            run.heartbeat_at = timezone.now()
            run.save()
    return run
