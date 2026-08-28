from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from deployment.models import ApplicationRelease, DeploymentCredential, DeploymentJob, DeploymentPlan, DeploymentTarget
from deployment.services.plans import DeploymentPlanService
from deployment.services.releases import DeploymentReleaseSourceService
from deployment.services.worker import DeploymentWorkerService
from deployment.services.credentials import credential_secret
from deployment.services.security import DeploymentNetworkSecurityService, sanitize_log_message
from deployment.services.execution import WindowsDeploymentExecutionService
from deployment.services.remote import DeploymentRemoteRemediationService
from deployment.services.system_doctor import DeploymentSystemDoctorService
from reports.models import PlatformUser


class DeploymentSecurityTests(TestCase):
    def test_remote_powershell_commands_are_transparent_and_not_encoded(self):
        command = WindowsDeploymentExecutionService._powershell_command("Write-Output 'status-ok'")

        self.assertIn("Write-Output", command)
        self.assertIn("RemoteSigned", command)
        self.assertNotIn("EncodedCommand", command)
        self.assertNotIn("ExecutionPolicy Bypass", command)

    def test_report_media_archive_contains_only_governed_visual_assets(self):
        with tempfile.TemporaryDirectory() as media_directory:
            visual_directory = Path(media_directory) / "report_visuals" / "thumbnails" / "2026" / "08"
            visual_directory.mkdir(parents=True)
            (visual_directory / "fleet.webp").write_bytes(b"approved-report-image")
            (visual_directory / "ignore.txt").write_text("not an image", encoding="utf-8")

            with override_settings(MEDIA_ROOT=media_directory):
                archive, summary = WindowsDeploymentExecutionService._build_report_media_archive()

            self.assertEqual(summary, {"files": 1, "bytes": 21})
            self.assertIsNotNone(archive)
            try:
                with zipfile.ZipFile(archive) as bundle:
                    self.assertEqual(
                        bundle.namelist(),
                        ["report_visuals/thumbnails/2026/08/fleet.webp"],
                    )
            finally:
                archive.close()

    def test_private_address_is_allowed(self):
        service = DeploymentNetworkSecurityService("10.0.0.0/8")
        self.assertEqual(service.resolve_and_validate("10.20.30.40"), ["10.20.30.40"])

    def test_external_address_is_rejected(self):
        service = DeploymentNetworkSecurityService("10.0.0.0/8")
        with self.assertRaisesMessage(ValueError, "outside the allowed"):
            service.resolve_and_validate("8.8.8.8")

    def test_loopback_is_rejected(self):
        service = DeploymentNetworkSecurityService("0.0.0.0/0")
        with self.assertRaisesMessage(ValueError, "not permitted"):
            service.resolve_and_validate("127.0.0.1")

    def test_log_secrets_are_masked(self):
        value = sanitize_log_message("password=hello token: abc123 API_KEY=secret")
        self.assertNotIn("hello", value)
        self.assertNotIn("abc123", value)
        self.assertNotIn("secret", value)

    def test_file_credential_cannot_escape_ssh_directory(self):
        credential = DeploymentCredential(
            name="Unsafe", credential_type="ssh_private_key", secret_reference="file:C:/Windows/win.ini"
        )
        self.assertEqual(credential_secret(credential), "")

    @patch("deployment.services.system_doctor.connection.ensure_connection", side_effect=OSError("database offline"))
    def test_system_doctor_still_reports_when_database_is_unavailable(self, _ensure_connection):
        result = DeploymentSystemDoctorService().run()

        database = next(item for item in result["checks"] if item["code"] == "database")
        self.assertEqual(database["status"], "Failed")

    def test_failed_deployment_prefers_structured_script_error_over_clixml(self):
        output = '{"status":"Failed","message":"Django validation failed with exit code 1."}'
        payload = WindowsDeploymentExecutionService._last_json_object(output, required=False)

        self.assertEqual(payload["message"], "Django validation failed with exit code 1.")
        self.assertEqual(
            WindowsDeploymentExecutionService._useful_error("#< CLIXML\n<Objs />", "Useful fallback"),
            "Useful fallback",
        )


class DeploymentBootstrapTests(TestCase):
    def test_bootstrap_is_idempotent_and_seeds_bodefm(self):
        call_command("bootstrap_deployment_process")
        call_command("bootstrap_deployment_process")
        target = DeploymentTarget.objects.get(name="BODEFM Test")
        self.assertEqual(target.environment, "Test")
        self.assertEqual(target.os_family, "windows")
        self.assertFalse(target.is_approved)
        self.assertEqual(DeploymentTarget.objects.filter(name="BODEFM Test").count(), 1)


class DeploymentViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("deploy-admin", "admin@example.com", "test-password")
        self.client.force_login(self.user)

    def test_admin_page_is_available(self):
        response = self.client.get(reverse("deployment-home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deployment Process")

    def test_admin_page_creates_csrf_cookie_for_ajax_actions(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.get(reverse("deployment-home"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)

    def test_health_endpoint_does_not_expose_configuration(self):
        self.client.logout()
        response = self.client.get(reverse("app-health"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["application"], "Mining360")
        self.assertNotIn("settings", payload)

    def test_create_target_rejects_external_network(self):
        response = self.client.post(
            reverse("deployment-targets-api"),
            data={"name": "External", "dns_name": "8.8.8.8", "environment": "Test", "port": 22},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DeploymentTarget.objects.filter(name="External").exists())

    def test_active_platform_admin_can_use_deployment_actions_without_hidden_django_permissions(self):
        platform_admin = get_user_model().objects.create_user(
            "platform-admin", "platform-admin@example.com", "test-password"
        )
        PlatformUser.objects.create(
            django_user=platform_admin,
            azure_ad_id="platform-admin-object-id",
            user_principal_name="platform-admin@example.com",
            email="platform-admin@example.com",
            display_name="Platform Administrator",
            is_platform_admin=True,
            is_active=True,
        )
        target = DeploymentTarget.objects.create(
            name="Platform Admin Target",
            environment="Test",
            ip_address="10.1.1.20",
            os_family="windows",
        )
        self.client.force_login(platform_admin)

        dashboard = self.client.get(reverse("deployment-dashboard-api"), HTTP_ACCEPT="application/json")
        approval = self.client.post(
            reverse("deployment-target-approve-api", args=[target.pk]),
            data={},
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(approval.status_code, 200)
        target.refresh_from_db()
        self.assertTrue(target.is_approved)

    def test_non_admin_cannot_use_deployment_actions(self):
        standard_user = get_user_model().objects.create_user(
            "standard-user", "standard@example.com", "test-password"
        )
        PlatformUser.objects.create(
            django_user=standard_user,
            azure_ad_id="standard-user-object-id",
            user_principal_name="standard@example.com",
            email="standard@example.com",
            display_name="Standard User",
            is_platform_admin=False,
            is_active=True,
        )
        target = DeploymentTarget.objects.create(
            name="Protected Target",
            environment="Test",
            ip_address="10.1.1.21",
            os_family="windows",
        )
        self.client.force_login(standard_user)

        response = self.client.post(
            reverse("deployment-target-approve-api", args=[target.pk]),
            data={},
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertFalse(target.is_approved)

    @patch("deployment.views.DeploymentTroubleshootingService.run")
    def test_admin_can_run_target_troubleshooting(self, troubleshoot):
        target = DeploymentTarget.objects.create(
            name="Troubleshooting Target",
            environment="Test",
            ip_address="10.1.1.22",
            os_family="windows",
        )
        troubleshoot.return_value = {
            "status": "Action Required",
            "checks": [],
            "actions_taken": [],
            "manual_actions": [{"code": "WINDOWS_DEPLOYMENT_ACL", "title": "Grant access"}],
        }

        response = self.client.post(
            reverse("deployment-target-troubleshoot-api", args=[target.pk]),
            data={},
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["status"], "Action Required")
        troubleshoot.assert_called_once()

    @patch("deployment.views.DeploymentSystemDoctorService.run")
    def test_admin_can_run_system_doctor_in_diagnosis_and_repair_modes(self, doctor):
        target = DeploymentTarget.objects.create(
            name="System Doctor Target",
            environment="Test",
            ip_address="10.1.1.23",
            os_family="windows",
        )
        doctor.return_value = {
            "status": "Degraded",
            "checks": [],
            "actions_taken": [],
            "manual_actions": [],
        }

        diagnosis = self.client.post(
            reverse("deployment-target-system-doctor-api", args=[target.pk]),
            data={"repair": False},
            content_type="application/json",
        )
        repair = self.client.post(
            reverse("deployment-target-system-doctor-api", args=[target.pk]),
            data={"repair": True},
            content_type="application/json",
        )

        self.assertEqual(diagnosis.status_code, 200)
        self.assertEqual(repair.status_code, 200)
        self.assertFalse(doctor.call_args_list[0].kwargs["repair"])
        self.assertTrue(doctor.call_args_list[1].kwargs["repair"])

    def test_remote_remediation_rejects_actions_outside_allowlist(self):
        target = DeploymentTarget.objects.create(
            name="Allowlist Target",
            environment="Test",
            ip_address="10.1.1.24",
            os_family="windows",
        )

        with self.assertRaisesMessage(ValueError, "Unsupported safe remediation"):
            DeploymentRemoteRemediationService().run(target, "run_arbitrary_command")


class DeploymentDryRunTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("dry-run-admin", "dry@example.com", "test-password")
        self.target = DeploymentTarget.objects.create(
            name="Linux Test", environment="Test", ip_address="10.1.1.10", os_family="debian", is_approved=True
        )
        self.release = ApplicationRelease.objects.create(
            version="1.0.0-test", name="Test", git_commit="a" * 40, status="Validated"
        )
        self.plan = DeploymentPlan.objects.create(
            name="Test plan", target=self.target, release=self.release, prepared_by=self.user
        )

    @patch("deployment.services.plans.DeploymentPrecheckService.run")
    def test_dry_run_never_applies_changes(self, precheck):
        precheck.return_value = {"status": "Passed", "checks": [], "failed": 0, "warnings": 0}
        result = DeploymentPlanService().dry_run(self.plan, user=self.user)
        self.assertTrue(result["ready"])
        self.assertEqual(result["changes_applied"], 0)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, "Ready")

    @patch("deployment.services.plans.DeploymentPrecheckService.run")
    def test_windows_test_target_is_ready_for_execution(self, precheck):
        self.target.os_family = "windows"
        self.target.save(update_fields=["os_family"])
        precheck.return_value = {"status": "Warning", "checks": [], "failed": 0, "warnings": 1}
        result = DeploymentPlanService().dry_run(self.plan, user=self.user)
        self.assertTrue(result["ready"])


class DeploymentReleaseSourceTests(TestCase):
    @patch("deployment.services.releases.Path.is_file", return_value=True)
    @patch("deployment.services.releases.subprocess.run")
    def test_latest_remote_commit_creates_validated_release(self, run, _is_file):
        run.return_value = CompletedProcess([], 0, stdout=f"{'b' * 40}\trefs/heads/main\n", stderr="")
        release = DeploymentReleaseSourceService().sync_latest()
        self.assertEqual(release.git_commit, "b" * 40)
        self.assertEqual(release.status, "Validated")
        self.assertEqual(DeploymentReleaseSourceService().sync_latest().pk, release.pk)

    @patch("deployment.services.releases.Path.is_file", return_value=True)
    @patch("deployment.services.releases.subprocess.run")
    def test_git_error_returns_provider_diagnostic(self, run, _is_file):
        run.side_effect = CalledProcessError(
            128,
            ["git", "ls-remote"],
            stderr="fatal: unable to access the configured repository",
        )
        with self.assertRaisesRegex(ValueError, "unable to access the configured repository"):
            DeploymentReleaseSourceService().sync_latest()


class OneClickDeploymentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("one-click", "deploy@example.com", "test-password")
        self.client.force_login(self.user)
        self.target = DeploymentTarget.objects.create(
            name="BODEFM Test One Click",
            environment="Test",
            ip_address="10.1.1.11",
            os_family="windows",
            is_approved=True,
            host_key_verified=True,
        )
        self.release = ApplicationRelease.objects.create(
            version="main-test-release", name="Main", git_commit="c" * 40, git_branch="main", status="Validated"
        )

    @patch("deployment.views.subprocess.Popen")
    @patch("deployment.views.subprocess.run")
    @patch("deployment.views.DeploymentPlanService.dry_run")
    @patch("deployment.views.DeploymentReleaseSourceService.sync_latest")
    def test_quick_deploy_queues_job(self, sync_latest, dry_run, run, popen):
        sync_latest.return_value = self.release
        dry_run.return_value = {"ready": True, "status": "Ready"}
        run.return_value.returncode = 0
        response = self.client.post(
            reverse("deployment-quick-deploy-api"),
            data={"target_id": self.target.pk, "confirmation": "DEPLOY"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(DeploymentJob.objects.get().status, "Queued")
        self.assertEqual(response.json()["worker_launcher"], "scheduled_task")
        popen.assert_not_called()

    @patch("deployment.views.subprocess.Popen")
    @patch("deployment.views.subprocess.run")
    def test_local_worker_is_started_when_scheduled_task_is_missing(self, run, popen):
        from deployment.views import _kick_deployment_worker

        run.return_value.returncode = 1
        self.assertEqual(_kick_deployment_worker(), "local_process")
        popen.assert_called_once()

    def test_quick_deploy_requires_explicit_confirmation(self):
        response = self.client.post(
            reverse("deployment-quick-deploy-api"),
            data={"target_id": self.target.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DeploymentJob.objects.exists())

    @patch("deployment.services.worker.WindowsDeploymentExecutionService.execute")
    def test_worker_completes_queued_job(self, execute):
        execute.return_value = {"status": "Succeeded", "message": "Health checks passed."}
        plan = DeploymentPlan.objects.create(
            name="Worker plan", target=self.target, release=self.release, prepared_by=self.user, status="Queued"
        )
        job = DeploymentJob.objects.create(deployment_plan=plan, status="Queued")
        worker = DeploymentWorkerService()
        claimed = worker.claim_next()
        worker.process(claimed)
        job.refresh_from_db()
        plan.refresh_from_db()
        self.assertEqual(job.status, "Succeeded")
        self.assertEqual(plan.status, "Succeeded")
        self.assertEqual(job.progress_percentage, 100)


class DeploymentFrontendContractTests(SimpleTestCase):
    def test_one_click_deployment_shows_immediate_progress(self):
        root = Path(settings.BASE_DIR) / "deployment"
        javascript = (root / "static" / "deployment" / "deployment.js").read_text(encoding="utf-8")
        stylesheet = (root / "static" / "deployment" / "deployment.css").read_text(encoding="utf-8")
        template = (root / "templates" / "deployment" / "home.html").read_text(encoding="utf-8")

        self.assertIn("showDeploymentPending()", javascript)
        self.assertIn("showDeploymentError(error.message)", javascript)
        self.assertIn("showCheckPending(pendingTitle, pendingMessage)", javascript)
        self.assertIn("Troubleshooting...", javascript)
        self.assertIn("System Doctor", javascript)
        self.assertIn("Repair safe issues", javascript)
        self.assertIn("deployment-spinner", stylesheet)
        self.assertNotIn("window.confirm", javascript)
        self.assertIn("deployment.js' %}?v=20260826-system-doctor-1", template)

    def test_windows_release_health_check_preserves_public_https_scheme(self):
        script = (
            Path(settings.BASE_DIR) / "deployment" / "windows" / "deploy_release.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("'X-Forwarded-Proto' = 'https'", script)
        self.assertIn("function Stop-Mining360Runtime", script)
        self.assertIn("Get-NetTCPConnection -LocalPort 8000", script)
        self.assertIn("Stop-Process -Id $listener.OwningProcess", script)
        self.assertIn("Get-CimInstance Win32_Process", script)
        self.assertIn("taskkill.exe /PID $process.ProcessId /T /F", script)
        self.assertIn("system_doctor --json", script)
        self.assertIn("report-media-{0}.zip", script)
        self.assertIn("Synchronized $mediaCount report visual media file(s)", script)
        self.assertIn("Copy-Item -Destination $reportVisualDestination -Recurse -Force", script)

        deployment_root = Path(settings.BASE_DIR) / "deployment"
        executable_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for pattern in ("*.py", "*.ps1")
            for path in deployment_root.rglob(pattern)
            if "tests" not in path.parts
        )
        self.assertNotIn("EncodedCommand", executable_sources)
        self.assertNotIn("ExecutionPolicy Bypass", executable_sources)

    def test_windows_runtime_trusts_only_required_proxy_headers(self):
        script = (
            Path(settings.BASE_DIR)
            / "deployment"
            / "windows"
            / "start_mining360.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn('MINING360_TRUSTED_PROXY" "127.0.0.1"', script)
        self.assertIn("--trusted-proxy=$trustedProxy", script)
        self.assertIn(
            '--trusted-proxy-headers="x-forwarded-proto x-forwarded-host"',
            script,
        )
