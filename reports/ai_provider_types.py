from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


ERROR_CODES = {
    "AUTHENTICATION_ERROR",
    "RATE_LIMIT",
    "TIMEOUT",
    "PROVIDER_UNAVAILABLE",
    "MODEL_UNAVAILABLE",
    "INVALID_REQUEST",
    "INVALID_RESPONSE",
    "INVALID_STRUCTURED_OUTPUT",
    "CONTENT_REFUSAL",
    "BUDGET_EXCEEDED",
    "CAPABILITY_NOT_SUPPORTED",
    "CONNECTION_ERROR",
    "UNKNOWN_PROVIDER_ERROR",
}

RETRYABLE_ERRORS = {
    "RATE_LIMIT",
    "TIMEOUT",
    "PROVIDER_UNAVAILABLE",
    "MODEL_UNAVAILABLE",
    "BUDGET_EXCEEDED",
    "CONNECTION_ERROR",
}


class AIProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502, retryable: bool | None = None):
        self.code = code if code in ERROR_CODES else "UNKNOWN_PROVIDER_ERROR"
        self.message = str(message or self.code)
        self.status_code = status_code
        self.retryable = self.code in RETRYABLE_ERRORS if retryable is None else retryable
        super().__init__(self.message)


@dataclass
class AIRequest:
    use_case: str
    messages: list[dict]
    model: str
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    system_instructions: str = ""
    temperature: float = 0
    maximum_output_tokens: int = 2048
    response_format: str = "text"
    output_schema: dict | None = None
    tools: list[dict] = field(default_factory=list)
    tool_choice: Any = None
    stream: bool = False
    metadata: dict = field(default_factory=dict)
    user_reference: str = ""
    conversation_reference: str = ""
    agent_reference: str = ""
    audio_file: Any = None
    audio_filename: str = ""
    audio_mime_type: str = ""
    language_hint: str = ""
    inputs: list[str] = field(default_factory=list)


@dataclass
class AIProviderResponse:
    request_id: str
    provider: str
    model: str
    status: str = "completed"
    content: str = ""
    structured_output: dict | list | None = None
    embeddings: list[list[float]] = field(default_factory=list)
    transcription: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
        }
    )
    latency_ms: int = 0
    estimated_cost: float | None = None
    fallback_used: bool = False
    attempts: list[dict] = field(default_factory=list)
    raw_response: Any = None

    def as_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "content": self.content,
            "structured_output": self.structured_output,
            "embeddings": self.embeddings,
            "transcription": self.transcription,
            "tool_calls": self.tool_calls,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "latency_ms": self.latency_ms,
            "estimated_cost": self.estimated_cost,
            "fallback_used": self.fallback_used,
            "attempts": self.attempts,
        }
