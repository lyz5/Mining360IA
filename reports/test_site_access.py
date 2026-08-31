from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import PlatformUser
from .site_access_service import SiteAccessDenied, effective_report_security, enforce_intent_site_scope


class SiteAccessServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("site.user@neemba.com")
        PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="site-user",
            user_principal_name="site.user@neemba.com",
            display_name="Fekola Site User",
            can_access_reporting=True,
            can_access_ai=True,
            business_performance_role="MineSite",
            business_performance_scope={"minesite": ["Fekola"], "rls_role": "Fekola"},
        )

    def test_scope_is_injected_when_question_has_no_site(self):
        intent = enforce_intent_site_scope({"filters": {}}, self.user)
        self.assertEqual(intent["filters"]["minesite"], "Fekola")

    def test_other_site_is_rejected(self):
        with self.assertRaises(SiteAccessDenied):
            enforce_intent_site_scope({"filters": {"minesite": "Essakane"}}, self.user)

    def test_report_security_uses_user_upn_and_dataset_role(self):
        security = effective_report_security(self.user, "FPR Global DB + RLS", "Global")
        self.assertTrue(security["restricted"])
        self.assertEqual(security["roles"], ["Fekola"])
        self.assertEqual(security["effective_username"], "site.user@neemba.com")
