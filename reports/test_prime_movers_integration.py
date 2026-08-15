from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AIConfigSection,
    PlatformUser,
    PowerAppsLaunchContext,
    PowerBIReport,
    PrimeMoversIntegrationConfiguration,
    UserExternalIdentity,
)
from .powerbi_embed_strategy import PowerBIEmbedStrategyResolver
from .prime_movers_integration import CorporateIdentityMappingService, PrimeMoversContextService
from .prime_movers_integration import PrimeMoversIntegrationError


@override_settings(
    ENABLE_PRIME_MOVERS_DUAL_WORKSPACE="Production",
    ENABLE_PRIME_MOVERS_POWERAPPS_IFRAME="Production",
    ENABLE_PRIME_MOVERS_POWERAPPS_NEW_TAB="Production",
    ENABLE_PRIME_MOVERS_AUTH_DIAGNOSTICS="Production",
    ENABLE_ENTRA_ACCOUNT_LINKING="Production",
)
class PrimeMoversIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("diagnepa", password="test", is_staff=True, is_superuser=True)
        self.platform_user = PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="ad:directory-object-guid",
            directory_object_id="directory-object-guid",
            directory_username="NEEMBA\\diagnepa",
            user_principal_name="papa.diagne@neemba.com",
            display_name="Papa Diagne",
            is_active=True,
            is_platform_admin=True,
            can_access_reporting=True,
        )
        self.identity = UserExternalIdentity.objects.create(
            user=self.user,
            provider="microsoft_entra",
            tenant_id="7a1b77be-dbd5-45cb-8e11-b01cbec06667",
            external_object_id="entra-object-id",
            upn="papa.diagne@neemba.com",
            windows_identity="NEEMBA\\diagnepa",
            display_name="Papa Diagne",
            mapping_status="validated",
            last_verified_at=timezone.now(),
        )
        section = AIConfigSection.objects.create(code="machine_performance_pm", name="Machine Performance PM")
        self.report = PowerBIReport.objects.create(
            section=section,
            workspace_id="a378c518-bfc4-4cd7-a49d-ba40394db80f",
            report_id="7965812a-e2d7-4950-9651-a148d8fdd235",
            report_name="Prime Movers Operational Status",
            display_name="Prime Movers Operational Status",
            authentication_mode="app_owns_data",
            contains_powerapps_visual=True,
            requires_user_identity=False,
            launch_mode="prime_movers_workspace",
            validation_status="Validated",
        )
        self.config = PrimeMoversIntegrationConfiguration.objects.create(
            report=self.report,
            code="prime-movers-test",
            powerapps_visual_internal_name="36a5326c9e017bc36902",
            powerapps_app_id="f344207c-d3a7-45b9-ae09-6cd27f1f18f6",
            powerapps_tenant_id="7a1b77be-dbd5-45cb-8e11-b01cbec06667",
            powerapps_environment_id="Default-test",
            powerapps_launch_url="https://apps.powerapps.com/play/e/Default-test/a/f344207c-d3a7-45b9-ae09-6cd27f1f18f6",
            iframe_enabled=True,
            new_tab_fallback=True,
            validation_status="Validated",
        )
        self.client.force_login(self.user)

    def test_strategy_keeps_powerbi_app_owned(self):
        strategy = PowerBIEmbedStrategyResolver.resolve(self.report, self.user)
        self.assertEqual(strategy.strategy, "app_owns_data")
        self.assertEqual(strategy.token_type, "Embed")
        self.assertFalse(strategy.requires_interactive_user)

    def test_ad_object_id_is_not_used_as_entra_object_id(self):
        identity = CorporateIdentityMappingService.resolve(self.user)
        self.assertEqual(identity.object_id, "entra-object-id")
        self.assertNotEqual(identity.object_id, self.platform_user.directory_object_id)

    def test_entra_identity_cannot_be_reassigned_to_another_user(self):
        other = User.objects.create_user("other_identity", password="test")
        PlatformUser.objects.create(
            django_user=other,
            azure_ad_id="ad:other-directory-object",
            user_principal_name="papa.diagne@neemba.com.invalid",
            display_name="Other User",
        )
        with self.assertRaises(PrimeMoversIntegrationError) as captured:
            CorporateIdentityMappingService.validate_from_microsoft_account(other, {
                "tenant_id": self.identity.tenant_id,
                "object_id": self.identity.external_object_id,
                "username": "papa.diagne@neemba.com.invalid",
            })
        self.assertEqual(captured.exception.code, "ENTRA_IDENTITY_CONFLICT")

    def test_launch_context_uses_a_stable_opaque_identifier(self):
        request = RequestFactory().post("/")
        request.user = self.user
        request.META["HTTP_USER_AGENT"] = "Test Browser"
        context, launch_url = PrimeMoversContextService.create_launch_context(
            request=request,
            report=self.report,
            payload={"serial_number": "XYZ123", "minesite": "Essakane", "model": "785"},
        )
        self.assertIn(f"contextId={context.opaque_id}", launch_url)
        self.assertNotIn("serialNumber", launch_url)
        self.assertNotIn("mineSite", launch_url)
        self.assertNotIn("model=785", launch_url)
        self.assertEqual(context.external_identity, self.identity)

    def test_preloaded_context_is_reused_for_machine_selections(self):
        request = RequestFactory().post("/")
        request.user = self.user
        request.META["HTTP_USER_AGENT"] = "Test Browser"
        context, initial_url = PrimeMoversContextService.create_launch_context(
            request=request,
            report=self.report,
            payload={"preload": True},
        )
        updated, updated_url = PrimeMoversContextService.create_launch_context(
            request=request,
            report=self.report,
            payload={
                "context_id": str(context.opaque_id),
                "equipment_id": "EX011",
                "serial_number": "DNR00153",
                "minesite": "Fekola",
                "model": "6020",
                "selected_status": "Down",
            },
        )
        self.assertEqual(updated.pk, context.pk)
        self.assertEqual(updated_url, initial_url)
        self.assertEqual(updated.serial_number, "DNR00153")
        self.assertEqual(updated.mine_site, "Fekola")
        self.assertEqual(updated.model, "6020")
        self.assertEqual(updated.report_context_json["selection_version"], 1)

        second, second_url = PrimeMoversContextService.create_launch_context(
            request=request,
            report=self.report,
            payload={
                "context_id": str(context.opaque_id),
                "equipment_id": "WL034",
                "serial_number": "L8X00510",
                "minesite": "Siguiri",
                "model": "988",
                "selected_status": "At Risk",
            },
        )
        self.assertEqual(second.pk, context.pk)
        self.assertEqual(second_url, initial_url)
        self.assertEqual(second.serial_number, "L8X00510")
        self.assertEqual(second.report_context_json["selection_version"], 2)

    def test_pending_entra_mapping_does_not_block_direct_canvas_app_login(self):
        self.identity.delete()
        request = RequestFactory().post("/")
        request.user = self.user
        request.META["HTTP_USER_AGENT"] = "Test Browser"
        context, launch_url = PrimeMoversContextService.create_launch_context(
            request=request,
            report=self.report,
            payload={"serial_number": "XYZ123"},
        )
        self.assertIsNone(context.external_identity)
        self.assertIn("apps.powerapps.com", launch_url)
        self.assertNotIn("papa.diagne@neemba.com", launch_url)

    def test_launch_requires_one_equipment(self):
        response = self.client.post(
            reverse("prime-movers-launch-context", args=[self.report.report_id]),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "EQUIPMENT_CONTEXT_REQUIRED")

    def test_context_is_isolated_by_user(self):
        context = PowerAppsLaunchContext.objects.create(
            user=self.user,
            external_identity=self.identity,
            configuration=self.config,
            serial_number="XYZ123",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        other = User.objects.create_user("other", password="test")
        self.client.force_login(other)
        response = self.client.get(reverse("prime-movers-context-status", args=[context.opaque_id]))
        self.assertEqual(response.status_code, 404)

    def test_expired_context_is_rejected(self):
        context = PowerAppsLaunchContext.objects.create(
            user=self.user,
            external_identity=self.identity,
            configuration=self.config,
            serial_number="XYZ123",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        response = self.client.get(reverse("prime-movers-context-status", args=[context.opaque_id]))
        self.assertEqual(response.status_code, 410)
        context.refresh_from_db()
        self.assertEqual(context.status, "expired")

    def test_workspace_renders_dual_identity_labels(self):
        self.config.powerbi_safe_initial_page_internal_name = "safe-page"
        self.config.save(update_fields=["powerbi_safe_initial_page_internal_name"])
        response = self.client.get(reverse("prime-movers-workspace", args=[self.report.report_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mining 360 API")
        self.assertContains(response, "papa.diagne@neemba.com")
        self.assertContains(response, 'meta name="csrf-token"')
        self.assertContains(response, 'data-safe-initial-page="safe-page"')
        self.assertContains(response, f'data-target-page="{self.config.powerbi_page_internal_name}"')

    def test_workspace_supplies_csrf_token_for_integration_events(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.get(reverse("prime-movers-workspace", args=[self.report.report_id]))
        self.assertEqual(response.status_code, 200)
        token = response.cookies["csrftoken"].value
        event_response = csrf_client.post(
            reverse("prime-movers-event", args=[self.report.report_id]),
            data=json.dumps({"event": "powerbi_loaded"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(event_response.status_code, 200)

    def test_powerapps_loaded_event_is_audited(self):
        response = self.client.post(
            reverse("prime-movers-event", args=[self.report.report_id]),
            data=json.dumps({"event": "powerapps_loaded", "serial_number": "XYZ123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_diagnostics_never_return_tokens(self):
        response = self.client.get(
            reverse("prime-movers-diagnostics", args=[self.report.report_id]) + "?format=json"
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8").casefold()
        self.assertNotIn("access_token", body)
        self.assertNotIn("client_secret", body)
        self.assertEqual(response.json()["decision"]["recommended_strategy"], "dual_workspace")

    @patch("reports.views.list_workspace_reports")
    def test_generic_report_url_redirects_to_workspace(self, list_reports):
        runtime = type("Report", (), {
            "id": self.report.report_id,
            "display_name": self.report.display_name,
            "embed_url": "https://app.powerbi.com/reportEmbed",
        })()
        list_reports.return_value = [runtime]
        with patch("reports.views._visible_reporting_reports", return_value=[runtime]):
            response = self.client.get(reverse("report-detail", args=[self.report.report_id]))
        self.assertRedirects(
            response,
            reverse("prime-movers-workspace", args=[self.report.report_id]),
            fetch_redirect_response=False,
        )
