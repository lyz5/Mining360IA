from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .access_control import is_platform_admin
from .models import (
    ResourceKnowledgeDocument,
    ResourceKnowledgeIndexRun,
    ResourceKnowledgeItem,
    ResourceKnowledgeRetrievalLog,
)
from .resource_knowledge_ai_service import (
    embedding_model,
    extraction_model,
    extraction_reasoning_effort,
)
from .resource_knowledge_index_service import preview_library, start_index_job
from .resource_knowledge_search_service import search_resource_knowledge


def _admin_error(request):
    if is_platform_admin(request.user):
        return None
    return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)


@login_required
def knowledge_admin(request):
    denied = _admin_error(request)
    if denied:
        return denied
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    documents = ResourceKnowledgeDocument.objects.annotate(
        validated_count=Count(
            "knowledge_items",
            filter=Q(knowledge_items__validation_status="Validated", knowledge_items__is_active=True),
        ),
        review_count=Count(
            "knowledge_items",
            filter=Q(knowledge_items__validation_status="To Review", knowledge_items__is_active=True),
        ),
    )
    if query:
        documents = documents.filter(
            Q(title__icontains=query)
            | Q(filename__icontains=query)
            | Q(section__icontains=query)
            | Q(category__icontains=query)
        )
    if status:
        documents = documents.filter(status=status)
    item_counts = {
        row["validation_status"]: row["count"]
        for row in ResourceKnowledgeItem.objects.filter(is_active=True)
        .values("validation_status")
        .annotate(count=Count("id"))
    }
    return render(request, "reports/resource_knowledge.html", {
        "active_section": "resources",
        "documents": documents[:250],
        "runs": ResourceKnowledgeIndexRun.objects.all()[:10],
        "recent_items": ResourceKnowledgeItem.objects.select_related("document").filter(is_active=True)[:100],
        "query": query,
        "selected_status": status,
        "stats": {
            "documents": ResourceKnowledgeDocument.objects.count(),
            "indexed": ResourceKnowledgeDocument.objects.filter(status="Indexed").count(),
            "chunks": sum(ResourceKnowledgeDocument.objects.values_list("chunk_count", flat=True)),
            "knowledge": ResourceKnowledgeItem.objects.filter(is_active=True).count(),
            "validated": item_counts.get("Validated", 0),
            "to_review": item_counts.get("To Review", 0),
            "retrievals": ResourceKnowledgeRetrievalLog.objects.count(),
        },
        "extraction_model": extraction_model(),
        "extraction_reasoning_effort": extraction_reasoning_effort(),
        "embedding_model": embedding_model(),
    })


@login_required
@require_GET
def knowledge_preview_api(request):
    denied = _admin_error(request)
    if denied:
        return denied
    return JsonResponse({"ok": True, "preview": preview_library(
        with_ai=False,
        with_embeddings=False,
        resource_id=request.GET.get("resource_id", "").strip(),
    )})


@login_required
@require_POST
def knowledge_rebuild_api(request):
    denied = _admin_error(request)
    if denied:
        return denied
    is_json = "application/json" in request.headers.get("Content-Type", "")
    data = json.loads(request.body or "{}") if is_json else request.POST
    def selected(name, default=True):
        value = data.get(name, default)
        return value if isinstance(value, bool) else str(value).lower() in {"1", "true", "on", "yes"}
    run = start_index_job(
        user=request.user,
        resource_id=str(data.get("resource_id") or ""),
        with_ai=False,
        with_embeddings=False,
        force=selected("force", False),
    )
    if not is_json:
        messages.success(request, f"Knowledge creation started (run {run.id}).")
        return redirect("resource-knowledge-admin")
    return JsonResponse({"ok": True, "run_id": str(run.id), "status": run.status})


@login_required
@require_GET
def knowledge_run_api(request, run_id):
    denied = _admin_error(request)
    if denied:
        return denied
    run = get_object_or_404(ResourceKnowledgeIndexRun, pk=run_id)
    return JsonResponse({
        "ok": True,
        "run": {
            "id": str(run.id),
            "status": run.status,
            "total_documents": run.total_documents,
            "processed_documents": run.processed_documents,
            "indexed_documents": run.indexed_documents,
            "skipped_documents": run.skipped_documents,
            "failed_documents": run.failed_documents,
            "chunks_created": run.chunks_created,
            "knowledge_created": run.knowledge_created,
            "embeddings_created": run.embeddings_created,
            "error_message": run.error_message,
        },
    })


@login_required
@require_http_methods(["GET", "POST"])
def knowledge_item_api(request, item_id):
    denied = _admin_error(request)
    if denied:
        return denied
    item = get_object_or_404(ResourceKnowledgeItem, pk=item_id)
    if request.method == "GET":
        return JsonResponse({"ok": True, "item": {
            "id": str(item.id),
            "title": item.title,
            "business_domain": item.business_domain,
            "equipment": item.equipment,
            "equipment_model": item.equipment_model,
            "system": item.system,
            "component": item.component,
            "subcomponent": item.subcomponent,
            "symptom": item.symptom,
            "failure_mode": item.failure_mode,
            "fault_codes": item.fault_codes,
            "probable_causes": item.probable_causes,
            "occurrence_conditions": item.occurrence_conditions,
            "possible_impacts": item.possible_impacts,
            "inspection_procedure": item.inspection_procedure,
            "troubleshooting_procedure": item.troubleshooting_procedure,
            "best_practices": item.best_practices,
            "recommendations": item.recommendations,
            "safety_instructions": item.safety_instructions,
            "criticality": item.criticality,
            "confidence": float(item.confidence),
            "validation_status": item.validation_status,
            "validation_notes": item.validation_notes,
            "is_active": item.is_active,
            "source": {
                "document": item.document.title,
                "page": item.source_page,
                "excerpt": item.source_excerpt,
            },
        }})
    data = json.loads(request.body or "{}")
    allowed = {
        "title", "business_domain", "equipment", "equipment_model", "system",
        "component", "subcomponent", "symptom", "failure_mode",
        "occurrence_conditions", "possible_impacts", "inspection_procedure",
        "troubleshooting_procedure", "criticality", "validation_notes",
    }
    for field in allowed:
        if field in data:
            setattr(item, field, str(data[field] or ""))
    for field in (
        "fault_codes", "probable_causes", "best_practices", "recommendations",
        "safety_instructions",
    ):
        if field in data and isinstance(data[field], list):
            setattr(item, field, [str(value).strip() for value in data[field] if str(value).strip()])
    if "validation_status" in data:
        status = str(data["validation_status"])
        if status not in dict(ResourceKnowledgeItem.VALIDATION_STATUSES):
            return JsonResponse({"ok": False, "error": "Invalid validation status."}, status=400)
        item.validation_status = status
        if status == "Validated":
            item.validated_by = request.user
            item.validated_at = timezone.now()
        elif status in {"Draft", "To Review", "Rejected"}:
            item.validated_by = None
            item.validated_at = None
    if "is_active" in data:
        item.is_active = bool(data["is_active"])
    item.save()
    return JsonResponse({"ok": True, "id": str(item.id), "status": item.validation_status})


@login_required
@require_POST
def knowledge_search_api(request):
    denied = _admin_error(request)
    if denied:
        return denied
    data = json.loads(request.body or "{}")
    query = str(data.get("query") or "").strip()
    if not query:
        return JsonResponse({"ok": False, "error": "Query is required."}, status=400)
    result = search_resource_knowledge(
        query,
        filters=data.get("filters") or {},
        limit=int(data.get("limit") or 5),
        mode=str(data.get("mode") or "Debug"),
        user=request.user,
        use_embeddings=False,
    )
    return JsonResponse({"ok": True, **result})
