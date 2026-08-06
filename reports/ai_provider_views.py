from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .access_control import is_platform_admin
from .ai_provider_bootstrap_service import bootstrap_ai_providers
from .ai_provider_credential_service import (
    credential_configured,
    masked_credential,
    set_provider_secret,
)
from .ai_provider_gateway_service import ai_gateway
from .ai_provider_health_service import check_all_providers, check_provider_health
from .models import (
    AIProvider,
    AIProviderAuditLog,
    AIProviderHealthLog,
    AIProviderModel,
    AIProviderUsageLog,
    AIUseCaseConfiguration,
)


def _denied(request):
    if is_platform_admin(request.user):
        return None
    return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)


def _payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _decimal(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _model_payload(model):
    return {
        "id": model.id,
        "provider_id": model.provider_id,
        "provider": model.provider.name,
        "model_code": model.model_code,
        "display_name": model.display_name,
        "description": model.description,
        "model_family": model.model_family,
        "context_window": model.context_window,
        "maximum_output_tokens": model.maximum_output_tokens,
        "capabilities": model.capabilities_json,
        "supports_streaming": model.supports_streaming,
        "supports_structured_output": model.supports_structured_output,
        "supports_tool_calling": model.supports_tool_calling,
        "supports_vision": model.supports_vision,
        "supports_embeddings": model.supports_embeddings,
        "supports_audio_transcription": model.supports_audio_transcription,
        "supports_text_to_speech": model.supports_text_to_speech,
        "input_cost_per_million": float(model.input_cost_per_million) if model.input_cost_per_million is not None else None,
        "output_cost_per_million": float(model.output_cost_per_million) if model.output_cost_per_million is not None else None,
        "cached_input_cost_per_million": float(model.cached_input_cost_per_million) if model.cached_input_cost_per_million is not None else None,
        "currency": model.currency,
        "pricing_notes": model.pricing_notes,
        "active": model.active,
        "is_default_for_provider": model.is_default_for_provider,
        "validation_status": model.validation_status,
    }


def _provider_payload(provider, detailed=False):
    usage = provider.usage_logs.aggregate(
        requests=Count("id"),
        success=Count("id", filter=Q(status="completed")),
        latency=Avg("latency_ms"),
        spend=Sum("estimated_cost"),
    )
    requests = int(usage["requests"] or 0)
    success = int(usage["success"] or 0)
    data = {
        "id": provider.id,
        "code": provider.code,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "description": provider.description,
        "base_url": provider.base_url,
        "api_version": provider.api_version,
        "auth_type": provider.auth_type,
        "priority": provider.priority,
        "selection_mode": provider.selection_mode,
        "is_default": provider.is_default,
        "active": provider.active,
        "allow_fallback": provider.allow_fallback,
        "status": provider.status,
        "timeout_seconds": provider.timeout_seconds,
        "retry_count": provider.retry_count,
        "retry_backoff_seconds": provider.retry_backoff_seconds,
        "requests_per_minute": provider.requests_per_minute,
        "tokens_per_minute": provider.tokens_per_minute,
        "maximum_concurrent_requests": provider.maximum_concurrent_requests,
        "daily_budget": float(provider.daily_budget) if provider.daily_budget is not None else None,
        "monthly_budget": float(provider.monthly_budget) if provider.monthly_budget is not None else None,
        "currency": provider.currency,
        "capabilities": provider.capabilities_json,
        "credential_status": masked_credential(provider),
        "credential_configured": credential_configured(provider),
        "last_health_check_at": provider.last_health_check_at.isoformat() if provider.last_health_check_at else "",
        "last_error_code": provider.last_error_code,
        "last_error_message": provider.last_error_message,
        "success_rate": round(success * 100 / requests, 1) if requests else None,
        "average_latency": round(float(usage["latency"] or 0), 1),
        "current_spend": float(usage["spend"] or 0),
        "model_count": provider.models.count(),
    }
    if detailed:
        data["models"] = [_model_payload(item) for item in provider.models.all()]
        data["configuration"] = provider.configuration_json
    return data


def _use_case_payload(item):
    return {
        "id": item.id,
        "use_case_code": item.use_case_code,
        "display_name": item.display_name,
        "description": item.description,
        "primary_provider_id": item.primary_provider_id,
        "primary_provider": item.primary_provider.name if item.primary_provider else "",
        "primary_model_id": item.primary_model_id,
        "primary_model": item.primary_model.display_name if item.primary_model else "",
        "selection_mode": item.selection_mode,
        "fallback_enabled": item.fallback_enabled,
        "fallback_providers": item.fallback_providers_json,
        "required_capabilities": item.required_capabilities_json,
        "temperature": float(item.temperature),
        "maximum_output_tokens": item.maximum_output_tokens,
        "timeout_seconds": item.timeout_seconds,
        "retry_count": item.retry_count,
        "structured_output_required": item.structured_output_required,
        "streaming_enabled": item.streaming_enabled,
        "active": item.active,
        "validation_status": item.validation_status,
    }


@login_required
def api_management_home(request):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    bootstrap_ai_providers()
    providers = [
        _provider_payload(item)
        for item in AIProvider.objects.prefetch_related("models", "credentials")
    ]
    return render(request, "reports/api_management.html", {
        "active_section": "api-management",
        "initial_providers": providers,
        "credential_saved": request.GET.get("credential_saved") == "1",
    })


@login_required
@require_http_methods(["GET", "POST"])
def provider_credential_page(request, provider_id):
    if not is_platform_admin(request.user):
        return JsonResponse(
            {"ok": False, "error": "Administrator access required."},
            status=403,
        )
    provider = get_object_or_404(AIProvider, id=provider_id)
    error = ""
    if request.method == "POST":
        try:
            set_provider_secret(provider, request.POST.get("credential", ""))
            if request.POST.get("activate") == "on":
                provider.active = True
                provider.status = "active"
                provider.updated_by = request.user
                provider.save(update_fields=["active", "status", "updated_by", "updated_at"])
            AIProviderAuditLog.objects.create(
                provider=provider,
                user=request.user,
                action="credential_replaced",
            )
            return redirect("/ai-config/api-management/?credential_saved=1")
        except ValueError as exc:
            error = str(exc)
    return render(request, "reports/ai_provider_credential.html", {
        "active_section": "api-management",
        "provider": provider,
        "credential_status": masked_credential(provider),
        "error": error,
    })


@login_required
@require_http_methods(["GET", "POST"])
def provider_test_page(request, provider_id):
    if not is_platform_admin(request.user):
        return JsonResponse(
            {"ok": False, "error": "Administrator access required."},
            status=403,
        )
    provider = get_object_or_404(AIProvider, id=provider_id)
    active_model = (
        provider.models.filter(is_default_for_provider=True, active=True).first()
        or provider.models.filter(active=True).first()
    )
    result = None
    error = ""
    if request.method == "POST":
        try:
            result = check_provider_health(provider)
            AIProviderAuditLog.objects.create(
                provider=provider,
                user=request.user,
                action="connection_test",
            )
        except Exception as exc:
            error = str(exc)
    return render(request, "reports/ai_provider_test.html", {
        "active_section": "api-management",
        "provider": provider,
        "credential_status": masked_credential(provider),
        "active_model": active_model,
        "result": result,
        "error": error,
    })


@login_required
@require_http_methods(["GET", "POST"])
def provider_model_create_page(request, provider_id):
    if not is_platform_admin(request.user):
        return JsonResponse(
            {"ok": False, "error": "Administrator access required."},
            status=403,
        )
    provider = get_object_or_404(AIProvider, id=provider_id)
    error = ""
    suggested_code = "glm-5.1" if provider.code == "glm_5" else ""
    if request.method == "POST":
        model_code = str(request.POST.get("model_code") or "").strip()
        if not model_code:
            error = "Model code is required."
        else:
            try:
                model, _ = AIProviderModel.objects.update_or_create(
                    provider=provider,
                    model_code=model_code,
                    defaults={
                        "display_name": str(
                            request.POST.get("display_name") or model_code
                        ).strip(),
                        "model_family": str(
                            request.POST.get("model_family") or provider.name
                        ).strip(),
                        "maximum_output_tokens": int(
                            request.POST.get("maximum_output_tokens") or 4096
                        ),
                        "capabilities_json": [
                            "text_generation",
                            "structured_output",
                            "json_mode",
                        ],
                        "supports_structured_output": True,
                        "supports_streaming": True,
                        "active": True,
                        "is_default_for_provider": True,
                        "validation_status": "To Review",
                    },
                )
                AIProviderModel.objects.filter(
                    provider=provider,
                    is_default_for_provider=True,
                ).exclude(pk=model.pk).update(is_default_for_provider=False)
                return redirect(
                    "ai-provider-test-page",
                    provider_id=provider.id,
                )
            except (ValueError, TypeError) as exc:
                error = str(exc)
    return render(request, "reports/ai_provider_model_form.html", {
        "active_section": "api-management",
        "provider": provider,
        "suggested_code": suggested_code,
        "error": error,
    })


@login_required
@require_http_methods(["GET", "POST"])
def provider_status_page(request, provider_id):
    if not is_platform_admin(request.user):
        return JsonResponse(
            {"ok": False, "error": "Administrator access required."},
            status=403,
        )
    provider = get_object_or_404(AIProvider, id=provider_id)
    target_active = not provider.active
    if request.method == "POST":
        target_active = request.POST.get("active") == "1"
        provider.active = target_active
        if target_active:
            if not credential_configured(provider):
                return render(request, "reports/ai_provider_status.html", {
                    "active_section": "api-management",
                    "provider": provider,
                    "target_active": target_active,
                    "error": "A credential must be configured before activation.",
                })
            if not provider.models.filter(active=True).exists():
                return render(request, "reports/ai_provider_status.html", {
                    "active_section": "api-management",
                    "provider": provider,
                    "target_active": target_active,
                    "error": "At least one active provider model is required before activation.",
                })
            provider.status = "active"
        else:
            provider.status = "inactive"
        provider.updated_by = request.user
        provider.save(update_fields=["active", "status", "updated_by", "updated_at"])
        AIProviderAuditLog.objects.create(
            provider=provider,
            user=request.user,
            action="activated" if target_active else "deactivated",
        )
        return redirect("api-management-home")
    return render(request, "reports/ai_provider_status.html", {
        "active_section": "api-management",
        "provider": provider,
        "target_active": target_active,
        "error": "",
    })


@login_required
@require_GET
def api_management_dashboard(request):
    if denied := _denied(request):
        return denied
    providers = AIProvider.objects.prefetch_related("models", "credentials")
    logs = AIProviderUsageLog.objects.all()
    total = logs.count()
    completed = logs.filter(status="completed").count()
    payload = {
        "ok": True,
        "summary": {
            "configured_providers": sum(1 for item in providers if credential_configured(item)),
            "active_providers": providers.filter(active=True).count(),
            "default_provider": providers.filter(is_default=True).values_list("name", flat=True).first() or "None",
            "healthy_providers": providers.filter(status="active").count(),
            "degraded_providers": providers.filter(status__in=["degraded", "unavailable"]).count(),
            "failed_requests": logs.filter(status="failed").count(),
            "fallback_rate": round(logs.filter(fallback_used=True).count() * 100 / total, 2) if total else 0,
            "total_cost": float(logs.aggregate(value=Sum("estimated_cost"))["value"] or 0),
            "success_rate": round(completed * 100 / total, 2) if total else 0,
        },
        "providers": [_provider_payload(item) for item in providers],
        "models": [_model_payload(item) for item in AIProviderModel.objects.select_related("provider")],
        "use_cases": [
            _use_case_payload(item)
            for item in AIUseCaseConfiguration.objects.select_related("primary_provider", "primary_model")
        ],
    }
    return JsonResponse(payload)


@login_required
@require_http_methods(["GET", "POST"])
def providers_collection_api(request):
    if denied := _denied(request):
        return denied
    if request.method == "GET":
        return JsonResponse({"ok": True, "items": [_provider_payload(item) for item in AIProvider.objects.all()]})
    data = _payload(request)
    provider = AIProvider(created_by=request.user)
    try:
        _apply_provider(provider, data, request.user)
        AIProviderAuditLog.objects.create(provider=provider, user=request.user, action="created")
        return JsonResponse({"ok": True, "item": _provider_payload(provider, True)}, status=201)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def _apply_provider(provider, data, user):
    text_fields = (
        "code", "name", "provider_type", "description", "base_url", "api_version",
        "auth_type", "selection_mode", "currency",
    )
    for field in text_fields:
        if field in data:
            setattr(provider, field, str(data[field] or "").strip())
    for field in (
        "priority", "timeout_seconds", "retry_count", "retry_backoff_seconds",
        "maximum_concurrent_requests",
    ):
        if field in data:
            setattr(provider, field, max(0, int(data[field] or 0)))
    for field in ("requests_per_minute", "tokens_per_minute"):
        if field in data:
            setattr(provider, field, int(data[field]) if data[field] not in (None, "") else None)
    for field in ("daily_budget", "monthly_budget"):
        if field in data:
            setattr(provider, field, _decimal(data[field]))
    for field in ("active", "is_default", "allow_fallback", "block_when_budget_exceeded"):
        if field in data:
            setattr(provider, field, bool(data[field]))
    if isinstance(data.get("capabilities"), list):
        provider.capabilities_json = list(dict.fromkeys(data["capabilities"]))
    if isinstance(data.get("configuration"), dict):
        provider.configuration_json = data["configuration"]
    if not provider.code or not provider.name:
        raise ValueError("Provider code and name are required.")
    provider.updated_by = user
    if provider.is_default:
        AIProvider.objects.filter(is_default=True).exclude(pk=provider.pk).update(is_default=False)
    provider.save()


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def provider_item_api(request, provider_id):
    if denied := _denied(request):
        return denied
    provider = get_object_or_404(AIProvider, id=provider_id)
    if request.method == "GET":
        return JsonResponse({"ok": True, "item": _provider_payload(provider, True)})
    if request.method == "DELETE":
        provider.active = False
        provider.status = "inactive"
        provider.updated_by = request.user
        provider.save()
        AIProviderAuditLog.objects.create(provider=provider, user=request.user, action="deactivated")
        return JsonResponse({"ok": True})
    before = _provider_payload(provider)
    try:
        _apply_provider(provider, _payload(request), request.user)
        AIProviderAuditLog.objects.create(
            provider=provider, user=request.user, action="updated", changes_json={"before": before}
        )
        return JsonResponse({"ok": True, "item": _provider_payload(provider, True)})
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@login_required
@require_POST
def provider_credential_api(request, provider_id):
    if denied := _denied(request):
        return denied
    provider = get_object_or_404(AIProvider, id=provider_id)
    try:
        set_provider_secret(provider, _payload(request).get("credential", ""))
        provider.status = "active" if provider.active else "inactive"
        provider.save(update_fields=["status", "updated_at"])
        AIProviderAuditLog.objects.create(
            provider=provider, user=request.user, action="credential_replaced"
        )
        return JsonResponse({"ok": True, "credential_status": masked_credential(provider)})
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@login_required
@require_POST
def provider_test_api(request, provider_id):
    if denied := _denied(request):
        return denied
    provider = get_object_or_404(AIProvider, id=provider_id)
    try:
        result = check_provider_health(provider)
        AIProviderAuditLog.objects.create(provider=provider, user=request.user, action="connection_test")
        return JsonResponse({"ok": result.get("ok", False), "result": result}, status=200 if result.get("ok") else 502)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


@login_required
@require_POST
def provider_set_default_api(request, provider_id):
    if denied := _denied(request):
        return denied
    provider = get_object_or_404(AIProvider, id=provider_id)
    AIProvider.objects.filter(is_default=True).exclude(id=provider.id).update(is_default=False)
    provider.is_default = True
    provider.save(update_fields=["is_default", "updated_at"])
    AIProviderAuditLog.objects.create(provider=provider, user=request.user, action="set_default")
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["GET", "POST"])
def provider_models_api(request):
    if denied := _denied(request):
        return denied
    if request.method == "GET":
        queryset = AIProviderModel.objects.select_related("provider")
        if request.GET.get("provider"):
            queryset = queryset.filter(provider_id=request.GET["provider"])
        return JsonResponse({"ok": True, "items": [_model_payload(item) for item in queryset]})
    data = _payload(request)
    try:
        provider = get_object_or_404(AIProvider, id=data.get("provider_id"))
        model = AIProviderModel(provider=provider)
        _apply_model(model, data)
        return JsonResponse({"ok": True, "item": _model_payload(model)}, status=201)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def _apply_model(model, data):
    for field in ("model_code", "display_name", "description", "model_family", "currency", "pricing_notes", "validation_status"):
        if field in data:
            setattr(model, field, str(data[field] or "").strip())
    for field in ("context_window", "maximum_output_tokens"):
        if field in data:
            setattr(model, field, int(data[field]) if data[field] not in (None, "") else None)
    for field in ("input_cost_per_million", "output_cost_per_million", "cached_input_cost_per_million"):
        if field in data:
            setattr(model, field, _decimal(data[field]))
    for field in (
        "active", "is_default_for_provider", "supports_streaming",
        "supports_structured_output", "supports_tool_calling", "supports_vision",
        "supports_embeddings", "supports_audio_transcription", "supports_text_to_speech",
    ):
        if field in data:
            setattr(model, field, bool(data[field]))
    if isinstance(data.get("capabilities"), list):
        model.capabilities_json = list(dict.fromkeys(data["capabilities"]))
    if model.is_default_for_provider:
        AIProviderModel.objects.filter(provider=model.provider, is_default_for_provider=True).exclude(pk=model.pk).update(is_default_for_provider=False)
    if not model.model_code:
        raise ValueError("Model code is required.")
    model.display_name = model.display_name or model.model_code
    model.save()


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def provider_model_item_api(request, model_id):
    if denied := _denied(request):
        return denied
    model = get_object_or_404(AIProviderModel.objects.select_related("provider"), id=model_id)
    if request.method == "GET":
        return JsonResponse({"ok": True, "item": _model_payload(model)})
    if request.method == "DELETE":
        model.active = False
        model.save(update_fields=["active", "updated_at"])
        return JsonResponse({"ok": True})
    try:
        _apply_model(model, _payload(request))
        return JsonResponse({"ok": True, "item": _model_payload(model)})
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@login_required
@require_http_methods(["GET", "PATCH"])
def use_case_routing_api(request, use_case_id=None):
    if denied := _denied(request):
        return denied
    if request.method == "GET":
        items = AIUseCaseConfiguration.objects.select_related("primary_provider", "primary_model")
        return JsonResponse({"ok": True, "items": [_use_case_payload(item) for item in items]})
    item = get_object_or_404(AIUseCaseConfiguration, id=use_case_id)
    data = _payload(request)
    if "primary_provider_id" in data:
        item.primary_provider = AIProvider.objects.filter(id=data["primary_provider_id"]).first()
    if "primary_model_id" in data:
        item.primary_model = AIProviderModel.objects.filter(id=data["primary_model_id"]).first()
    for field in ("selection_mode", "validation_status"):
        if field in data:
            setattr(item, field, str(data[field]))
    for field in ("fallback_enabled", "structured_output_required", "streaming_enabled", "active"):
        if field in data:
            setattr(item, field, bool(data[field]))
    for field in ("maximum_output_tokens", "timeout_seconds", "retry_count"):
        if field in data:
            setattr(item, field, max(0, int(data[field] or 0)))
    if "temperature" in data:
        item.temperature = Decimal(str(data["temperature"] or 0))
    for field, target in (
        ("fallback_providers", "fallback_providers_json"),
        ("required_capabilities", "required_capabilities_json"),
    ):
        if isinstance(data.get(field), list):
            setattr(item, target, data[field])
    item.save()
    return JsonResponse({"ok": True, "item": _use_case_payload(item)})


@login_required
@require_POST
def provider_playground_api(request):
    if denied := _denied(request):
        return denied
    data = _payload(request)
    try:
        options = {
            "provider": data.get("provider", ""),
            "model": data.get("model", ""),
            "temperature": data.get("temperature", 0),
            "maximum_output_tokens": data.get("maximum_output_tokens", 256),
        }
        schema = data.get("output_schema") if data.get("structured_output") else None
        if schema:
            result = ai_gateway.generate_structured_output(
                use_case=data.get("use_case") or "machine_performance_response",
                messages=[{"role": "user", "content": str(data.get("prompt") or "")}],
                output_schema=schema,
                context={"user": request.user},
                options=options,
            )
        else:
            result = ai_gateway.generate_text(
                use_case=data.get("use_case") or "machine_performance_response",
                messages=[{"role": "user", "content": str(data.get("prompt") or "")}],
                context={"user": request.user},
                options=options,
            )
        return JsonResponse({"ok": True, "result": result.as_dict()})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc), "error_code": getattr(exc, "code", "")}, status=502)


@login_required
@require_POST
def provider_health_all_api(request):
    if denied := _denied(request):
        return denied
    return JsonResponse({"ok": True, "items": check_all_providers()})


@login_required
@require_GET
def provider_usage_api(request):
    if denied := _denied(request):
        return denied
    grouped = (
        AIProviderUsageLog.objects.values("provider_code")
        .annotate(
            requests=Count("id"),
            cost=Sum("estimated_cost"),
            latency=Avg("latency_ms"),
            failures=Count("id", filter=Q(status="failed")),
            fallbacks=Count("id", filter=Q(fallback_used=True)),
        )
        .order_by("-requests")
    )
    return JsonResponse({"ok": True, "items": list(grouped)})
