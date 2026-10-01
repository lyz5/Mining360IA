from unittest.mock import patch
from django.contrib.auth.models import User, AnonymousUser
from django.test import TestCase, RequestFactory, override_settings
from django.template.loader import render_to_string
from .models import PlatformUser
from .platform_roles import ROLE_KEY, ROLE_LABELS, profile_roles, can_manage_users
from .access_control import enforce_request_access, has_module_access, is_platform_admin
from .user_access_service import update_user_access, set_user_status, UserAccessValidationError, access_options
from .business_review_access_service import has_business_review_permission, filter_published_rows
from .active_directory_service import DirectoryIdentity, synchronize_identity


@override_settings(ENABLE_BUSINESS_REVIEW="Production", ENABLE_AVAILABILITY_COMMAND_CENTER_HOME="Production")
class SimplifiedRoleTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.super_user, self.super_profile = self.account('super', ['super_admin'], superuser=True)
        self.admin, self.admin_profile = self.account('admin', ['admin'])
        self.user, self.profile = self.account('reader', ['reporting'])
        self.options = patch('reports.user_access_service._business_options', return_value=(['Mali'], ['Customer'], []))
        self.options.start()
        self.addCleanup(self.options.stop)

    def account(self, name, roles=None, superuser=False, **values):
        user = User.objects.create_user(name, is_superuser=superuser, is_staff=superuser)
        profile = PlatformUser.objects.create(django_user=user, azure_ad_id=name,
            user_principal_name=f'{name}@example.test', display_name=name,
            directory_roles_managed=False, is_platform_admin=superuser,
            business_performance_scope={ROLE_KEY:roles} if roles is not None else {}, **values)
        return user, profile

    def request(self, user, path, method='get'):
        request = getattr(self.factory, method)(path, HTTP_ACCEPT='application/json')
        request.user = user
        return request

    def test_exactly_six_roles_and_only_super_assigns_administrators(self):
        self.assertEqual(list(ROLE_LABELS), ['excellence_center','business_overview','reporting','resources','admin','super_admin'])
        options = access_options(self.admin)
        self.assertEqual([r['code'] for r in options['platform_roles'] if not r['assignable']], ['admin','super_admin'])

    def test_legacy_admin_keeps_full_access_as_super_admin(self):
        user, profile = self.account('legacy', None, superuser=True)
        self.assertEqual(profile_roles(profile), ['super_admin'])
        self.assertTrue(is_platform_admin(user))

    def test_legacy_reporting_keeps_excellence_and_library(self):
        user, profile = self.account('oldreport', None, can_access_reporting=True)
        self.assertEqual(set(profile_roles(profile)), {'excellence_center','reporting','resources'})

    def test_admin_can_manage_users_but_not_sensitive_configuration(self):
        self.assertTrue(can_manage_users(self.admin))
        self.assertFalse(is_platform_admin(self.admin))
        self.assertIsNone(enforce_request_access(self.request(self.admin, '/api/access-control/users/')))
        self.assertEqual(enforce_request_access(self.request(self.admin, '/system-config/')).status_code,403)
        self.assertEqual(enforce_request_access(self.request(self.admin, '/api/deployment/status/')).status_code,403)

    def test_unauthorized_cannot_manage_users(self):
        for actor in [self.user, AnonymousUser()]:
            with self.assertRaises(UserAccessValidationError):
                update_user_access(self.profile, {'platform_roles':['super_admin']}, actor)

    def test_admin_cannot_assign_or_modify_administrators(self):
        for roles in [['admin'], ['super_admin']]:
            with self.assertRaises(UserAccessValidationError):
                update_user_access(self.profile, {'platform_roles':roles}, self.admin)
        with self.assertRaises(UserAccessValidationError):
            update_user_access(self.admin_profile, {'platform_roles':['super_admin']}, self.admin)
        with self.assertRaises(UserAccessValidationError):
            set_user_status(self.super_profile, False, self.admin)

    def test_admin_cannot_assign_business_administrator(self):
        with self.assertRaises(UserAccessValidationError):
            update_user_access(self.profile, {'business_performance_access':'Administrator'}, self.admin)

    def test_admin_cannot_enable_directory_privilege_inheritance(self):
        with self.assertRaises(UserAccessValidationError):
            update_user_access(self.profile, {'directory_roles_managed':True}, self.admin)

    def test_admin_api_rejects_escalation_and_allows_module_assignment(self):
        self.client.force_login(self.admin)
        url=f'/api/access-control/users/{self.profile.pk}/access/'
        result=self.client.patch(url, {'platform_roles':['super_admin']}, content_type='application/json')
        self.assertEqual(result.status_code,400)
        result=self.client.patch(url, {'platform_roles':['resources']}, content_type='application/json')
        self.assertEqual(result.status_code,200)
        self.profile.refresh_from_db()
        self.assertEqual(profile_roles(self.profile),['resources'])

    def test_ad_managed_roles_cannot_be_changed_manually(self):
        self.profile.auth_source='active_directory'
        self.profile.directory_roles_managed=True
        self.profile.save()
        with self.assertRaises(UserAccessValidationError):
            update_user_access(self.profile, {'platform_roles':['resources']}, self.super_user)

    def test_revoked_business_role_does_not_retain_permission_based_access(self):
        from django.contrib.auth.models import Permission
        self.user.user_permissions.add(Permission.objects.get(codename='view_business_review'))
        self.assertFalse(has_business_review_permission(self.user,'view_business_review'))

    def test_admin_assigns_independent_business_roles_without_superuser(self):
        item = update_user_access(self.profile, {'platform_roles':['excellence_center','resources']}, self.admin)
        user = User.objects.get(pk=item.django_user_id)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertTrue(has_module_access(user,'excellence_center'))
        self.assertFalse(has_module_access(user,'reporting'))
        self.assertTrue(has_module_access(user,'resources'))

    def test_module_direct_urls_enforced(self):
        for path in ['/excellence-center/','/api/home/availability-command-center/','/resources/','/business-review/command-center/']:
            self.assertEqual(enforce_request_access(self.request(self.user,path)).status_code,403)
        self.assertIsNone(enforce_request_access(self.request(self.user,'/reporting/')))

    def test_legacy_write_endpoints_cannot_bypass_new_checks(self):
        for actor in [self.admin,self.super_user]:
            self.assertEqual(enforce_request_access(self.request(actor,'/users/1/roles/','post')).status_code,403)

    def test_role_change_preserves_all_scope_keys(self):
        scope={'country':['Mali'],'customer':['Customer'],'minesite':['Fekola'], 'minesites':['Fekola'],
               'account_codes':['A1'],'rls_role':'Fekola','other_rule':{'model':['777']},ROLE_KEY:['reporting']}
        self.profile.business_performance_scope = scope
        self.profile.business_performance_role = 'Viewer'
        self.profile.save()
        with patch('reports.user_access_service._minesite_options',return_value=['Fekola']):
            result=update_user_access(self.profile, {'platform_roles':['business_overview','reporting']}, self.super_user)
        self.assertEqual({k:v for k,v in result.business_performance_scope.items() if k!=ROLE_KEY}, {k:v for k,v in scope.items() if k!=ROLE_KEY})

    def test_business_role_grants_read_but_not_publication_or_draft_preview(self):
        user, profile=self.account('business',['business_overview'])
        self.assertTrue(has_business_review_permission(user,'view_business_command_center'))
        self.assertTrue(has_business_review_permission(user,'view_business_review_financials'))
        self.assertFalse(has_business_review_permission(user,'preview_business_review_draft'))
        self.assertFalse(has_business_review_permission(user,'create_business_review_action'))
        self.assertEqual(filter_published_rows([{'minesite_name':'Fekola','account_code':'A1'}], user), [])

    def test_last_super_admin_cannot_be_removed(self):
        with self.assertRaises(UserAccessValidationError):
            update_user_access(self.super_profile, {'platform_roles':['admin']}, self.super_user)

    def test_ad_manual_admin_does_not_become_super_on_login(self):
        self.admin_profile.auth_source='active_directory'
        self.admin_profile.directory_object_id='directory-admin'
        self.admin_profile.save()
        identity=DirectoryIdentity('directory-admin','admin','admin@example.test','','Admin','CN=Admin',['Privileged'],False)
        with patch('reports.active_directory_service._settings',return_value={'admin_groups':['Privileged']}):
            user=synchronize_identity(identity,None)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.admin_profile.refresh_from_db()
        self.assertEqual(profile_roles(self.admin_profile), ['admin'])

    def test_inactive_profile_denies_even_django_super_flags(self):
        self.super_profile.is_active=False
        self.super_profile.save()
        self.assertFalse(is_platform_admin(User.objects.get(pk=self.super_user.pk)))

    def test_navigation_only_shows_assigned_modules(self):
        request=self.request(self.user,'/reporting/')
        html=render_to_string('reports/includes/app_nav.html',{'request':request})
        self.assertIn('>Reporting</span>',html)
        self.assertNotIn('>Excellence Center</span>',html)
        self.assertNotIn('>Resources</span>',html)
