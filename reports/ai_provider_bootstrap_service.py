from __future__ import annotations

import os

from django.db import transaction

from .ai_provider_credential_service import credential_configured
from .models import (
    AIProvider,
    AIProviderCredential,
    AIProviderModel,
    AIUseCaseConfiguration,
    SystemIntegrationConfig,
    SystemParameter,
)
from .system_configuration_service import integration_value


PROVIDER_SEEDS = [
    {
        "code": "openai",
        "name": "OpenAI",
        "provider_type": "openai",
        "priority": 100,
        "is_default": True,
        "base_url": "https://api.openai.com/v1",
        "capabilities": [
            "text_generation", "structured_output", "tool_calling", "embeddings",
            "audio_transcription", "text_to_speech", "vision", "streaming",
            "long_context", "json_mode", "function_calling", "document_analysis",
        ],
    },
    {
        "code": "anthropic_claude",
        "name": "Claude AI",
        "provider_type": "anthropic_claude",
        "priority": 90,
        "is_default": False,
        "base_url": "https://api.anthropic.com",
        "api_version": "2023-06-01",
        "capabilities": [
            "text_generation", "structured_output", "tool_calling", "vision",
            "streaming", "long_context", "json_mode", "function_calling",
            "document_analysis",
        ],
    },
    {
        "code": "google_gemini",
        "name": "Google Gemini",
        "provider_type": "google_gemini",
        "priority": 80,
        "is_default": False,
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "capabilities": [
            "text_generation", "structured_output", "tool_calling", "embeddings",
            "vision", "document_analysis", "streaming", "long_context",
            "json_mode", "function_calling",
        ],
    },
    {
        "code": "glm_5",
        "name": "GLM-5",
        "provider_type": "glm_5",
        "priority": 70,
        "is_default": False,
        "base_url": "https://api.z.ai/api/paas/v4",
        "capabilities": [
            "text_generation", "structured_output", "tool_calling", "streaming",
            "long_context", "json_mode", "function_calling",
        ],
    },
]

USE_CASE_SEEDS = [
    ("agent_router", "Agent Router", ["structured_output"], True),
    ("machine_performance_response", "Machine Performance Response", ["text_generation"], False),
    ("mining_knowledge_response", "Mining Knowledge Response", ["text_generation"], False),
    ("combined_agent_response", "Combined Agent Response", ["text_generation"], False),
    ("intent_classification", "Intent Classification", ["structured_output"], True),
    ("entity_extraction", "Entity Extraction", ["structured_output"], True),
    ("synonym_resolution", "Synonym Resolution", ["structured_output"], True),
    ("clarification_generation", "Clarification Generation", ["text_generation"], False),
    ("root_cause_comment_analysis", "Root Cause Comment Analysis", ["structured_output"], True),
    ("smcs_comment_classification", "SMCS Comment Classification", ["structured_output"], True),
    ("knowledge_document_summary", "Knowledge Document Summary", ["text_generation"], False),
    ("knowledge_enrichment", "Knowledge Enrichment", ["structured_output"], True),
    ("question_generation", "Question Generation", ["structured_output"], True),
    ("embedding_generation", "Embedding Generation", ["embeddings"], False),
    ("voice_transcription", "Voice Transcription", ["audio_transcription"], False),
    ("text_to_speech", "Text to Speech", ["text_to_speech"], False),
    ("semantic_question_parsing", "Semantic Question Parsing", ["structured_output"], True),
    ("semantic_answer_interpretation", "Semantic Answer Interpretation", ["text_generation"], False),
]

FEATURE_FLAGS = [
    ("enable-multi-provider-ai", "Multi-provider AI", "Admin Only"),
    ("enable-provider-fallback", "Provider fallback", "Admin Only"),
    ("enable-provider-health-check", "Provider health check", "Admin Only"),
    ("enable-provider-budget-control", "Provider budget control", "Admin Only"),
    ("enable-provider-playground", "Provider playground", "Admin Only"),
]


def _openai_model_code():
    return (
        os.getenv("OPENAI_MODEL")
        or integration_value("OpenAI", "default_model", "")
        or "gpt-4.1-mini"
    ).strip()


@transaction.atomic
def bootstrap_ai_providers() -> dict:
    providers = {}
    created_providers = 0
    for seed in PROVIDER_SEEDS:
        provider, created = AIProvider.objects.get_or_create(
            code=seed["code"],
            defaults={
                "name": seed["name"],
                "provider_type": seed["provider_type"],
                "description": f"{seed['name']} AI provider managed by Mining 360.",
                "base_url": seed["base_url"],
                "api_version": seed.get("api_version", ""),
                "priority": seed["priority"],
                "is_default": seed["is_default"],
                "active": False,
                "status": "not_configured",
                "capabilities_json": seed["capabilities"],
            },
        )
        created_providers += int(created)
        providers[provider.code] = provider

    openai = providers["openai"]
    integration = SystemIntegrationConfig.objects.filter(code="openai-default").first()
    reference = "system-integration:openai-default:api_key" if integration else "env:OPENAI_API_KEY"
    credential, _ = AIProviderCredential.objects.get_or_create(
        provider=openai,
        credential_type="api_key",
        defaults={"secret_reference": reference, "active": True},
    )
    if not credential.encrypted_value and credential.secret_reference != reference:
        credential.secret_reference = reference
        credential.save(update_fields=["secret_reference", "updated_at"])
    if credential_configured(openai):
        openai.active = True
        openai.status = "active"
        openai.save(update_fields=["active", "status", "updated_at"])

    model_code = _openai_model_code()
    openai_model, created_model = AIProviderModel.objects.get_or_create(
        provider=openai,
        model_code=model_code,
        defaults={
            "display_name": model_code,
            "model_family": "OpenAI",
            "capabilities_json": openai.capabilities_json,
            "supports_streaming": True,
            "supports_structured_output": True,
            "supports_tool_calling": True,
            "supports_vision": True,
            "supports_embeddings": False,
            "is_default_for_provider": True,
            "validation_status": "To Review",
        },
    )
    embedding_model, created_embedding = AIProviderModel.objects.get_or_create(
        provider=openai,
        model_code=os.getenv("RESOURCE_KB_EMBEDDING_MODEL", "text-embedding-3-small"),
        defaults={
            "display_name": os.getenv("RESOURCE_KB_EMBEDDING_MODEL", "text-embedding-3-small"),
            "model_family": "Embedding",
            "capabilities_json": ["embeddings"],
            "supports_embeddings": True,
            "validation_status": "To Review",
        },
    )
    transcription_model, created_transcription = AIProviderModel.objects.get_or_create(
        provider=openai,
        model_code="gpt-4o-mini-transcribe",
        defaults={
            "display_name": "gpt-4o-mini-transcribe",
            "model_family": "Audio",
            "capabilities_json": ["audio_transcription"],
            "supports_audio_transcription": True,
            "validation_status": "To Review",
        },
    )

    created_use_cases = 0
    fallback_codes = ["anthropic_claude", "google_gemini", "glm_5"]
    for code, name, capabilities, structured in USE_CASE_SEEDS:
        model = openai_model
        if "embeddings" in capabilities:
            model = embedding_model
        elif "audio_transcription" in capabilities:
            model = transcription_model
        item, created = AIUseCaseConfiguration.objects.get_or_create(
            use_case_code=code,
            defaults={
                "display_name": name,
                "description": f"Provider routing for {name}.",
                "primary_provider": openai,
                "primary_model": model,
                "selection_mode": "priority",
                "fallback_enabled": True,
                "fallback_providers_json": fallback_codes,
                "required_capabilities_json": capabilities,
                "structured_output_required": structured,
                "temperature": 0 if structured else 0.3,
                "maximum_output_tokens": (
                    4096 if code == "root_cause_comment_analysis" else 2048
                ),
                "validation_status": "To Review",
            },
        )
        created_use_cases += int(created)

    for key, label, default in FEATURE_FLAGS:
        SystemParameter.objects.get_or_create(
            key=key,
            defaults={
                "category": "AI Provider Management",
                "label": label,
                "description": f"Feature mode for {label}.",
                "value_type": "Text",
                "value_json": default,
                "default_value_json": default,
                "options_json": ["Disabled", "Admin Only", "Pilot Users", "Production"],
                "is_runtime_editable": True,
                "is_active": True,
            },
        )

    return {
        "providers": AIProvider.objects.count(),
        "providers_created": created_providers,
        "models_created": int(created_model) + int(created_embedding) + int(created_transcription),
        "use_cases": AIUseCaseConfiguration.objects.count(),
        "use_cases_created": created_use_cases,
        "default_provider": openai.code,
        "openai_configured": credential_configured(openai),
    }
