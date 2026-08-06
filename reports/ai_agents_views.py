from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .access_control import is_platform_admin
from .agent_router_service import route_question, routing_rules_payload
from .ai_agent_execution_service import execute_agent_question
from .models import (
    AIAgent,
    AIAgentCapability,
    AIAgentDataSource,
    AIAgentExecutionLog,
    AIAgentIntent,
    AIAgentProviderConfiguration,
    AIAgentPrompt,
    AIAgentRoutingConfiguration,
    AIAgentTool,
    AIProvider,
    AIProviderModel,
    AIUseCaseConfiguration,
)


RELATED_MODELS = {
    "capabilities": (
        AIAgentCapability,
        ["capability_code", "display_name", "description", "enabled", "configuration_json", "priority", "validation_status"],
    ),
    "intents": (
        AIAgentIntent,
        ["intent_code", "display_name", "description", "examples_json", "required_entities_json", "optional_entities_json", "priority", "enabled", "validation_status"],
    ),
    "tools": (
        AIAgentTool,
        ["tool_code", "display_name", "description", "service_path", "enabled", "requires_confirmation", "timeout_seconds", "priority", "configuration_json", "validation_status"],
    ),
    "sources": (
        AIAgentDataSource,
        ["source_type", "source_reference", "source_name", "enabled", "read_only", "priority", "filters_json", "validation_status"],
    ),
    "prompts": (
        AIAgentPrompt,
        ["prompt_code", "prompt_type", "name", "content", "version", "enabled", "validation_status"],
    ),
}


def _denied(request):
    if is_platform_admin(request.user):
        return None
    return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)


def _payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _value(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _related_payload(item, fields):
    return {"id": item.pk, **{field: _value(getattr(item, field)) for field in fields}}


def _agent_payload(agent, *, detailed=False):
    base = {
        "id": agent.pk,
        "code": agent.code,
        "name": agent.name,
        "description": agent.description,
        "agent_type": agent.agent_type,
        "routing_mode": agent.routing_mode,
        "priority": agent.priority,
        "minimum_confidence": float(agent.minimum_confidence),
        "active": agent.active,
        "is_default": agent.is_default,
        "allow_combined_execution": agent.allow_combined_execution,
        "validation_status": agent.validation_status,
        "version": agent.version,
        "owner": agent.owner,
        "updated_at": agent.updated_at.isoformat(),
        "counts": {
            "capabilities": agent.capabilities.count(),
            "sources": agent.data_sources.count(),
            "intents": agent.intents.count(),
            "tools": agent.tools.count(),
        },
    }
    if not detailed:
        return base
    base.update({
        "system_instructions": agent.system_instructions,
        "response_instructions": agent.response_instructions,
        "clarification_instructions": agent.clarification_instructions,
        "combined_execution_instructions": agent.combined_execution_instructions,
        "default_language": agent.default_language,
        "routing_keywords": agent.routing_keywords,
        "exclusion_keywords": agent.exclusion_keywords,
        "clarification_message": agent.clarification_message,
        "created_at": agent.created_at.isoformat(),
        "validated_at": agent.validated_at.isoformat() if agent.validated_at else "",
    })
    for resource_type, (model, fields) in RELATED_MODELS.items():
        manager_name = "data_sources" if resource_type == "sources" else resource_type
        base[resource_type] = [
            _related_payload(item, fields)
            for item in getattr(agent, manager_name).all()
        ]
    permission = getattr(agent, "permission_config", None)
    base["permissions"] = {
        "allowed_role_ids": list(permission.allowed_roles.values_list("id", flat=True)) if permission else [],
        "allowed_user_ids": list(permission.allowed_users.values_list("id", flat=True)) if permission else [],
        "allowed_minesites": permission.allowed_minesites if permission else [],
        "allowed_customers": permission.allowed_customers if permission else [],
        "can_export": permission.can_export if permission else False,
        "can_access_comments": permission.can_access_comments if permission else False,
        "can_access_debug": permission.can_access_debug if permission else False,
    }
    return base


def _apply_agent(agent, data, user):
    text_fields = (
        "code", "name", "description", "agent_type", "system_instructions",
        "response_instructions", "clarification_instructions",
        "combined_execution_instructions", "default_language", "routing_mode",
        "clarification_message", "validation_status", "version", "owner",
    )
    for field in text_fields:
        if field in data:
            setattr(agent, field, str(data[field] or "").strip())
    for field in ("priority",):
        if field in data:
            setattr(agent, field, max(0, int(data[field] or 0)))
    if "minimum_confidence" in data:
        agent.minimum_confidence = Decimal(str(data["minimum_confidence"] or 0))
    for field in ("active", "is_default", "allow_combined_execution"):
        if field in data:
            setattr(agent, field, bool(data[field]))
    for field in ("routing_keywords", "exclusion_keywords"):
        if field in data and isinstance(data[field], list):
            setattr(agent, field, data[field])
    agent.updated_by = user
    if not agent.pk:
        agent.created_by = user
    if agent.validation_status == "Validated":
        agent.validated_by = user
        agent.validated_at = timezone.now()
    elif "validation_status" in data:
        agent.validated_by = None
        agent.validated_at = None
    if not agent.code or not agent.name:
        raise ValueError("Agent Code and Agent Name are required.")
    if agent.is_default:
        AIAgent.objects.filter(is_default=True).exclude(pk=agent.pk).update(is_default=False)
    agent.save()
    return agent


@login_required
def ai_agents_home(request):
    denied = _denied(request)
    if denied:
        return denied
    return render(request, "reports/ai_agents.html", {
        "active_section": "ai-agents",
        "sidebar_stats": [
            {"label": "Agents", "value": AIAgent.objects.count()},
            {"label": "Active", "value": AIAgent.objects.filter(active=True).count()},
        ],
    })


@login_required
@require_http_methods(["GET", "POST"])
def agents_collection_api(request):
    denied = _denied(request)
    if denied:
        return denied
    if request.method == "POST":
        try:
            agent = _apply_agent(AIAgent(), _payload(request), request.user)
            return JsonResponse({"ok": True, "agent": _agent_payload(agent, detailed=True)}, status=201)
        except (ValueError, TypeError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    agents = AIAgent.objects.prefetch_related("capabilities", "data_sources", "intents", "tools")
    logs = AIAgentExecutionLog.objects.filter(is_test=False)
    total = logs.count()
    successful = logs.filter(execution_status="Completed").count()
    summary = logs.aggregate(
        average_response_time=Avg("response_time_ms"),
        average_confidence=Avg("routing_confidence"),
        total_cost=Sum("estimated_cost"),
    )
    return JsonResponse({
        "ok": True,
        "agents": [_agent_payload(agent) for agent in agents],
        "summary": {
            "total_agents": agents.count(),
            "active_agents": agents.filter(active=True).count(),
            "validated_agents": agents.filter(validation_status="Validated").count(),
            "routing_success_rate": round(successful / total * 100, 1) if total else 0,
            "clarification_rate": round(
                logs.filter(execution_status="Clarification Required").count() / total * 100, 1
            ) if total else 0,
            "combined_executions": logs.filter(selected_agent_code="combined").count(),
            "average_response_time": round(float(summary["average_response_time"] or 0)),
            "api_cost": float(summary["total_cost"] or 0),
        },
    })


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def agent_item_api(request, agent_id):
    denied = _denied(request)
    if denied:
        return denied
    agent = get_object_or_404(AIAgent, pk=agent_id)
    if request.method == "GET":
        return JsonResponse({"ok": True, "agent": _agent_payload(agent, detailed=True)})
    if request.method == "DELETE":
        if agent.code in {"machine_performance", "mining_knowledge"}:
            return JsonResponse(
                {"ok": False, "error": "Bootstrap agents cannot be deleted. Deactivate them instead."},
                status=409,
            )
        agent.delete()
        return JsonResponse({"ok": True})
    try:
        _apply_agent(agent, _payload(request), request.user)
        return JsonResponse({"ok": True, "agent": _agent_payload(agent, detailed=True)})
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@login_required
@require_http_methods(["GET", "POST"])
def agent_components_api(request, agent_id, resource_type):
    denied = _denied(request)
    if denied:
        return denied
    agent = get_object_or_404(AIAgent, pk=agent_id)
    if resource_type not in RELATED_MODELS:
        return JsonResponse({"ok": False, "error": "Unsupported agent resource."}, status=404)
    model, fields = RELATED_MODELS[resource_type]
    if request.method == "POST":
        data = _payload(request)
        values = {field: data[field] for field in fields if field in data}
        try:
            item = model.objects.create(agent=agent, **values)
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        return JsonResponse({"ok": True, "item": _related_payload(item, fields)}, status=201)
    return JsonResponse({
        "ok": True,
        "items": [_related_payload(item, fields) for item in model.objects.filter(agent=agent)],
    })


def _agent_provider_payload(item):
    return {
        "id": item.id,
        "use_case_id": item.use_case_id,
        "use_case": item.use_case.use_case_code,
        "use_case_name": item.use_case.display_name,
        "provider_id": item.provider_id,
        "provider": item.provider.name,
        "model_id": item.model_id,
        "model": item.model.display_name if item.model else "",
        "priority": item.priority,
        "fallback_enabled": item.fallback_enabled,
        "active": item.active,
    }


@login_required
@require_http_methods(["GET", "POST"])
def agent_provider_configurations_api(request, agent_id):
    denied = _denied(request)
    if denied:
        return denied
    agent = get_object_or_404(AIAgent, pk=agent_id)
    if request.method == "POST":
        data = _payload(request)
        use_case = get_object_or_404(AIUseCaseConfiguration, pk=data.get("use_case_id"))
        provider = get_object_or_404(AIProvider, pk=data.get("provider_id"))
        provider_model = None
        if data.get("model_id"):
            provider_model = get_object_or_404(
                AIProviderModel,
                pk=data["model_id"],
                provider=provider,
            )
        item, _ = AIAgentProviderConfiguration.objects.update_or_create(
            agent=agent,
            use_case=use_case,
            provider=provider,
            defaults={
                "model": provider_model,
                "priority": max(0, int(data.get("priority") or 100)),
                "fallback_enabled": bool(data.get("fallback_enabled", True)),
                "active": bool(data.get("active", True)),
            },
        )
        return JsonResponse({"ok": True, "item": _agent_provider_payload(item)})
    return JsonResponse({
        "ok": True,
        "items": [
            _agent_provider_payload(item)
            for item in agent.provider_configurations.select_related(
                "use_case", "provider", "model"
            )
        ],
        "use_cases": [
            {"id": item.id, "code": item.use_case_code, "name": item.display_name}
            for item in AIUseCaseConfiguration.objects.filter(active=True)
        ],
        "providers": [
            {"id": item.id, "code": item.code, "name": item.name}
            for item in AIProvider.objects.all()
        ],
        "models": [
            {
                "id": item.id,
                "provider_id": item.provider_id,
                "code": item.model_code,
                "name": item.display_name,
            }
            for item in AIProviderModel.objects.filter(active=True)
        ],
    })


@login_required
@require_http_methods(["PATCH", "DELETE"])
def agent_component_item_api(request, agent_id, resource_type, item_id):
    denied = _denied(request)
    if denied:
        return denied
    if resource_type not in RELATED_MODELS:
        return JsonResponse({"ok": False, "error": "Unsupported agent resource."}, status=404)
    model, fields = RELATED_MODELS[resource_type]
    item = get_object_or_404(model, pk=item_id, agent_id=agent_id)
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True})
    data = _payload(request)
    for field in fields:
        if field in data:
            setattr(item, field, data[field])
    try:
        item.save()
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "item": _related_payload(item, fields)})


@login_required
@require_http_methods(["GET", "PATCH"])
def router_configuration_api(request):
    denied = _denied(request)
    if denied:
        return denied
    config = AIAgentRoutingConfiguration.objects.select_related("default_agent").first()
    if not config:
        return JsonResponse({"ok": False, "error": "Router configuration is missing."}, status=404)
    if request.method == "PATCH":
        data = _payload(request)
        for field in (
            "feature_mode", "routing_enabled", "deterministic_routing_enabled",
            "ai_fallback_enabled", "minimum_confidence", "combined_execution_enabled",
            "manual_selection_enabled", "clarification_behavior",
            "routing_timeout_seconds", "routing_prompt",
        ):
            if field in data:
                setattr(config, field, data[field])
        if "default_agent_id" in data:
            config.default_agent_id = data["default_agent_id"] or None
        config.save()
    return JsonResponse({"ok": True, "configuration": {
        "id": config.pk,
        "feature_mode": config.feature_mode,
        "routing_enabled": config.routing_enabled,
        "deterministic_routing_enabled": config.deterministic_routing_enabled,
        "ai_fallback_enabled": config.ai_fallback_enabled,
        "default_agent_id": config.default_agent_id,
        "minimum_confidence": float(config.minimum_confidence),
        "combined_execution_enabled": config.combined_execution_enabled,
        "manual_selection_enabled": config.manual_selection_enabled,
        "clarification_behavior": config.clarification_behavior,
        "routing_timeout_seconds": config.routing_timeout_seconds,
        "routing_prompt": config.routing_prompt,
        "rules": routing_rules_payload(),
    }})


@login_required
@require_POST
def router_test_api(request):
    denied = _denied(request)
    if denied:
        return denied
    data = _payload(request)
    question = str(data.get("question") or "").strip()
    if not question:
        return JsonResponse({"ok": False, "error": "Question is required."}, status=400)
    result = route_question(
        question,
        user=request.user,
        conversation_id=str(data.get("conversation_id") or ""),
        manual_agent=str(data.get("manual_agent") or "auto"),
    )
    return JsonResponse({"ok": True, "routing": result})


@login_required
@require_POST
def agent_test_api(request, agent_id):
    denied = _denied(request)
    if denied:
        return denied
    agent = get_object_or_404(AIAgent, pk=agent_id)
    data = _payload(request)
    question = str(data.get("question") or "").strip()
    if not question:
        return JsonResponse({"ok": False, "error": "Question is required."}, status=400)
    try:
        result = execute_agent_question(
            question,
            user=request.user,
            conversation_id=str(data.get("conversation_id") or f"agent-test-{request.user.pk}"),
            manual_agent=agent.code,
            debug_mode=True,
            is_test=True,
        )
        return JsonResponse(result)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@require_GET
def agent_logs_api(request):
    denied = _denied(request)
    if denied:
        return denied
    logs = AIAgentExecutionLog.objects.select_related("selected_agent")[:200]
    return JsonResponse({"ok": True, "logs": [{
        "id": str(item.id),
        "question": item.question,
        "selected_agent": item.selected_agent_code,
        "routing_method": item.routing_method,
        "routing_confidence": float(item.routing_confidence),
        "intent": item.intent,
        "status": item.execution_status,
        "response_time_ms": item.response_time_ms,
        "estimated_cost": float(item.estimated_cost),
        "is_test": item.is_test,
        "created_at": item.created_at.isoformat(),
    } for item in logs]})
