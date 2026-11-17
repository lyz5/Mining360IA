import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailLoginChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    email_digest = models.CharField(max_length=64, db_index=True)
    session_digest = models.CharField(max_length=64)
    code_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True)
    delivery_status = models.CharField(max_length=16, default='pending')

    class Meta:
        app_label = 'reports'
        db_table = 'email_login_challenge'


class EmailLoginRateLock(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window_start = models.DateTimeField(default=timezone.now)
    last_request_at = models.DateTimeField(null=True)
    requests = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = 'reports'
        db_table = 'email_login_rate_lock'
