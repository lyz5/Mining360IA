"""Direct compatibility integration for existing non-Codex features.

This has no catalogue, database routing, managed credentials or provider fallback.
M360 Chatbot continues to use its separate Codex runtime.
"""
from types import SimpleNamespace

from .ai_output_validation_service import output_validation_service
from .legacy_ai_types import AIRequest, LegacyAIError
from .legacy_openai_adapter import LegacyOpenAIAdapter


class LegacyAIService:
    def generate_text(self, *, use_case, messages, context=None, options=None):
        return self._execute('generate_text', use_case, messages, options)

    def generate_structured_output(self, *, use_case, messages, output_schema, context=None, options=None):
        return self._execute('generate_structured_output', use_case, messages, options, output_schema=output_schema)

    def create_embeddings(self, *, use_case, inputs, context=None, options=None):
        return self._execute('create_embeddings', use_case, [], options, inputs=list(inputs))

    def transcribe_audio(self, *, use_case, audio_file, filename, mime_type, language_hint=None, context=None, options=None):
        return self._execute('transcribe_audio', use_case, [], options, audio_file=audio_file,
                             audio_filename=filename, audio_mime_type=mime_type, language_hint=language_hint or '')

    def _execute(self, operation, use_case, messages, options, **kwargs):
        from .openai_service import get_openai_api_key, get_openai_model

        options = options or {}
        if options.get('provider') not in (None, '', 'openai'):
            raise LegacyAIError('CAPABILITY_NOT_SUPPORTED', 'This legacy integration only supports OpenAI.', retryable=False)
        key = get_openai_api_key()
        if not key:
            raise LegacyAIError('AUTHENTICATION_ERROR', 'The legacy AI integration is not configured.', retryable=False)
        if operation == 'create_embeddings':
            from .resource_knowledge_ai_service import embedding_model
            default_model = embedding_model()
        elif operation == 'transcribe_audio':
            default_model = 'gpt-4o-mini-transcribe'
        else:
            default_model = get_openai_model()
        request = AIRequest(
            use_case=use_case, messages=messages, model=options.get('model') or default_model,
            maximum_output_tokens=int(options.get('maximum_output_tokens', 2048)),
            temperature=options.get('temperature', 0), metadata=dict(options.get('metadata') or {}), **kwargs,
        )
        adapter = LegacyOpenAIAdapter(SimpleNamespace(code='openai', name='OpenAI', base_url='',
                                       timeout_seconds=float(options.get('timeout_seconds', 60))), key)
        try:
            response = getattr(adapter, operation)(request)
            if request.output_schema:
                output_validation_service.validate(response.structured_output, request.output_schema)
            return response
        except LegacyAIError:
            raise
        except Exception as exc:
            # Never surface raw SDK responses, credentials or request bodies.
            raise LegacyAIError('PROVIDER_UNAVAILABLE', 'The legacy AI request failed. Please retry later.') from None


legacy_ai = LegacyAIService()
