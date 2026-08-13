from __future__ import annotations

from django.utils import timezone

from .models import AIConversationArtifact


ARTIFACT_FIELDS = [
    ("follow_up_resolution", "follow_up_resolution", "Follow-up resolution trace"),
    ("response_envelope", "adaptive_response", "Adaptive response"),
    ("availability_diagnostics", "downtime_drivers", "Downtime diagnostics"),
    ("navigation", "powerbi_navigation", "Power BI navigation"),
    ("resource_knowledge", "knowledge_sources", "Knowledge sources"),
    ("sources", "document_citations", "Document citations"),
    ("rows", "table", "Analytical rows"),
    ("summary", "analytical_result", "Analytical summary"),
]


def artifacts_from_response(conversation, message, response_payload: dict) -> list[AIConversationArtifact]:
    parent_metadata = message.parent_message.metadata_json if message.parent_message else {}
    refresh_of = str((parent_metadata or {}).get("refresh_of_artifact_id") or "")
    superseded = AIConversationArtifact.objects.filter(
        pk=refresh_of,
        conversation=conversation,
        artifact_type="response_snapshot",
    ).first() if refresh_of else None
    version = (superseded.artifact_version + 1) if superseded else 1
    artifacts = [
        AIConversationArtifact(
            conversation=conversation,
            message=message,
            artifact_type="response_snapshot",
            title="Saved response",
            payload_json=response_payload,
            source_type="chat_pipeline",
            artifact_version=version,
            supersedes_artifact=superseded,
            refreshed_at=timezone.now() if superseded else None,
        )
    ]
    intent = response_payload.get("intent") or response_payload.get("semantic_request") or {}
    presentation = response_payload.get("presentation") or (response_payload.get("response_envelope") or {}).get("presentation") or {}
    filters = dict(intent.get("filters") or {})
    if intent.get("metric") or filters:
        artifacts.append(
            AIConversationArtifact(
                conversation=conversation,
                message=message,
                artifact_type="filter_snapshot",
                title="Historical analytical context",
                payload_json={
                    "metric": intent.get("metric") or response_payload.get("metric"),
                    "filters": filters,
                    "normalized_filters": filters,
                    "filter_resolution": response_payload.get("filter_resolution_snapshot") or [],
                    "semantic_model": (response_payload.get("navigation") or {}).get("semantic_model_id") or "",
                    "query_execution_reference": (response_payload.get("debug") or {}).get("interaction_log_id"),
                    "template_code": presentation.get("template_code") or "legacy_availability_response",
                    "template_version": presentation.get("template_version") or "legacy",
                    "component_order": presentation.get("components") or [],
                    "intent_snapshot": intent,
                    "scope_snapshot": intent.get("scope_type"),
                    "calculated_at": response_payload.get("calculated_at") or timezone.now().isoformat(),
                },
                source_type="chat_pipeline",
                artifact_version=version,
                refreshed_at=timezone.now() if superseded else None,
            )
        )
    for field, artifact_type, title in ARTIFACT_FIELDS:
        value = response_payload.get(field)
        if value in (None, "", [], {}):
            continue
        artifacts.append(
            AIConversationArtifact(
                conversation=conversation,
                message=message,
                artifact_type=artifact_type,
                title=title,
                payload_json={"value": value},
                source_type="chat_pipeline",
                source_reference=field,
            )
        )
    return AIConversationArtifact.objects.bulk_create(artifacts)


def serialize_artifact(artifact: AIConversationArtifact) -> dict:
    return {
        "id": str(artifact.id),
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "payload": artifact.payload_json,
        "source_type": artifact.source_type,
        "source_reference": artifact.source_reference,
        "status": artifact.status,
        "artifact_version": artifact.artifact_version,
        "supersedes_artifact_id": str(artifact.supersedes_artifact_id) if artifact.supersedes_artifact_id else None,
        "refreshed_at": artifact.refreshed_at.isoformat() if artifact.refreshed_at else None,
        "created_at": artifact.created_at.isoformat(),
    }
