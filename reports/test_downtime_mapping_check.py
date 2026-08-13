import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .downtime_mapping_check_service import (
    BlindDescriptionCATClassificationService,
    DowntimeMappingCheckError,
    DowntimeMappingComparisonService,
    classification_signature,
    comment_quality,
    estimate_run,
    sanitize_comment,
)
from .models import DescriptionCATReference, DowntimeMappingCheckItem, DowntimeMappingCheckRun


class DowntimeMappingServiceTests(TestCase):
    def setUp(self):
        self.electrical = DescriptionCATReference.objects.create(
            code="electrical-system", name="Electrical System", display_name="Electrical System",
            keywords_json=["alternator", "wiring"], validation_status="Validated",
        )

    def event(self, **overrides):
        value = {
            "event_id": "EVT-1", "labour_type": "Engine",
            "current_description_cat": "Engine",
            "comment": "Alternator failure confirmed and replacement alternator installed.",
            "work_type": "Unplanned", "model": "785", "minesite": "Essakane", "serial_number": "ABC123",
        }
        value.update(overrides)
        return value

    def test_sanitization_removes_personal_contact_data(self):
        sanitized, status = sanitize_comment("Call jean@example.com or +221 77 123 45 67 about alternator failure")
        self.assertEqual(status, "sanitized")
        self.assertNotIn("jean@example.com", sanitized)
        self.assertNotIn("77 123", sanitized)
        self.assertIn("alternator failure", sanitized)

    def test_comment_quality_rejects_empty_and_generic_comments(self):
        self.assertEqual(comment_quality(""), "Empty")
        self.assertEqual(comment_quality("Machine down"), "Generic")
        self.assertIn(comment_quality("Pompe à eau endommagée et remplacée après diagnostic"), {"Medium Quality", "High Quality"})

    @patch("reports.downtime_mapping_check_service.ai_gateway.generate_structured_output")
    def test_blind_request_excludes_current_description_cat(self, gateway):
        gateway.return_value = SimpleNamespace(
            structured_output={
                "classification_status": "matched", "recommended_description_cat": {"code": "electrical-system", "name": "Electrical System"},
                "confidence": 94, "reason": "Alternator failure", "evidence_phrases": ["Alternator failure confirmed"],
                "detected_information": {}, "alternative_candidates": [], "requires_review": False, "review_reason": None,
            }, request_id="req-1", usage={}, estimated_cost=0, model="test-model",
        )
        result, _ = BlindDescriptionCATClassificationService().classify(self.event(), [self.electrical])
        provider_payload = json.loads(gateway.call_args.kwargs["messages"][0]["content"])
        self.assertNotIn("current_description_cat", provider_payload)
        self.assertNotIn("Description CAT currently", gateway.call_args.kwargs["options"]["system_instructions"])
        self.assertEqual(result["recommended_description_cat"]["code"], "electrical-system")

    @patch("reports.downtime_mapping_check_service.ai_gateway.generate_structured_output")
    def test_unknown_ai_category_is_rejected(self, gateway):
        gateway.return_value = SimpleNamespace(
            structured_output={"classification_status": "matched", "recommended_description_cat": {"code": "invented", "name": "Invented"}, "confidence": 99,
                               "reason": "x", "evidence_phrases": [], "detected_information": {}, "alternative_candidates": [], "requires_review": False, "review_reason": None},
        )
        with self.assertRaises(DowntimeMappingCheckError):
            BlindDescriptionCATClassificationService().classify(self.event(), [self.electrical])

    def test_comparison_statuses_are_deterministic(self):
        comparison = DowntimeMappingComparisonService()
        result = {"classification_status": "matched", "recommended_description_cat": {"code": "electrical-system", "name": "Electrical System"}, "confidence": 94}
        self.assertEqual(comparison.compare("Electrical System", result), "VERIFIED")
        self.assertEqual(comparison.compare("Engine", result), "MISMATCH")
        self.assertEqual(comparison.compare("", result), "UNMAPPED")
        self.assertEqual(comparison.compare("Engine", {"classification_status": "insufficient_evidence"}), "INSUFFICIENT_EVIDENCE")

    def test_signature_groups_identical_evidence_across_events(self):
        first = classification_signature(self.event(event_id="EVT-1"), [self.electrical])
        second = classification_signature(self.event(event_id="EVT-2"), [self.electrical])
        changed = classification_signature(self.event(event_id="EVT-2", comment="Different pump failure evidence"), [self.electrical])
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    @override_settings(DOWNTIME_MAPPING_MAX_DATE_RANGE_DAYS=31)
    def test_date_range_limit(self):
        with self.assertRaises(DowntimeMappingCheckError):
            estimate_run(date(2026, 1, 1), date(2026, 3, 1), {})


@override_settings(ENABLE_DOWNTIME_MAPPING_CHECK="Admin Only", DOWNTIME_MAPPING_DEV_THREAD_WORKER=False)
class DowntimeMappingApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("mapping-admin", password="test", is_staff=True)
        self.client.force_login(self.user)

    def test_page_is_available_to_admin(self):
        response = self.client.get(reverse("downtime-mapping-check"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Downtime Mapping Check")
        self.assertContains(response, "Check data")

    @patch("reports.downtime_mapping_views.estimate_run")
    def test_preview_returns_volume_and_cost(self, estimate):
        estimate.return_value = {"total_rows": 10, "rows_with_comment": 8, "cached_rows": 2, "ai_rows": 6, "rows_without_useful_comments": 2, "estimated_tokens": 3900, "estimated_cost": 0.01, "mode": "full"}
        response = self.client.post(reverse("downtime-mapping-preview-api"), data=json.dumps({"start_date": "2026-05-01", "end_date": "2026-05-31", "filters": {}}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preview"]["total_rows"], 10)

    def test_missing_dates_returns_business_error(self):
        response = self.client.post(reverse("downtime-mapping-preview-api"), data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("required", response.json()["error"])

    def test_review_decision_is_persisted_without_writeback(self):
        cat = DescriptionCATReference.objects.create(code="pm", name="PM", display_name="PM", validation_status="Validated")
        run = DowntimeMappingCheckRun.objects.create(created_by=self.user, start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), status="Completed")
        item = DowntimeMappingCheckItem.objects.create(
            run=run, downtime_event_id="EVT-10", labour_type="Scheduled Service", current_description_cat="Other",
            recommended_description_cat=cat, mapping_status="MISMATCH", confidence=96,
            classification_signature="a" * 64, comparison_signature="b" * 64,
        )
        response = self.client.post(reverse("downtime-mapping-review-api", args=[item.pk]), data=json.dumps({"decision": "Approve AI Recommendation", "notes": "Validated against work order"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.review_status, "Approved Recommendation")
        self.assertEqual(item.approved_description_cat, cat)
        self.assertFalse(item.applied)

    def test_csv_export_preserves_audit_data(self):
        run = DowntimeMappingCheckRun.objects.create(created_by=self.user, start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), status="Completed")
        DowntimeMappingCheckItem.objects.create(run=run, downtime_event_id="EVT-11", mapping_status="INSUFFICIENT_EVIDENCE", classification_signature="c" * 64, comparison_signature="d" * 64)
        response = self.client.get(reverse("downtime-mapping-export-api", args=[run.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("EVT-11", response.content.decode())

    def test_run_cannot_start_before_taxonomy_validation(self):
        DescriptionCATReference.objects.all().update(validation_status="To Review")
        response = self.client.post(reverse("downtime-mapping-runs-api"), data=json.dumps({"start_date": "2026-05-01", "end_date": "2026-05-02"}), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Validate at least one", response.json()["error"])
