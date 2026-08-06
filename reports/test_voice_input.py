from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .audio_security_service import VoiceInputError, validate_audio_upload
from .audio_transcription_service import TranscriptionResult
from .models import (
    OpenAIUsageLog,
    PlatformUser,
    VoiceInputConfiguration,
    VoiceTranscriptionLog,
)
from .voice_input_service import VoiceInputService


def webm_upload(name="question.webm"):
    return SimpleUploadedFile(
        name,
        b"\x1a\x45\xdf\xa3" + (b"\x00" * 1024),
        content_type="audio/webm",
    )


class FakeTranscriptionProvider:
    def __init__(self, text="What is the physical availability at Essakane?"):
        self.text = text
        self.calls = []

    def transcribe(self, **kwargs):
        self.calls.append(kwargs)
        response = SimpleNamespace(
            model=kwargs["model"],
            id="audio-test-request",
            text=self.text,
            usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=15,
                total_tokens=135,
                input_token_details=SimpleNamespace(audio_tokens=120),
            ),
        )
        return TranscriptionResult(
            text=self.text,
            model=kwargs["model"],
            request_id="audio-test-request",
            response=response,
        )


class VoiceInputTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("voice-user", password="password")
        PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="voice-user-id",
            user_principal_name="voice@example.com",
            display_name="Voice User",
            email="voice@example.com",
            can_access_ai=True,
            is_active=True,
        )
        self.admin = User.objects.create_user(
            "voice-admin",
            password="password",
            is_staff=True,
            is_superuser=True,
        )
        self.config = VoiceInputConfiguration.objects.filter(name="Default").first()
        if not self.config:
            self.config = VoiceInputConfiguration.objects.create(name="Default")
        self.config.enabled = True
        self.config.feature_mode = "Production"
        self.config.allowed_audio_formats = ["audio/webm", "audio/mp4", "audio/ogg"]
        self.config.retry_count = 0
        self.config.save()

    def test_valid_audio_is_transcribed_and_logged(self):
        provider = FakeTranscriptionProvider()
        result = VoiceInputService(provider=provider).transcribe(
            user=self.user,
            uploaded_file=webm_upload(),
            voice_request_id=uuid4(),
            conversation_id="conversation-test",
            language_hint="en",
            duration_seconds=8.4,
            mime_type="audio/webm",
        )
        self.assertTrue(result["success"])
        self.assertIn("physical availability", result["transcription"])
        log = VoiceTranscriptionLog.objects.get()
        self.assertEqual(log.status, "Completed")
        self.assertEqual(log.conversation_id, "conversation-test")
        self.assertEqual(log.total_tokens, 135)
        self.assertEqual(OpenAIUsageLog.objects.get().feature, "Voice Transcription")
        self.assertNotIn("transcription", {field.name for field in VoiceTranscriptionLog._meta.fields})

    def test_duplicate_request_is_not_processed_twice(self):
        request_id = uuid4()
        service = VoiceInputService(provider=FakeTranscriptionProvider())
        service.transcribe(
            user=self.user,
            uploaded_file=webm_upload(),
            voice_request_id=request_id,
            duration_seconds=3,
            mime_type="audio/webm",
        )
        cached = service.transcribe(
            user=self.user,
            uploaded_file=webm_upload(),
            voice_request_id=request_id,
            duration_seconds=3,
            mime_type="audio/webm",
        )
        self.assertTrue(cached["success"])
        self.assertEqual(VoiceTranscriptionLog.objects.count(), 1)

    def test_invalid_audio_signature_is_rejected(self):
        upload = SimpleUploadedFile("fake.webm", b"not-webm" * 30, content_type="audio/webm")
        with self.assertRaises(VoiceInputError) as context:
            validate_audio_upload(upload, self.config, "audio/webm", 3)
        self.assertEqual(context.exception.code, "INVALID_AUDIO_CONTENT")

    def test_disabled_feature_blocks_transcription(self):
        self.config.enabled = False
        self.config.save()
        with self.assertRaises(VoiceInputError) as context:
            VoiceInputService(provider=FakeTranscriptionProvider()).transcribe(
                user=self.user,
                uploaded_file=webm_upload(),
                voice_request_id=uuid4(),
                duration_seconds=3,
                mime_type="audio/webm",
            )
        self.assertEqual(context.exception.code, "VOICE_INPUT_DISABLED")

    def test_public_configuration_respects_feature_flag(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/ai/audio/config/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["config"]["enabled"])
        self.config.feature_mode = "Admin Only"
        self.config.save()
        response = self.client.get("/api/ai/audio/config/")
        self.assertFalse(response.json()["config"]["enabled"])

    def test_voice_configuration_is_admin_only(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/ia-config/api/voice-input/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(
            "/ia-config/api/voice-input/",
            data='{"enabled": true, "model": "gpt-4o-mini-transcribe", "feature_mode": "Production"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["config"]["model"], "gpt-4o-mini-transcribe")


class VoiceInputFrontendContractTests(TestCase):
    def test_chat_contains_accessible_voice_controls(self):
        reports_dir = Path(settings.BASE_DIR) / "reports"
        template = (reports_dir / "templates" / "reports" / "ai.html").read_text(encoding="utf-8")
        javascript = (reports_dir / "static" / "reports" / "voice_input.js").read_text(encoding="utf-8")
        styles = (reports_dir / "static" / "reports" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="ai-voice-button"', template)
        self.assertIn('aria-label="Start voice input"', template)
        self.assertIn("navigator.mediaDevices.getUserMedia", javascript)
        self.assertIn("new MediaRecorder", javascript)
        self.assertIn('form.append("conversation_id"', javascript)
        self.assertIn(".ai-voice-button.is-recording", styles)
