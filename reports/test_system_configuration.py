from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import SystemIntegrationConfig, SystemParameter
from .system_configuration_service import (
    MASKED_SECRET,
    decrypt_secrets,
    integration_payload,
    integration_value,
    save_integration,
)


class PortableSystemConfigurationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("config-admin", "admin@example.com", "password")
        self.viewer = User.objects.create_user("config-viewer", password="password")

    def create_openai_connection(self):
        return save_integration(
            SystemIntegrationConfig(),
            {
                "code": "openai-test",
                "name": "OpenAI Test",
                "integration_type": "OpenAI",
                "is_default": True,
                "is_active": True,
                "settings": {
                    "api_key": "test-secret-key",
                    "admin_api_key": "test-admin-key",
                    "organization_id": "org-test",
                    "project_id": "project-test",
                    "default_model": "test-model",
                    "api_base": "https://api.openai.com/v1",
                    "timeout_seconds": 90,
                },
            },
            self.admin,
        )

    def test_secrets_are_encrypted_and_masked(self):
        item = self.create_openai_connection()
        self.assertNotIn("test-secret-key", item.encrypted_secrets)
        self.assertEqual(decrypt_secrets(item)["api_key"], "test-secret-key")
        payload = integration_payload(item)
        self.assertEqual(payload["settings"]["api_key"], MASKED_SECRET)
        self.assertNotIn("test-secret-key", str(payload))

    def test_masked_secret_is_retained_on_update(self):
        item = self.create_openai_connection()
        save_integration(
            item,
            {
                "code": item.code,
                "name": "Updated OpenAI",
                "integration_type": "OpenAI",
                "settings": {
                    **item.settings_json,
                    "api_key": MASKED_SECRET,
                    "admin_api_key": MASKED_SECRET,
                },
            },
            self.admin,
        )
        self.assertEqual(decrypt_secrets(item)["api_key"], "test-secret-key")

    def test_runtime_resolver_reads_default_connection(self):
        self.create_openai_connection()
        self.assertEqual(integration_value("OpenAI", "default_model"), "test-model")
        self.assertEqual(integration_value("OpenAI", "api_key", secret=True), "test-secret-key")

    @patch("reports.views.ensure_portable_configuration")
    def test_connections_api_is_admin_only_and_never_reveals_secret(self, _ensure):
        self.create_openai_connection()
        self.client.force_login(self.viewer)
        denied = self.client.get(reverse("system-integrations-api"))
        self.assertIn(denied.status_code, {302, 403})

        self.client.force_login(self.admin)
        response = self.client.get(reverse("system-integrations-api"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("test-secret-key", str(body))
        self.assertEqual(body["items"][0]["settings"]["api_key"], MASKED_SECRET)

    @patch("reports.views.ensure_portable_configuration")
    def test_runtime_parameter_can_be_updated_by_admin(self, _ensure):
        item = SystemParameter.objects.create(
            key="test-page-size",
            category="Runtime",
            label="Test Page Size",
            value_type="Integer",
            value_json=25,
        )
        self.client.force_login(self.admin)
        response = self.client.put(
            reverse("system-parameter-item-api", args=[item.pk]),
            data='{"value":"75"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.value_json, 75)

    def test_string_false_is_not_saved_as_true(self):
        item = save_integration(
            SystemIntegrationConfig(),
            {
                "code": "storage-test",
                "name": "Storage Test",
                "integration_type": "Storage",
                "is_active": "false",
                "settings": {"root_path": "C:/data"},
            },
            self.admin,
        )
        self.assertFalse(item.is_active)
