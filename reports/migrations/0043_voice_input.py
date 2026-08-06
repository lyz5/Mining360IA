import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import uuid


DEFAULT_FORMATS = [
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-m4a",
]


def seed_voice_configuration(apps, schema_editor):
    VoiceInputConfiguration = apps.get_model("reports", "VoiceInputConfiguration")
    VoiceInputConfiguration.objects.get_or_create(
        name="Default",
        defaults={"allowed_audio_formats": DEFAULT_FORMATS},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0042_portable_system_configuration"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VoiceInputConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="Default", max_length=120, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("provider", models.CharField(default="OpenAI", max_length=80)),
                ("model", models.CharField(default="gpt-4o-mini-transcribe", max_length=160)),
                ("default_language", models.CharField(choices=[("auto", "Auto Detect"), ("fr", "French"), ("en", "English")], default="auto", max_length=12)),
                ("auto_detect_language", models.BooleanField(default=True)),
                ("maximum_duration_seconds", models.PositiveIntegerField(default=120)),
                ("maximum_file_size_mb", models.PositiveIntegerField(default=20)),
                ("allowed_audio_formats", models.JSONField(blank=True, default=list)),
                ("auto_send", models.BooleanField(default=False)),
                ("store_audio", models.BooleanField(default=False)),
                ("retention_duration_days", models.PositiveIntegerField(default=0)),
                ("daily_user_limit_minutes", models.PositiveIntegerField(default=30)),
                ("request_rate_limit_per_minute", models.PositiveIntegerField(default=10)),
                ("maximum_concurrent_transcriptions", models.PositiveSmallIntegerField(default=1)),
                ("timeout_seconds", models.PositiveIntegerField(default=120)),
                ("retry_count", models.PositiveSmallIntegerField(default=1)),
                ("privacy_message_fr", models.TextField(default="Votre audio sera utilisé uniquement pour transcrire votre question. Il ne sera pas conservé par Mining 360 AI après traitement.")),
                ("privacy_message_en", models.TextField(default="Your audio will only be used to transcribe your question. Mining 360 AI will not retain it after processing.")),
                ("feature_mode", models.CharField(choices=[("Disabled", "Disabled"), ("Admin Only", "Admin Only"), ("Pilot Users", "Pilot Users"), ("Production", "Production")], default="Production", max_length=20)),
                ("stop_recording_after_silence", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("pilot_users", models.ManyToManyField(blank=True, related_name="voice_input_pilot_configs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "VoiceInputConfiguration", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="VoiceTranscriptionLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("conversation_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("provider", models.CharField(blank=True, max_length=80)),
                ("model", models.CharField(blank=True, db_index=True, max_length=160)),
                ("detected_language", models.CharField(blank=True, max_length=16)),
                ("duration_seconds", models.DecimalField(decimal_places=3, default=0, max_digits=10)),
                ("file_size", models.PositiveBigIntegerField(default=0)),
                ("mime_type", models.CharField(blank=True, max_length=120)),
                ("processing_time_ms", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(choices=[("Processing", "Processing"), ("Completed", "Completed"), ("Failed", "Failed"), ("Cancelled", "Cancelled")], db_index=True, default="Processing", max_length=20)),
                ("error_code", models.CharField(blank=True, max_length=160)),
                ("input_tokens", models.PositiveBigIntegerField(default=0)),
                ("output_tokens", models.PositiveBigIntegerField(default=0)),
                ("total_tokens", models.PositiveBigIntegerField(default=0)),
                ("estimated_cost", models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("openai_usage_log", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="voice_transcription", to="reports.openaiusagelog")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "VoiceTranscriptionLog",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["user", "created_at"], name="voice_usage_user_time"),
                    models.Index(fields=["status", "created_at"], name="voice_usage_status_time"),
                ],
            },
        ),
        migrations.RunPython(seed_voice_configuration, migrations.RunPython.noop),
    ]
