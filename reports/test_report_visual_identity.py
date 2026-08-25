import tempfile
from io import BytesIO
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import (
    AIConfigSection,
    PlatformUser,
    PowerBIReport,
    ReportCategory,
    ReportingReportPreference,
)
from .report_visual_identity import ReportVisualIdentityResolver


class ReportVisualIdentityResolverTests(TestCase):
    def setUp(self):
        ReportCategory.objects.update_or_create(
            code="fleet_performance",
            defaults={
                "display_name": "Fleet Performance",
                "illustration_code": "fleet_performance",
                "icon_code": "activity",
                "accent_code": "emerald",
                "validation_status": "Validated",
            },
        )

    def preference(self, **overrides):
        values = {
            "report_id": str(uuid4()),
            "report_name": "Fleet Performance Report",
            "display_name": "Fleet Performance Report",
            "description": "Monitor availability, reliability, downtime and fleet performance.",
            "short_description": "Monitor availability, reliability, downtime and fleet performance.",
            "category": "fleet_performance",
            "tags_json": ["Availability", "Reliability"],
            "validation_status": "Validated",
        }
        values.update(overrides)
        return ReportingReportPreference.objects.create(**values)

    def test_manual_thumbnail_has_highest_automatic_priority(self):
        preference = self.preference(
            thumbnail_url="https://cdn.example.com/fleet.webp",
            thumbnail_status="configured",
            thumbnail_source="automatic",
            illustration_code="fleet_performance",
        )
        identity = ReportVisualIdentityResolver(preference).resolve()
        self.assertEqual(identity.source, "manual_thumbnail")
        self.assertEqual(identity.thumbnail_url, "https://cdn.example.com/fleet.webp")
        self.assertEqual(identity.accent, "emerald")

    def test_explicit_report_illustration_can_override_available_thumbnail(self):
        preference = self.preference(
            thumbnail_url="https://cdn.example.com/fleet.webp",
            thumbnail_status="configured",
            thumbnail_source="report_illustration",
            illustration_code="fleet_performance",
        )
        identity = ReportVisualIdentityResolver(preference).resolve()
        self.assertEqual(identity.source, "report_illustration")
        self.assertEqual(identity.illustration_code, "fleet_performance")

    def test_broken_thumbnail_falls_back_without_broken_image(self):
        preference = self.preference(
            thumbnail_url="https://cdn.example.com/missing.webp",
            thumbnail_status="failed",
            illustration_code="fleet_performance",
        )
        identity = ReportVisualIdentityResolver(preference).resolve()
        self.assertEqual(identity.source, "report_illustration")
        self.assertFalse(identity.thumbnail_url)
        self.assertEqual(identity.status, "invalid")

    def test_category_and_generic_fallbacks_are_deterministic(self):
        category_identity = ReportVisualIdentityResolver(self.preference()).resolve()
        self.assertEqual(category_identity.source, "category_illustration")
        generic = self.preference(
            report_id=str(uuid4()),
            report_name="Unclassified Report",
            display_name="Unclassified Report",
            category="other",
            description="",
            short_description="",
            tags_json=[],
        )
        generic_identity = ReportVisualIdentityResolver(generic).resolve()
        self.assertEqual(generic_identity.source, "generic_fallback")


class ReportThumbnailUploadTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.admin = User.objects.create_superuser("visual-admin", "admin@example.com", "password")
        self.user = User.objects.create_user("visual-user", password="password")
        PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="visual-user-oid",
            user_principal_name="visual-user@example.com",
            display_name="Visual User",
            can_access_reporting=True,
        )
        self.report_id = str(uuid4())
        self.preference = ReportingReportPreference.objects.create(
            report_id=self.report_id,
            report_name="Fleet Performance Report",
            display_name="Fleet Performance Report",
            category="fleet_performance",
        )
        section = AIConfigSection.objects.create(code="visual-tests", name="Visual Tests")
        PowerBIReport.objects.create(
            section=section,
            workspace_id="workspace",
            report_id=self.report_id,
            report_name="Fleet Performance Report",
            display_name="Fleet Performance Report",
            validation_status="Validated",
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media.cleanup()

    @staticmethod
    def png(width=1200, height=450):
        output = BytesIO()
        Image.new("RGB", (width, height), "#e6b800").save(output, format="PNG")
        return SimpleUploadedFile("fleet.png", output.getvalue(), content_type="image/png")

    def test_admin_can_upload_and_reporting_user_can_read_thumbnail(self):
        self.client.force_login(self.admin)
        upload = self.client.post(
            reverse("reporting-configuration-thumbnail-api", args=[self.report_id]),
            {"thumbnail": self.png()},
        )
        self.assertEqual(upload.status_code, 200, upload.content)
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.thumbnail_source, "manual_thumbnail")
        self.client.force_login(self.user)
        response = self.client.get(reverse("reporting-report-thumbnail", args=[self.report_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        response.close()

    def test_upload_rejects_small_or_spoofed_images(self):
        self.client.force_login(self.admin)
        small = self.client.post(
            reverse("reporting-configuration-thumbnail-api", args=[self.report_id]),
            {"thumbnail": self.png(320, 120)},
        )
        self.assertEqual(small.status_code, 400)
        spoofed = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        response = self.client.post(
            reverse("reporting-configuration-thumbnail-api", args=[self.report_id]),
            {"thumbnail": spoofed},
        )
        self.assertEqual(response.status_code, 400)

    def test_standard_user_cannot_upload_thumbnail(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("reporting-configuration-thumbnail-api", args=[self.report_id]),
            {"thumbnail": self.png()},
        )
        self.assertEqual(response.status_code, 403)
