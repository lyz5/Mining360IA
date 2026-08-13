import logging

from django.contrib.auth.backends import BaseBackend
from django.utils import timezone

from .active_directory_service import ActiveDirectoryError, authenticate_directory_user
from .models import ActiveDirectoryAuthenticationAuditLog


logger = logging.getLogger(__name__)


class ActiveDirectoryBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        clean_username = str(username or "").strip()
        if not clean_username or not password:
            return None
        try:
            user = authenticate_directory_user(clean_username, password)
            if user is None:
                return None
            platform_user = user.platformuser
            platform_user.last_directory_authenticated_at = timezone.now()
            platform_user.save(update_fields=["last_directory_authenticated_at", "updated_at"])
            self._audit(request, clean_username, "success", "authenticated", user=user)
            return user
        except ActiveDirectoryError as exc:
            logger.info("Active Directory authentication rejected for %s: %s", clean_username, exc.code)
            self._audit(request, clean_username, "blocked" if exc.code in {"account_disabled", "group_not_allowed", "not_synchronized"} else "failed", exc.code)
            return None
        except Exception:
            logger.exception("Unexpected Active Directory authentication failure for %s", clean_username)
            self._audit(request, clean_username, "failed", "directory_unavailable")
            return None

    def get_user(self, user_id):
        from django.contrib.auth import get_user_model
        try:
            return get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return None

    @staticmethod
    def _audit(request, username, status, reason, user=None):
        forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR") or "") if request else ""
        source_ip = (forwarded.split(",", 1)[0].strip() if forwarded else str(request.META.get("REMOTE_ADDR") or "")) if request else ""
        ActiveDirectoryAuthenticationAuditLog.objects.create(
            user=user, username=username[:255], status=status, reason_code=reason[:80],
            source_ip=source_ip or None,
            user_agent=str(request.META.get("HTTP_USER_AGENT") or "")[:500] if request else "",
        )
