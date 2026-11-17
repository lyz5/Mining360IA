"""Allowlisted mailbox proof, with expiring, session-bound, single-use codes."""
import logging
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_variables

from .email_signin_models import EmailLoginChallenge, EmailLoginRateLock
from .models import PlatformUser

logger = logging.getLogger(__name__)
SESSION_KEY = 'email_signin_challenge'
NONCE_KEY = 'email_signin_nonce'
BACKEND = 'reports.email_signin_service.EmailCodeBackend'
MAX_ATTEMPTS = 5
LIFETIME_MINUTES = 10
DELIVERY_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='m360-signin-mail')


class SignInThrottled(Exception):
    pass


class EmailAccountNotRegistered(Exception):
    pass


class EmailAccountUnavailable(Exception):
    pass


def digest(kind, value):
    return salted_hmac('mining360.email-signin.' + kind, str(value), algorithm='sha256').hexdigest()


def clean_email(value):
    value = str(value or '').strip().casefold()
    if len(value) > 254:
        raise ValidationError('Enter a valid email address.')
    validate_email(value)
    return value


def profile_for_email(address):
    profiles = list(PlatformUser.objects.select_related('django_user').filter(
        Q(email__iexact=address) | Q(user_principal_name__iexact=address),
        is_active=True, django_user__isnull=False, django_user__is_active=True,
    )[:2])
    return profiles[0] if len(profiles) == 1 else None


def _throttle(address, request):
    now = timezone.now()
    # REMOTE_ADDR is the actual peer. No client-supplied X-Forwarded-For is used.
    keys = [(digest('email-rate', address), 6, 60),
            (digest('peer-rate', request.META.get('REMOTE_ADDR', 'unknown')), 120, 0)]
    with transaction.atomic():
        rows = []
        for key, maximum, interval in sorted(keys):
            EmailLoginRateLock.objects.get_or_create(key=key)
            row = EmailLoginRateLock.objects.select_for_update().get(pk=key)
            if now - row.window_start >= timedelta(minutes=15):
                row.requests = 0
                row.window_start = now
            if row.requests >= maximum or (interval and row.last_request_at and now - row.last_request_at < timedelta(seconds=interval)):
                raise SignInThrottled()
            rows.append(row)
        for row in rows:
            row.requests += 1
            row.last_request_at = now
            row.save(update_fields=('requests', 'window_start', 'last_request_at'))


@sensitive_variables('value', 'address', 'code', 'nonce')
def request_code(request, value):
    """Check the existing account before issuing a sign-in challenge."""
    address = clean_email(value)
    _throttle(address, request)
    profile = profile_for_email(address)
    if not profile:
        request.session.pop(SESSION_KEY, None)
        request.session.pop(NONCE_KEY, None)
        if not PlatformUser.objects.filter(
            Q(email__iexact=address) | Q(user_principal_name__iexact=address),
        ).exists():
            raise EmailAccountNotRegistered()
        raise EmailAccountUnavailable()
    nonce = secrets.token_urlsafe(32)
    code = f'{secrets.randbelow(100000000):08}'
    now = timezone.now()
    challenge = EmailLoginChallenge.objects.create(
        user=profile.django_user,
        email_digest=digest('email', address), session_digest=digest('session', nonce),
        code_hash=make_password(code), expires_at=now + timedelta(minutes=LIFETIME_MINUTES),
    )
    # Old requests from another browser are not invalidated by a resend here.
    request.session[SESSION_KEY] = str(challenge.pk)
    request.session[NONCE_KEY] = nonce
    # Delivery remains asynchronous; only the short-lived in-memory job contains
    # the plaintext code. Unknown addresses never reach the delivery queue.
    transaction.on_commit(lambda: queue_delivery(challenge.pk, address, code, profile.django_user_id))
    return str(challenge.pk)


def queue_delivery(challenge_id, address, code, user_id):
    if getattr(settings, 'MINING360_EMAIL_CODE_DELIVERY_ASYNC', True):
        try:
            DELIVERY_POOL.submit(_deliver, challenge_id, address, code, user_id)
        except RuntimeError:
            EmailLoginChallenge.objects.filter(pk=challenge_id).update(delivery_status='failed')
            logger.warning('Mining360 email sign-in delivery unavailable.')
    else:
        _deliver(challenge_id, address, code, user_id)


@sensitive_variables('address', 'code')
def _deliver(challenge_id, address, code, user_id):
    asynchronous = getattr(settings, 'MINING360_EMAIL_CODE_DELIVERY_ASYNC', True)
    if asynchronous:
        close_old_connections()
    status = 'failed'
    try:
        from .email_signin_delivery import send_code
        profile = profile_for_email(address)
        challenge = EmailLoginChallenge.objects.filter(pk=challenge_id, delivery_status='pending', expires_at__gt=timezone.now()).first()
        if not challenge or not profile or profile.django_user_id != user_id:
            return
        send_code(address, code, LIFETIME_MINUTES)
        status = 'issued'
    except Exception:
        logger.warning('Mining360 email sign-in delivery unavailable.')
    finally:
        try:
            values = {'delivery_status': status}
            if status == 'issued':
                values['expires_at'] = timezone.now() + timedelta(minutes=LIFETIME_MINUTES)
            EmailLoginChallenge.objects.filter(pk=challenge_id).update(**values)
        finally:
            if asynchronous:
                close_old_connections()


class EmailCodeBackend(BaseBackend):
    @sensitive_variables('email_code', 'raw', 'nonce')
    def authenticate(self, request, email_code=None, **kwargs):
        if not getattr(settings, 'MINING360_EMAIL_CODE_LOGIN_ENABLED', False) or request is None or email_code is None:
            return None
        raw = re.sub(r'[\s-]', '', str(email_code)) if len(str(email_code)) <= 32 else ''
        if not re.fullmatch(r'[0-9]{8}', raw):
            raw = ''  # Malformed attempts also consume the bounded budget.
        challenge_id = request.session.get(SESSION_KEY)
        nonce = request.session.get(NONCE_KEY)
        if not challenge_id or not nonce:
            return None
        try:
            with transaction.atomic():
                challenge = EmailLoginChallenge.objects.select_for_update().filter(pk=challenge_id).first()
                now = timezone.now()
                if (not challenge or challenge.consumed_at or challenge.expires_at <= now
                        or challenge.attempts >= MAX_ATTEMPTS or challenge.delivery_status == 'pending'
                        or not constant_time_compare(challenge.session_digest, digest('session', nonce))):
                    return None
                challenge.attempts += 1
                valid_hash = check_password(raw, challenge.code_hash)  # Also for decoys/malformed input.
                valid = bool(raw) and valid_hash and challenge.delivery_status == 'issued'
                user = None
                if valid and challenge.user_id:
                    profile = PlatformUser.objects.select_related('django_user').filter(
                        django_user_id=challenge.user_id, is_active=True, django_user__is_active=True,
                    ).first()
                    if profile:
                        # Revoking or changing the allowlisted mailbox invalidates the code.
                        addresses = {str(value).strip().casefold() for value in (profile.email, profile.user_principal_name) if value}
                        addresses = {value for value in addresses if constant_time_compare(digest('email', value), challenge.email_digest)}
                        if any(getattr(profile_for_email(value), 'pk', None) == profile.pk for value in addresses):
                            user = profile.django_user
                if user or challenge.attempts >= MAX_ATTEMPTS:
                    challenge.consumed_at = now
                    challenge.code_hash = ''
                challenge.save(update_fields=('attempts', 'consumed_at', 'code_hash'))
                return user
        except (ValueError, ValidationError):
            return None

    def get_user(self, user_id):
        if not getattr(settings, 'MINING360_EMAIL_CODE_LOGIN_ENABLED', False):
            return None
        profile = PlatformUser.objects.select_related('django_user').filter(
            django_user_id=user_id, is_active=True, django_user__is_active=True,
        ).first()
        return profile.django_user if profile else None
