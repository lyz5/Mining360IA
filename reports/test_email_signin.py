import copy
from io import StringIO
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .access_control import is_platform_admin
from .email_signin_models import EmailLoginChallenge, EmailLoginRateLock
from .email_signin_service import (
    BACKEND, NONCE_KEY, SESSION_KEY, EmailCodeBackend, SignInThrottled,
    EmailAccountNotRegistered, EmailAccountUnavailable, clean_email, digest, request_code,
)
from .models import PlatformUser, SystemIntegrationConfig
from .system_configuration_service import decrypt_secrets, save_integration, integration_payload


TEST_SETTINGS = dict(
    MINING360_EMAIL_CODE_LOGIN_ENABLED=True, MINING360_EMAIL_CODE_DELIVERY_ASYNC=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


def delivery_config(**updates):
    values = {'transport': 'SMTP', 'sender_email': 'sender@example.invalid',
              'smtp_host': 'smtp.example.invalid', 'smtp_port': 587, 'smtp_tls': True,
              'smtp_ssl': False, 'smtp_username': 'test-mailer', 'smtp_password': 'test-only-placeholder'}
    values.update(updates)
    return save_integration(SystemIntegrationConfig(), {
        'code': 'email-signin', 'name': 'Local sign-in test delivery',
        'integration_type': 'Notification', 'is_active': True, 'settings': values,
    })


def identity(name='viewer', admin=False):
    user = get_user_model().objects.create_user(name, is_staff=admin, is_superuser=admin)
    user.set_unusable_password()
    user.save()
    profile = PlatformUser.objects.create(
        django_user=user, azure_ad_id='ad:' + name, user_principal_name=name + '@old.example.invalid',
        email=name + '@example.invalid', display_name='Local Test ' + name,
        auth_source='active_directory', directory_object_id='directory-' + name,
        directory_roles_managed=False, is_active=True, is_platform_admin=admin,
        can_access_reporting=True, business_performance_role='Administrator' if admin else 'Viewer',
        business_performance_scope={'platform_roles_v2': ['super_admin'] if admin else ['business_overview', 'resources'],
                                    'minesites': ['Local Test Site'], 'account_codes': ['LOCAL-ONLY']},
    )
    return user, profile


@override_settings(**TEST_SETTINGS)
class EmailCodeServiceTests(TestCase):
    def setUp(self):
        self.user, self.profile = identity()
        self.config = delivery_config()
        self.factory = RequestFactory()
        mail.get_connection()
        mail.outbox.clear()

    def issue(self, address=None, peer='172.17.0.20'):
        request = self.factory.post('/email-sign-in/', REMOTE_ADDR=peer)
        request.session = {}
        with self.captureOnCommitCallbacks(execute=True):
            request_code(request, address or self.profile.email)
        code = re.search(r'\b[0-9]{8}\b', mail.outbox[-1].body).group() if mail.outbox else None
        return request, code

    def test_normalizes_email_and_rejects_header_injection(self):
        self.assertEqual(clean_email(' Viewer@EXAMPLE.invalid '), self.profile.email)
        for value in ('not-an-email', 'a@example.invalid\r\nBcc: a@other.invalid', 'a' * 255 + '@x.invalid'):
            with self.assertRaises(ValidationError):
                clean_email(value)

    def test_only_existing_profile_receives_code(self):
        request, code = self.issue()
        row = EmailLoginChallenge.objects.get(pk=request.session[SESSION_KEY])
        self.assertEqual(mail.outbox[0].to, [self.profile.email])
        self.assertEqual(mail.outbox[0].from_email, 'sender@example.invalid')
        self.assertEqual(row.user_id, self.user.pk)
        self.assertNotIn(code, row.code_hash)
        self.assertNotIn(code, str(request.session))
        self.assertEqual(row.delivery_status, 'issued')
        self.assertAlmostEqual((row.expires_at-row.created_at).total_seconds(), 600, delta=2)

    def test_unknown_inactive_and_disabled_users_do_not_receive_email(self):
        for i, kind in enumerate(('unknown', 'profile', 'user')):
            self.profile.is_active = kind != 'profile';self.profile.save()
            self.user.is_active = kind != 'user';self.user.save()
            with self.assertRaises(EmailAccountNotRegistered if kind == 'unknown' else EmailAccountUnavailable):
                self.issue('absent@example.invalid' if kind == 'unknown' else self.profile.email, peer='172.17.0.'+str(40+i))
            EmailLoginRateLock.objects.all().delete()
        self.assertEqual(mail.outbox, [])
        self.assertEqual(EmailLoginChallenge.objects.count(),0)
        self.assertEqual(get_user_model().objects.count(),1)

    def test_ambiguous_alias_cannot_select_another_user(self):
        _, other = identity('other');other.email=self.profile.email;other.save()
        with self.assertRaises(EmailAccountUnavailable):self.issue()
        self.assertEqual(mail.outbox, [])
        self.assertEqual(EmailLoginChallenge.objects.count(),0)

    def test_unlinked_existing_profile_is_unavailable_instead_of_missing(self):
        self.profile.django_user=None;self.profile.save(update_fields=['django_user'])
        with self.assertRaises(EmailAccountUnavailable):self.issue()
        self.assertEqual(mail.outbox,[])

    def test_unknown_account_checks_are_still_throttled(self):
        with self.assertRaises(EmailAccountNotRegistered):self.issue('absent@example.invalid')
        with self.assertRaises(SignInThrottled):self.issue('absent@example.invalid')
        self.assertEqual(EmailLoginChallenge.objects.count(),0)

    def test_code_authenticates_without_touching_roles_or_directory_identity(self):
        before=PlatformUser.objects.values().get(pk=self.profile.pk)
        request, code = self.issue()
        result = authenticate(request, email_code=code)
        self.assertEqual(result.pk, self.user.pk)
        self.assertEqual(result.backend, BACKEND)
        self.assertFalse(is_platform_admin(result))
        self.assertEqual(before, PlatformUser.objects.values().get(pk=self.profile.pk))
        self.user.refresh_from_db();self.assertFalse(self.user.has_usable_password())

    def test_upn_alias_is_also_allowlisted(self):
        request, code = self.issue(self.profile.user_principal_name.upper())
        self.assertEqual(mail.outbox[0].to, [self.profile.user_principal_name])
        self.assertEqual(authenticate(request, email_code=code).pk,self.user.pk)

    def test_single_use_code_is_erased_after_success(self):
        request, code = self.issue()
        self.assertIsNotNone(authenticate(request, email_code=code))
        self.assertIsNone(authenticate(request, email_code=code))
        row=EmailLoginChallenge.objects.get(pk=request.session[SESSION_KEY])
        self.assertIsNotNone(row.consumed_at);self.assertEqual(row.code_hash,'')

    def test_leading_zeros_and_pasted_spacing_are_preserved(self):
        with patch('reports.email_signin_service.secrets.randbelow',return_value=123456):
            request, code=self.issue()
        self.assertEqual(code,'00123456')
        self.assertEqual(authenticate(request,email_code='0012 3456').pk,self.user.pk)

    def test_expired_code_is_rejected(self):
        request,code=self.issue()
        EmailLoginChallenge.objects.filter(pk=request.session[SESSION_KEY]).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertIsNone(authenticate(request,email_code=code))

    def test_five_wrong_or_malformed_attempts_lock_the_challenge(self):
        request,code=self.issue()
        for attempt in ('bad','1','00000000000000000000000','x'*200,'not-a-code'):
            self.assertIsNone(authenticate(request,email_code=attempt))
        self.assertIsNone(authenticate(request,email_code=code))
        row=EmailLoginChallenge.objects.get(pk=request.session[SESSION_KEY])
        self.assertEqual(row.attempts,5);self.assertIsNotNone(row.consumed_at)

    def test_valid_code_from_another_browser_cannot_be_used(self):
        request,code=self.issue();other=copy.copy(request);other.session=dict(request.session)
        other.session[NONCE_KEY]='different-browser'
        self.assertIsNone(authenticate(other,email_code=code))
        self.assertIsNotNone(authenticate(request,email_code=code))

    def test_removed_or_changed_profile_invalidates_pending_code(self):
        request,code=self.issue()
        self.profile.email='changed@example.invalid';self.profile.user_principal_name='changed@old.example.invalid';self.profile.save()
        self.assertIsNone(authenticate(request,email_code=code))

    def test_profile_revocation_invalidates_session_backend(self):
        self.assertIsNotNone(EmailCodeBackend().get_user(self.user.pk))
        self.profile.is_active=False;self.profile.save()
        self.assertIsNone(EmailCodeBackend().get_user(self.user.pk))

    def test_delivery_failure_never_logs_code_or_upstream_secret(self):
        with patch('reports.email_signin_delivery.send_code',side_effect=RuntimeError('secret=must-not-appear')):
            with self.assertLogs('reports.email_signin_service',level='WARNING') as logged:
                request,_=self.issue()
        self.assertNotIn('must-not-appear',str(logged.output))
        self.assertEqual(EmailLoginChallenge.objects.get(pk=request.session[SESSION_KEY]).delivery_status,'failed')
        self.assertIsNone(authenticate(request,email_code='12345678'))

    def test_cooldown_and_quarter_hour_limit_survive_session_changes(self):
        request,_=self.issue()
        with self.assertRaises(SignInThrottled):request_code(request,self.profile.email)
        for _ in range(5):
            EmailLoginRateLock.objects.update(last_request_at=timezone.now()-timedelta(seconds=61))
            self.issue()
        EmailLoginRateLock.objects.update(last_request_at=timezone.now()-timedelta(seconds=61))
        with self.assertRaises(SignInThrottled):self.issue()

    def test_invalid_challenge_and_disabled_feature_fail_closed(self):
        request,code=self.issue();original=dict(request.session)
        request.session[SESSION_KEY]='not-a-uuid'
        self.assertIsNone(authenticate(request,email_code=code))
        request.session=original
        with override_settings(MINING360_EMAIL_CODE_LOGIN_ENABLED=False):
            self.assertIsNone(authenticate(request,email_code=code))
            self.assertIsNone(EmailCodeBackend().get_user(self.user.pk))

    def test_forwarded_peer_header_cannot_create_a_new_rate_bucket(self):
        request,_=self.issue();key=digest('peer-rate','172.17.0.20')
        self.assertTrue(EmailLoginRateLock.objects.filter(pk=key).exists())
        self.assertFalse(EmailLoginRateLock.objects.filter(pk=digest('peer-rate','8.8.8.8')).exists())


@override_settings(**TEST_SETTINGS)
class EmailCodeViewTests(TestCase):
    def setUp(self):
        self.user,self.profile=identity();delivery_config();mail.get_connection();mail.outbox.clear()

    def send(self,client=None,address=None):
        client=client or self.client
        with self.captureOnCommitCallbacks(execute=True):
            response=client.post(reverse('email-sign-in'),{'action':'request','email':address or self.profile.email,'next':'/resources/'})
        return response

    def code(self):return re.search(r'\b[0-9]{8}\b',mail.outbox[-1].body).group()

    def test_existing_login_route_switches_only_when_enabled(self):
        self.assertRedirects(self.client.get('/login/'),'/email-sign-in/?next=',fetch_redirect_response=False)
        with override_settings(MINING360_EMAIL_CODE_LOGIN_ENABLED=False):
            self.assertContains(self.client.get('/login/'),'name="password"')
            self.assertEqual(self.client.get('/email-sign-in/').status_code,404)

    def test_password_fallback_and_anonymous_protection_remain(self):
        self.assertContains(self.client.get('/login/?method=password'),'name="password"')
        for path in ('/business-review/command-center/','/system-config/','/users/'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,302)
            self.assertTrue(response['Location'].startswith('/login/'))

    def test_unknown_address_shows_explicit_account_message_without_sending(self):
        self.send();known=self.client.get(reverse('email-sign-in'))
        other=Client();unknown=self.send(other,'unknown@example.invalid')
        self.assertContains(known,'A sign-in code has been requested for your account')
        self.assertContains(unknown,'No Mining360 account is registered for this email address.')
        self.assertContains(unknown,'value="unknown@example.invalid"')
        self.assertContains(unknown,'name="email"')
        self.assertNotContains(unknown,'name="code"')
        self.assertNotIn(SESSION_KEY,other.session)
        self.assertEqual(len(mail.outbox),1)
        self.assertEqual(EmailLoginChallenge.objects.count(),1)
        for response in (known,unknown):
            self.assertNotContains(response,self.profile.email)
            self.assertNotContains(response,self.profile.display_name)
            self.assertIn('private',response['Cache-Control'])
            self.assertIn('no-store',response['Cache-Control'])

    def test_disabled_account_does_not_claim_the_email_is_unregistered(self):
        self.profile.is_active=False;self.profile.save(update_fields=['is_active'])
        response=self.send()
        self.assertContains(response,'This account is not enabled for email sign-in.')
        self.assertNotContains(response,'No Mining360 account is registered')
        self.assertNotContains(response,'name="code"')
        self.assertEqual(mail.outbox,[])

    def test_unknown_request_clears_any_previous_pending_browser_challenge(self):
        self.send()
        self.assertIn(SESSION_KEY,self.client.session)
        response=self.send(address='unknown@example.invalid')
        self.assertContains(response,'No Mining360 account is registered for this email address.')
        self.assertNotIn(SESSION_KEY,self.client.session)
        self.assertNotIn(NONCE_KEY,self.client.session)
        self.assertEqual(EmailLoginChallenge.objects.count(),1)
        self.assertEqual(len(mail.outbox),1)

    def test_verification_creates_normal_session_without_code_or_nonce(self):
        self.send();code=self.code()
        response=self.client.post('/email-sign-in/',{'action':'verify','code':code,'next':'/resources/'})
        self.assertEqual(response.status_code,302);self.assertEqual(response['Location'],'/resources/')
        session=self.client.session
        self.assertEqual(session['_auth_user_id'],str(self.user.pk))
        self.assertEqual(session['_auth_user_backend'],BACKEND)
        self.assertNotIn(SESSION_KEY,session);self.assertNotIn(NONCE_KEY,session)
        self.assertNotIn(code,str(dict(session)))
        self.assertTrue(session.get_expire_at_browser_close())

    def test_remember_me_is_optional(self):
        self.send()
        self.client.post('/email-sign-in/',{'action':'verify','code':self.code(),'remember':'on'})
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_next_url_cannot_redirect_outside_the_application(self):
        self.send()
        for value in ('https://evil.invalid','//evil.invalid','http://testserver/resources/'):
            response=self.client.get('/email-sign-in/',{'next':value},secure=True)
            self.assertEqual(response.context['next'],'/')

    def test_csrf_is_required_for_both_email_and_code(self):
        client=Client(enforce_csrf_checks=True)
        for action in ('request','verify'):
            response=client.post('/email-sign-in/',{'action':action,'email':self.profile.email,'code':'12345678'})
            self.assertEqual(response.status_code,403)
        self.assertEqual(EmailLoginChallenge.objects.count(),0)

    def test_same_origin_form_post_works_and_null_or_foreign_origins_stay_rejected(self):
        client=Client(enforce_csrf_checks=True)
        response=client.get('/email-sign-in/')
        self.assertEqual(response['Referrer-Policy'],'same-origin')
        token=client.cookies['csrftoken'].value
        with self.captureOnCommitCallbacks(execute=True):
            response=client.post('/email-sign-in/',{'email':self.profile.email},HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='http://testserver')
        self.assertEqual(response.status_code,302)
        for origin in ('null','https://untrusted.example.invalid'):
            response=client.post('/email-sign-in/',{'action':'verify','code':self.code()},HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN=origin)
            self.assertEqual(response.status_code,403)

    def test_same_code_cannot_be_submitted_by_another_session(self):
        self.send();other=Client()
        other.post('/email-sign-in/',{'action':'verify','code':self.code()})
        self.assertNotIn('_auth_user_id',other.session)

    def test_config_rights_are_preserved_for_viewer_and_admin(self):
        self.send();self.client.post('/email-sign-in/',{'action':'verify','code':self.code()})
        self.assertEqual(self.client.get('/system-config/api/integration-schemas/',HTTP_ACCEPT='application/json').status_code,403)
        admin,profile=identity('admin',admin=True);client=Client()
        self.send(client,profile.email)
        client.post('/email-sign-in/',{'action':'verify','code':self.code()})
        self.assertEqual(client.get('/system-config/api/integration-schemas/').status_code,200)
        admin.refresh_from_db();self.assertTrue(admin.is_superuser)

    def test_no_configured_delivery_shows_an_explicit_unavailable_state(self):
        SystemIntegrationConfig.objects.filter(code='email-signin').delete()
        self.assertContains(self.client.get('/email-sign-in/'),'temporarily unavailable')
        response=self.client.post('/email-sign-in/',{'email':self.profile.email})
        self.assertContains(response,'temporarily unavailable')
        self.assertEqual(EmailLoginChallenge.objects.count(),0)

    def test_restart_clears_the_pending_browser_challenge(self):
        self.send();self.client.post('/email-sign-in/',{'action':'restart'})
        self.assertNotIn(SESSION_KEY,self.client.session)
        self.assertContains(self.client.get('/email-sign-in/'),'name="email"')


@override_settings(**TEST_SETTINGS)
class EmailDeliveryTests(TestCase):
    def test_flow_url_is_encrypted_and_masked_in_config(self):
        value='https://test.environment.api.powerplatform.com/workflows/local-test/invoke?sig=fixture-only'
        item=delivery_config(transport='Power Automate',flow_url=value)
        self.assertNotIn(value,str(item.settings_json));self.assertNotIn(value,item.encrypted_secrets)
        self.assertEqual(decrypt_secrets(item)['flow_url'],value)
        self.assertNotIn(value,str(integration_payload(item)))

    def test_flow_contract_requires_success_after_sending_and_never_follows_redirects(self):
        from .email_signin_delivery import send_code
        delivery_config(transport='Power Automate',flow_url='https://test.logic.azure.com/workflows/test/invoke?sig=fixture')
        with patch('reports.email_signin_delivery.HTTP.post') as post:
            post.return_value.status_code=204;send_code('viewer@example.invalid','00123456',10)
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            self.assertEqual(set(post.call_args.kwargs['json']),{'recipient','subject','body'})
            self.assertEqual(post.call_args.kwargs['json']['recipient'],'viewer@example.invalid')
            for status in (202,302,400,500):
                post.return_value.status_code=status
                with self.assertRaises(RuntimeError):send_code('viewer@example.invalid','00123456',10)

    def test_noncorporate_flow_and_unencrypted_smtp_are_rejected(self):
        for url in ('http://test.logic.azure.com/invoke','https://evil.invalid/','https://user:pass@test.logic.azure.com/invoke','https://test.logic.azure.com:8443/invoke'):
            with self.assertRaises(ValueError):delivery_config(transport='Power Automate',flow_url=url)
        with self.assertRaises(ValueError):delivery_config(smtp_tls=False,smtp_ssl=False)
        with self.assertRaises(ValueError):delivery_config(smtp_tls=True,smtp_ssl=True)


@override_settings(**TEST_SETTINGS)
class EmailCodeConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_verification_succeeds_only_once(self):
        user,profile=identity();delivery_config()
        request=RequestFactory().post('/email-sign-in/',REMOTE_ADDR='172.17.0.30');request.session={}
        mail.get_connection();mail.outbox.clear();request_code(request,profile.email)
        code=re.search(r'\b[0-9]{8}\b',mail.outbox[0].body).group()
        session=dict(request.session)
        def verify(_):
            try:
                own=RequestFactory().post('/email-sign-in/');own.session=dict(session)
                return EmailCodeBackend().authenticate(own,email_code=code) is not None
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(verify,range(2)))
        self.assertEqual(sorted(results),[False,True])


@override_settings(**TEST_SETTINGS)
class EmailSigninRetentionTests(TestCase):
    def test_pruning_removes_only_stale_auth_records(self):
        user, profile = identity()
        now = timezone.now()
        values = dict(user=user, email_digest='a'*64, session_digest='b'*64, code_hash='unused')
        old = EmailLoginChallenge.objects.create(**values, expires_at=now-timedelta(days=4))
        current = EmailLoginChallenge.objects.create(**values, expires_at=now+timedelta(minutes=10))
        expired_today = EmailLoginChallenge.objects.create(**values, expires_at=now-timedelta(minutes=1))
        EmailLoginRateLock.objects.create(key='a'*64, window_start=now-timedelta(days=4))
        EmailLoginRateLock.objects.create(key='b'*64, window_start=now)
        call_command('prune_email_signin', stdout=StringIO())
        self.assertFalse(EmailLoginChallenge.objects.filter(pk=old.pk).exists())
        self.assertEqual(set(EmailLoginChallenge.objects.values_list('pk',flat=True)),{current.pk,expired_today.pk})
        self.assertEqual(EmailLoginRateLock.objects.count(),1)
        self.assertTrue(PlatformUser.objects.filter(pk=profile.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
