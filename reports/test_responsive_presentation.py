"""Presentation must preserve server permissions and every financial aggregate."""
from django.contrib.auth.models import AnonymousUser, User
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import PlatformUser
from . import test_business_command_center as command_fixtures

FEATURES = command_fixtures.FEATURES


@override_settings(**FEATURES)
class PresentationNavigationTests(TestCase):
    def nav(self, user, responsive=True, theme=True):
        request = RequestFactory().get('/resources/')
        request.user = user
        with override_settings(MINING360_RESPONSIVE_UI_ENABLED=responsive, MINING360_BUSINESS_THEME_ENABLED=theme):
            return render_to_string('reports/includes/app_nav.html', {'request':request,'active_section':'resources'})

    def test_disabled_restores_legacy_assets_and_no_mobile_listeners(self):
        user = User.objects.create_superuser('ui-admin', 'ui@example.test', 'test-only-password')
        html = self.nav(user,False,False)
        self.assertNotIn('responsive.css', html)
        self.assertNotIn('responsive.js', html)
        self.assertNotIn('presentation_bootstrap.js', html)
        self.assertNotIn('business_theme.css', html)
        self.assertIn('source_actions.js', html)

    def test_theme_and_layout_are_independent(self):
        user = User.objects.create_superuser('ui-admin', 'ui@example.test', 'test-only-password')
        layout = self.nav(user,True,False)
        theme = self.nav(user,False,True)
        self.assertIn('responsive.js',layout)
        self.assertNotIn('business_theme.css',layout)
        self.assertNotIn('responsive.js',theme)
        self.assertIn('business_theme.css',theme)

    def test_resource_only_user_never_gets_unauthorized_destinations(self):
        user = User.objects.create_user('ui-reader')
        PlatformUser.objects.create(django_user=user, azure_ad_id='ui-reader',
            user_principal_name='reader@example.test',display_name='UI Reader',
            business_performance_scope={'platform_roles_v2':['resources']})
        html = self.nav(user)
        self.assertIn(reverse('resources'), html)
        self.assertNotIn('data-mobile-destination=',html)
        self.assertNotIn('Deployment Process',html)
        self.assertNotIn('Business Mapping',html)

    def test_anonymous_user_gets_no_mobile_business_destination(self):
        html = self.nav(AnonymousUser())
        self.assertNotIn('data-mobile-destination=',html)

    def test_primary_links_are_defined_once_on_server(self):
        user = User.objects.create_superuser('ui-admin', 'ui@example.test', 'test-only-password')
        html = self.nav(user)
        self.assertEqual(html.count('data-mobile-destination="Business"'),1)
        self.assertEqual(html.count('data-mobile-destination="Excellence"'),1)
        self.assertEqual(html.count('data-mobile-destination="Reports"'),1)


@override_settings(**FEATURES)
class PresentationFinancialParityTests(TestCase):
    def setUp(self):
        fixture = command_fixtures.BusinessCommandCenterApiTests('test_page_and_bootstrap_load_without_published_mapping')
        fixture.setUp()
        self.client = fixture.client

    def test_presentation_switches_do_not_change_governed_payload(self):
        url = reverse('business-command-center-bootstrap-api')
        for params in ({}, {'business_line':'parts'}, {'division_scope':'all_divisions'}):
            with self.subTest(params=params):
                with override_settings(MINING360_RESPONSIVE_UI_ENABLED=False,MINING360_BUSINESS_THEME_ENABLED=False):
                    old = self.client.get(url, params).json()
                with override_settings(MINING360_RESPONSIVE_UI_ENABLED=True,MINING360_BUSINESS_THEME_ENABLED=True):
                    new = self.client.get(url, params).json()
                for key in ('hero','business_lines','reconciliation','monthly_trend','daily_trend','mix','waterfall'):
                    self.assertEqual(old.get(key),new.get(key),key)

    def test_same_source_rows_remain_identical(self):
        from .models import RevenueSourceSnapshot
        before = list(RevenueSourceSnapshot.objects.order_by('source_record_id').values_list('source_record_id','revenue_eur','active'))
        self.client.get(reverse('business-command-center'))
        after = list(RevenueSourceSnapshot.objects.order_by('source_record_id').values_list('source_record_id','revenue_eur','active'))
        self.assertEqual(before,after)
