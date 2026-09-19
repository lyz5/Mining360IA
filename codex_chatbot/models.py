from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class CodexChatbotPilot(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="codex_chatbot_pilot",
        on_delete=models.CASCADE,
    )
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "codex_chatbot_pilot"


class CodexConversation(models.Model):
    legacy_context = models.JSONField(default=dict, blank=True, editable=False)
    legacy_conversation_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="codex_conversations",
        on_delete=models.PROTECT,
    )
    title = models.CharField(max_length=180, default="New conversation")
    native_thread_id = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=30, default="ACTIVE", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "codex_conversation"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "status", "updated_at"], name="codex_conv_owner_status")]


class CodexMessage(models.Model):
    legacy_message_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    legacy_payload = models.JSONField(default=dict, blank=True, editable=False)
    ROLES = (("USER", "User"), ("ASSISTANT", "Assistant"), ("SYSTEM", "System"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(CodexConversation, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=ROLES)
    content = models.TextField()
    answer_status = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "codex_message"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="codex_msg_conv_time")]


class CodexRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(CodexConversation, related_name="runs", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="codex_runs", on_delete=models.PROTECT)
    result_message = models.OneToOneField(
        CodexMessage,
        related_name="source_run",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=40, default="QUEUED", db_index=True)
    question = models.TextField()
    tool_code = models.CharField(max_length=120, blank=True)
    native_thread_id = models.CharField(max_length=255, blank=True)
    native_turn_id = models.CharField(max_length=255, blank=True)
    error_code = models.CharField(max_length=120, blank=True)
    error_message = models.TextField(blank=True)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    progress_label = models.CharField(max_length=180, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "codex_run"
        ordering = ["-created_at"]


class CodexEvidence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(CodexRun, related_name="evidence", on_delete=models.CASCADE)
    source_type = models.CharField(max_length=120)
    source_record_id = models.CharField(max_length=255, blank=True)
    label = models.CharField(max_length=255)
    value_json = models.JSONField(default=dict)
    retrieved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "codex_evidence"
        ordering = ["retrieved_at", "id"]


class CodexArtifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(CodexRun, related_name="artifacts", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="codex_artifacts", on_delete=models.PROTECT)
    artifact_type = models.CharField(max_length=60, default="CSV")
    title = models.CharField(max_length=255)
    relative_path = models.CharField(max_length=500, unique=True)
    content_type = models.CharField(max_length=120, default="text/csv")
    row_count = models.PositiveIntegerField(default=0)
    byte_size = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "codex_artifact"
        ordering = ["-created_at"]
