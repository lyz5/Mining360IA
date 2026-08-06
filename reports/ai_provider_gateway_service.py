from __future__ import annotations

import time
from dataclasses import replace

from django.utils import timezone

from .ai_output_validation_service import output_validation_service
from .ai_provider_budget_service import estimate_provider_cost
from .ai_provider_circuit_service import record_provider_failure, record_provider_success
from .ai_provider_credential_service import provider_secret
from .ai_provider_routing_service import provider_routing_service
from .ai_provider_types import AIProviderError, AIRequest
from .ai_providers import adapter_registry
from .models import AIAgent, AIProviderUsageLog


class AIProviderGatewayService:
    def generate_text(self, *, use_case, messages, context=None, options=None):
        return self._execute(
            operation="generate_text",
            capability="text_generation",
            use_case=use_case,
            messages=messages,
            context=context,
            options=options,
        )

    def generate_structured_output(
        self, *, use_case, messages, output_schema, context=None, options=None
    ):
        return self._execute(
            operation="generate_structured_output",
            capability="structured_output",
            use_case=use_case,
            messages=messages,
            output_schema=output_schema,
            context=context,
            options=options,
        )

    def create_embeddings(self, *, use_case, inputs, context=None, options=None):
        return self._execute(
            operation="create_embeddings",
            capability="embeddings",
            use_case=use_case,
            messages=[],
            inputs=inputs,
            context=context,
            options=options,
        )

    def transcribe_audio(
        self,
        *,
        use_case,
        audio_file,
        filename,
        mime_type,
        language_hint=None,
        context=None,
        options=None,
    ):
        return self._execute(
            operation="transcribe_audio",
            capability="audio_transcription",
            use_case=use_case,
            messages=[],
            audio_file=audio_file,
            audio_filename=filename,
            audio_mime_type=mime_type,
            language_hint=language_hint or "",
            context=context,
            options=options,
        )

    def _execute(
        self,
        *,
        operation,
        capability,
        use_case,
        messages,
        context=None,
        options=None,
        output_schema=None,
        inputs=None,
        audio_file=None,
        audio_filename="",
        audio_mime_type="",
        language_hint="",
    ):
        context = context or {}
        options = options or {}
        selections = provider_routing_service.select(
            use_case_code=use_case,
            capability=capability,
            context=context,
            options=options,
        )
        attempts = []
        final_error = None
        for selection_index, selection in enumerate(selections):
            provider = selection.provider
            use_case_config = selection.use_case
            retry_count = int(options.get("retry_count", use_case_config.retry_count if use_case_config else provider.retry_count))
            request = AIRequest(
                use_case=use_case,
                messages=messages,
                model=selection.model.model_code,
                system_instructions=str(options.get("system_instructions") or ""),
                temperature=float(options.get("temperature", use_case_config.temperature if use_case_config else 0)),
                maximum_output_tokens=int(
                    options.get(
                        "maximum_output_tokens",
                        use_case_config.maximum_output_tokens if use_case_config else 2048,
                    )
                ),
                response_format="json" if output_schema else "text",
                output_schema=output_schema,
                tools=list(options.get("tools") or []),
                stream=bool(options.get("stream", False)),
                metadata=dict(options.get("metadata") or {}),
                user_reference=str(getattr(context.get("user"), "pk", "") or ""),
                conversation_reference=str(context.get("conversation_id") or ""),
                agent_reference=str(context.get("agent_code") or ""),
                inputs=list(inputs or []),
                audio_file=audio_file,
                audio_filename=audio_filename,
                audio_mime_type=audio_mime_type,
                language_hint=language_hint,
            )
            adapter = adapter_registry.create(provider, provider_secret(provider))
            for retry in range(max(0, retry_count) + 1):
                started = time.perf_counter()
                try:
                    response = getattr(adapter, operation)(request)
                    if output_schema:
                        output_validation_service.validate(response.structured_output, output_schema)
                    response.fallback_used = selection_index > 0
                    response.attempts = attempts + [
                        {"provider": provider.code, "model": selection.model.model_code, "status": "completed"}
                    ]
                    response.estimated_cost = self._cost(selection.model, response.usage)
                    self._log(
                        selection=selection,
                        response=response,
                        context=context,
                        use_case=use_case,
                        retry=retry,
                        fallback_reason=attempts[-1]["error_code"] if attempts else "",
                    )
                    provider.status = "active"
                    provider.last_success_at = timezone.now()
                    provider.last_error_code = ""
                    provider.last_error_message = ""
                    provider.save(
                        update_fields=[
                            "status", "last_success_at", "last_error_code",
                            "last_error_message", "updated_at",
                        ]
                    )
                    record_provider_success(provider)
                    return response
                except Exception as exc:
                    error = adapter.normalize_error(exc)
                    final_error = error
                    attempts.append(
                        {
                            "provider": provider.code,
                            "model": selection.model.model_code,
                            "status": "failed",
                            "error_code": error.code,
                            "message": error.message,
                        }
                    )
                    self._log_failure(
                        selection=selection,
                        request=request,
                        context=context,
                        use_case=use_case,
                        retry=retry,
                        error=error,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                    provider.last_failure_at = timezone.now()
                    provider.last_error_code = error.code
                    provider.last_error_message = error.message[:2000]
                    if error.code == "AUTHENTICATION_ERROR":
                        provider.status = "invalid_credentials"
                    elif error.code in {"PROVIDER_UNAVAILABLE", "CONNECTION_ERROR"}:
                        provider.status = "degraded"
                    provider.save()
                    record_provider_failure(provider, error.code)
                    if not error.retryable:
                        raise error
                    if retry < retry_count:
                        time.sleep(min(8, provider.retry_backoff_seconds * (2 ** retry)))
            if not provider.allow_fallback:
                break
        raise final_error or AIProviderError("PROVIDER_UNAVAILABLE", "All AI providers failed.")

    @staticmethod
    def _cost(model, usage):
        value = estimate_provider_cost(model, usage)
        return float(value) if value is not None else None

    @staticmethod
    def _agent(context):
        value = context.get("agent")
        if isinstance(value, AIAgent):
            return value
        code = context.get("agent_code")
        return AIAgent.objects.filter(code=code).first() if code else None

    def _log(self, *, selection, response, context, use_case, retry, fallback_reason):
        AIProviderUsageLog.objects.create(
            request_id=response.request_id,
            user=context.get("user") if getattr(context.get("user"), "is_authenticated", False) else None,
            conversation_id=str(context.get("conversation_id") or ""),
            agent=self._agent(context),
            use_case=use_case,
            provider=selection.provider,
            provider_code=selection.provider.code,
            model=response.model,
            primary_provider_code=selection.primary_provider_code,
            fallback_used=response.fallback_used,
            fallback_reason=fallback_reason,
            status="completed",
            input_tokens=response.usage.get("input_tokens", 0),
            output_tokens=response.usage.get("output_tokens", 0),
            cached_tokens=response.usage.get("cached_tokens", 0),
            total_tokens=response.usage.get("total_tokens", 0),
            audio_seconds=context.get("audio_seconds", 0) or 0,
            estimated_cost=response.estimated_cost,
            currency=selection.provider.currency,
            latency_ms=response.latency_ms,
            retry_count=retry,
            metadata_json={"attempts": response.attempts},
        )

    def _log_failure(self, *, selection, request, context, use_case, retry, error, latency_ms):
        AIProviderUsageLog.objects.create(
            request_id=request.request_id,
            user=context.get("user") if getattr(context.get("user"), "is_authenticated", False) else None,
            conversation_id=str(context.get("conversation_id") or ""),
            agent=self._agent(context),
            use_case=use_case,
            provider=selection.provider,
            provider_code=selection.provider.code,
            model=selection.model.model_code,
            primary_provider_code=selection.primary_provider_code,
            fallback_used=selection.provider.code != selection.primary_provider_code,
            status="failed",
            latency_ms=latency_ms,
            retry_count=retry,
            error_code=error.code,
            error_message=error.message[:2000],
        )


ai_gateway = AIProviderGatewayService()
