"""Owner-scoped conversation management shared by the UI and local maintenance."""
from django.db import transaction
from reports.models import AIConversation
from .models import CodexConversation
from .async_service import ACTIVE_RUN_STATUSES, RunConflictError
from .fleet_export import artifact_path


@transaction.atomic
def delete_conversation(*, conversation_id, user):
    conversation = CodexConversation.objects.select_for_update().get(pk=conversation_id, owner=user)
    if conversation.runs.filter(status__in=ACTIVE_RUN_STATUSES).exists():
        raise RunConflictError("Cancel the current request before deleting this conversation.")
    # Resolve every file against the configured artifact root before any deletion.
    paths = [artifact_path(a) for run in conversation.runs.all() for a in run.artifacts.all()]
    if conversation.legacy_conversation_id:
        AIConversation.objects.filter(pk=conversation.legacy_conversation_id, user=user).delete()
    conversation.delete()
    def remove_exports():
        for path in paths:
            path.unlink(missing_ok=True)
    transaction.on_commit(remove_exports)
