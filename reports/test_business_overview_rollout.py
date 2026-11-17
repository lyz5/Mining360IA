"""Role-based read access must work with the application's actual rollout defaults."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .access_control import enforce_request_access, is_platform_admin
from .ai_feature_rollout import feature_enabled
from .business_mapping_access_service import has_mapping_permission
from .business_review_access_service import filter_published_rows, has_business_review_permission
from .business_review_views import _command_center_allowed, business_command_center
from .platform_roles import ROLE_KEY


class BusinessOverviewRolloutTests(SimpleTestCase):
    def account(self, roles, *, scope=None, active=True):
        user = SimpleNamespace(is_authenticated=True, is_active=True, is_superuser=False,
                               is_staff=False, has_perm=lambda name: False)
        user.platformuser = SimpleNamespace(
            is_active=active, is_platform_admin=False, can_access_ai=False,
            can_access_reporting=False, can_access_data=False, can_access_sources=False,
            business_performance_scope={ROLE_KEY: roles, **(scope or {})}, django_user=user,
        )
        return user

    def request(self, user):
        request = RequestFactory().get('/business-review/command-center/')
        request.user = user
        return request

    def test_business_reader_opens_current_dashboard_without_super_admin(self):
        user = self.account(['business_overview'])
        request = self.request(user)
        self.assertFalse(is_platform_admin(user))
        self.assertIsNone(enforce_request_access(request))
        with patch('reports.business_review_views.render', return_value=HttpResponse('ok')) as render:
            response = business_command_center(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(render.call_args.args[1], 'reports/business_command_center_v2.html')
        context = render.call_args.args[2]
        for feature in ['customers', 'countries', 'key_accounts', 'last_visit', 'attention', 'presentation']:
            self.assertTrue(context['features'][feature], feature)
        self.assertFalse(context['can_export'])
        self.assertFalse(context['can_create_action'])

    def test_admin_requires_the_business_role_too(self):
        self.assertFalse(_command_center_allowed(self.account(['admin'])))
        self.assertTrue(_command_center_allowed(self.account(['admin', 'business_overview'])))

    def test_other_roles_do_not_gain_business_access(self):
        for roles in [[], ['reporting'], ['excellence_center'], ['chatbot'], ['resources']]:
            with self.subTest(roles=roles):
                user = self.account(roles)
                self.assertFalse(_command_center_allowed(user))
                self.assertEqual(business_command_center(self.request(user)).status_code, 403)

    def test_anonymous_and_inactive_profiles_are_denied(self):
        self.assertFalse(_command_center_allowed(AnonymousUser()))
        self.assertFalse(_command_center_allowed(self.account(['business_overview'], active=False)))

    def test_old_django_permissions_do_not_bypass_an_explicit_role_revocation(self):
        user = self.account(['reporting'])
        user.has_perm = lambda name: True
        self.assertFalse(_command_center_allowed(user))

    def test_account_and_site_restrictions_remain_intersected(self):
        user = self.account(['business_overview'], scope={'accounts': ['A1'], 'minesites': ['Site A']})
        rows = [
            {'id': 'allowed', 'account_code': 'a1', 'minesite_name': 'Site A'},
            {'id': 'wrong-account', 'account_code': 'a2', 'minesite_name': 'Site A'},
            {'id': 'wrong-site', 'account_code': 'a1', 'minesite_name': 'Site B'},
        ]
        self.assertEqual([row['id'] for row in filter_published_rows(rows, user)], ['allowed'])
        self.assertEqual(filter_published_rows(rows, self.account(['business_overview'])), [])

    def test_read_role_does_not_gain_sensitive_permissions(self):
        user = self.account(['business_overview'])
        for permission in ['export_business_command_center', 'create_business_review_action',
                           'preview_business_review_draft']:
            self.assertFalse(has_business_review_permission(user, permission), permission)
        self.assertFalse(has_mapping_permission(user, 'publish_business_mapping'))
        for flag in ['ENABLE_BUSINESS_COMMAND_CENTER_EXPORT', 'ENABLE_BUSINESS_COMMAND_CENTER_WATCHLIST',
                     'ENABLE_BUSINESS_REVIEW_ACTIONS', 'ENABLE_BUSINESS_MAPPING_PUBLICATION']:
            self.assertFalse(feature_enabled(flag, user), flag)

    def test_explicit_disabled_or_admin_only_rollout_remains_enforced(self):
        user = self.account(['business_overview'])
        for mode in ['Disabled', 'Admin Only']:
            with self.subTest(mode=mode), override_settings(ENABLE_BUSINESS_REVIEW=mode):
                self.assertFalse(_command_center_allowed(user))
