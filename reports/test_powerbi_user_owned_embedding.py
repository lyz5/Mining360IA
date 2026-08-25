from __future__ import annotations

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from .microsoft_delegated_auth import InteractiveAuthenticationRequired
from .models import AIConfigSection, PlatformUser, PowerBIReport
from .powerbi_embed_strategy import PowerBIEmbedStrategyResolver, build_embed_configuration


@override_settings(
    ENABLE_USER_OWNS_DATA_EMBEDDING="Production",
    ENABLE_ENTRA_ACCOUNT_LINKING="Production",
)
class PowerBIUserOwnedEmbeddingTests(TestCase):
    def setUp(self):
        self.user = self._create_user("user@neemba.com", "oid-user")
        self.client.force_login(self.user)
        self.section = AIConfigSection.objects.create(code="performance-test", name="Performance Test")

    @staticmethod
    def _create_user(username, object_id):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username=username)
        PlatformUser.objects.create(
            django_user=user,
            azure_ad_id=object_id,
            user_principal_name=username,
            display_name="Test User",
            is_active=True,
            can_access_reporting=True,
            can_access_ai=True,
        )
        return user

    def _report(self, **overrides):
        values = {
            "section": self.section,
            "workspace_id": "workspace-id",
            "report_id": "report-id",
            "report_name": "Report",
            "display_name": "Report",
            "embed_url": "https://app.powerbi.com/reportEmbed?reportId=report-id",
            "validation_status": "Validated",
            "is_active": True,
        }
        values.update(overrides)
        return PowerBIReport.objects.create(**values)

    def test_standard_report_uses_app_owned_strategy(self):
        strategy = PowerBIEmbedStrategyResolver.resolve(self._report(), self.user)
        self.assertEqual(strategy.strategy, "app_owns_data")
        self.assertEqual(strategy.token_type, "Embed")

    @patch("reports.powerbi_embed_strategy.generate_report_embed_token", return_value="embed-token")
    def test_opening_profile_is_applied_to_embed_configuration(self, _token):
        report = self._report(
            opening_profile_name="Operations viewer",
            default_page_internal_name="ReportSectionOperations",
            display_option="fit_to_width",
            filter_pane_visible=True,
            page_navigation_visible=False,
            bookmarks_pane_visible=True,
            background_type="transparent",
        )

        config = build_embed_configuration(type("Request", (), {"user": self.user})(), report)

        self.assertEqual(config["pageName"], "ReportSectionOperations")
        self.assertEqual(config["openingProfile"]["displayOption"], "fit_to_width")
        self.assertEqual(config["openingProfile"]["backgroundType"], "transparent")
        self.assertTrue(config["settings"]["panes"]["filters"]["visible"])
        self.assertFalse(config["settings"]["panes"]["pageNavigation"]["visible"])
        self.assertTrue(config["settings"]["panes"]["bookmarks"]["visible"])

    def test_powerapps_report_uses_user_owned_strategy(self):
        report = self._report(
            authentication_mode="user_owns_data",
            contains_powerapps_visual=True,
            requires_user_identity=True,
        )
        strategy = PowerBIEmbedStrategyResolver.resolve(report, self.user)
        self.assertEqual(strategy.strategy, "user_owns_data")
        self.assertEqual(strategy.token_type, "Aad")

    def test_powerapps_report_rejects_app_owned_configuration(self):
        report = PowerBIReport(
            section=self.section,
            workspace_id="workspace-id",
            report_id="invalid-report",
            report_name="Invalid",
            display_name="Invalid",
            authentication_mode="app_owns_data",
            contains_powerapps_visual=True,
        )
        with self.assertRaises(ValidationError):
            report.full_clean()

    @patch("reports.powerbi_interaction_views.build_embed_configuration")
    def test_embed_endpoint_keeps_standard_embed_configuration(self, build):
        report = self._report()
        build.return_value = {
            "type": "report",
            "id": report.report_id,
            "accessToken": "not-logged-token",
            "tokenType": "Embed",
            "authenticationMode": "app_owns_data",
        }
        response = self.client.get(reverse("powerbi-interaction-embed-config", args=[report.report_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["config"]["tokenType"], "Embed")

    @patch("reports.powerbi_interaction_views.build_embed_configuration")
    def test_standard_user_cannot_override_configured_rls_role(self, build):
        report = self._report(default_rls_role="SiteManager")
        build.return_value = {
            "type": "report",
            "id": report.report_id,
            "accessToken": "not-logged-token",
            "tokenType": "Embed",
        }

        response = self.client.get(
            reverse("powerbi-interaction-embed-config", args=[report.report_id]),
            {"role": "Administrator"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(build.call_args.kwargs["role"], "SiteManager")

    @patch("reports.powerbi_interaction_views.build_embed_configuration")
    def test_user_owned_endpoint_requires_interactive_login_without_fallback(self, build):
        report = self._report(
            authentication_mode="user_owns_data",
            contains_powerapps_visual=True,
            requires_user_identity=True,
        )
        build.side_effect = InteractiveAuthenticationRequired()
        response = self.client.get(reverse("powerbi-interaction-embed-config", args=[report.report_id]))
        payload = response.json()
        self.assertEqual(response.status_code, 409)
        self.assertTrue(payload["authentication_required"])
        self.assertEqual(payload["authentication_mode"], "user_owns_data")
        self.assertIn("auth/powerbi/start", payload["connect_url"])

    def test_report_configuration_never_serializes_credentials(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        report = self._report(
            authentication_mode="user_owns_data",
            contains_powerapps_visual=True,
            requires_user_identity=True,
        )
        response = self.client.get(reverse("powerbi-interaction-collection", args=["reports"]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access_token", response.content.decode().lower())
        self.assertNotIn("client_secret", response.content.decode().lower())
