from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CodexDiagnosticRun


User = get_user_model()


@override_settings(ENABLE_CODEX_ADMIN="Admin Only")
class CodexAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user("root", password="test", is_superuser=True, is_staff=True)
        self.staff = User.objects.create_user("staff", password="test", is_staff=True)

    def test_staff_user_is_denied(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("codex_admin:home")).status_code, 403)

    def test_superuser_can_run_persisted_read_only_diagnostic(self):
        self.client.force_login(self.superuser)

        response = self.client.post(reverse("codex_admin:run-diagnostic"))

        self.assertEqual(response.status_code, 200)
        run = CodexDiagnosticRun.objects.get()
        self.assertEqual(run.requested_by, self.superuser)
        self.assertEqual(run.summary_json["mode"], "READ_ONLY")
        self.assertEqual(run.summary_json["queue"]["queued"], 0)
        self.assertTrue(all(item["present"] for item in run.summary_json["protected_files"]))

    @override_settings(ENABLE_CODEX_ADMIN="Disabled")
    def test_disabled_flag_denies_superuser(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("codex_admin:home")).status_code, 403)
