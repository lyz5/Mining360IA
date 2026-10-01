from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from .platform_roles import ROLE_KEY
from .user_access_service import _validated_access


class LocalRoleCompatibilityTests(SimpleTestCase):
    @patch('reports.user_access_service._minesite_options', return_value=[])
    @patch('reports.user_access_service._business_options', return_value=([], [], []))
    @patch('reports.user_access_service.can_manage_users', return_value=True)
    @patch('reports.user_access_service.is_super_admin', return_value=False)
    def test_legacy_local_directory_flag_does_not_lock_manual_roles(self, *mocks):
        item=SimpleNamespace(auth_source='local',directory_roles_managed=True,
            business_performance_scope={ROLE_KEY:['reporting']},business_performance_role='')
        values=_validated_access({'platform_roles':['resources']},item=item,actor=object())
        self.assertEqual(values['roles'],['resources'])
        self.assertFalse(values['directory_roles_managed'])

    @patch('reports.user_access_service._minesite_options', return_value=[])
    @patch('reports.user_access_service._business_options', return_value=([], [], []))
    @patch('reports.user_access_service.can_manage_users', return_value=True)
    @patch('reports.user_access_service.is_super_admin', return_value=True)
    def test_super_admin_demotion_removes_implicit_business_administration(self, *mocks):
        item=SimpleNamespace(auth_source='local',directory_roles_managed=False,
            business_performance_scope={ROLE_KEY:['super_admin']},business_performance_role='Administrator')
        values=_validated_access({'platform_roles':['admin']},item=item,actor=object())
        self.assertEqual(values['bp_role'],'Viewer')
