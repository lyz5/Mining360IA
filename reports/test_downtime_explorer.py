from datetime import timedelta
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .downtime_context_service import (
    back_explorer,
    open_explorer,
    reset_explorer,
    select_dimension,
)
from .downtime_event_service import (
    comment_coverage,
    detect_repeated_failures,
    normalize_events,
)
from .downtime_query_service import (
    _cache_key,
    build_breakdown_dax,
    build_events_dax,
    build_summary_dax,
)
from .models import DowntimeExplorerSession
from .models import SMCSCode
from .smcs_service import resolve_event_smcs


class DowntimeExplorerContextTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="explorer-user",
            password="password",
        )

    def open_session(self):
        with patch(
            "reports.downtime_context_service.resolve_workspace_dataset_id",
            return_value="dataset-1",
        ):
            return open_explorer(
                user=self.user,
                conversation_id="",
                source_question="Availability for Fekola 777 in May 2026",
                current_context={
                    "filters": {
                        "minesite": "Fekola",
                        "model": "777",
                        "period": "2026-05",
                    }
                },
                selected_driver="PM",
            )

    def test_open_is_idempotent_and_preserves_context(self):
        first, first_created = self.open_session()
        second, second_created = self.open_session()

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.context_json["filters"]["minesite"], "Fekola")
        self.assertEqual(first.context_json["filters"]["model"], "777")
        self.assertEqual(
            first.context_json["selections"]["downtime_driver"],
            "PM",
        )

    def test_select_back_and_reset(self):
        session, _ = self.open_session()
        session = select_dimension(
            session,
            dimension_code="work_type",
            value="Planned",
        )
        self.assertEqual(session.context_json["selections"]["work_type"], "Planned")

        session = back_explorer(session)
        self.assertNotIn("work_type", session.context_json["selections"])

        session = select_dimension(
            session,
            dimension_code="labour_type",
            value="PM",
        )
        session = reset_explorer(session)
        self.assertEqual(
            session.context_json["selections"],
            {"downtime_driver": "PM"},
        )

    def test_cache_key_is_user_scoped(self):
        session, _ = self.open_session()
        other = get_user_model().objects.create_user(
            username="other-explorer-user",
            password="password",
        )
        session.pk = None
        session.id = None
        session.user = other
        session.context_hash = "different-user-context"
        session.expires_at = session.expires_at + timedelta(minutes=1)
        session.save()

        original = DowntimeExplorerSession.objects.filter(user=self.user).first()
        self.assertNotEqual(
            _cache_key(original, "summary", "EVALUATE ROW()"),
            _cache_key(session, "summary", "EVALUATE ROW()"),
        )


class DowntimeExplorerQueryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="query-user",
            password="password",
        )
        with patch(
            "reports.downtime_context_service.resolve_workspace_dataset_id",
            return_value="dataset-1",
        ):
            self.session, _ = open_explorer(
                user=self.user,
                conversation_id="",
                source_question="test",
                current_context={
                    "filters": {
                        "minesite": "Fekola",
                        "model": "777",
                        "period": "2026-05",
                    }
                },
                selected_driver="Electrical System",
            )

    def test_controlled_dax_uses_configured_measure_and_filters(self):
        dax = build_summary_dax(self.session)
        self.assertIn("[DonwtimeHours]", dax)
        self.assertIn("DescriptionCat", dax)
        self.assertIn("Electrical System", dax)
        self.assertIn("Fekola", dax)
        self.assertIn("777", dax)

    def test_event_dax_uses_fact_period_and_has_bounded_result(self):
        dax = build_events_dax(self.session, limit=25)
        self.assertIn("TOPN(25", dax)
        self.assertIn("'DowntimeData_MiningProd'[MonthYear]", dax)
        self.assertIn("DATE(2026, 5, 1)", dax)
        self.assertIn('"Comment"', dax)

    def test_unmapped_dimension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not mapped"):
            build_breakdown_dax(self.session, "component")


class DowntimeExplorerAnalysisTests(TestCase):
    def test_comment_coverage_is_based_on_returned_events(self):
        events = normalize_events([
            {
                "Serial Number": "A1",
                "Start Date": "2026-05-01T00:00:00",
                "End Date": "2026-05-01T02:00:00",
                "Duration": 2,
                "Comment": "Starter motor replaced after repeated failure.",
            },
            {
                "Serial Number": "A2",
                "Start Date": "2026-05-02T00:00:00",
                "End Date": "2026-05-02T06:00:00",
                "Duration": 6,
                "Comment": "",
            },
        ])
        coverage = comment_coverage(events)
        self.assertEqual(coverage["event_count"], 2)
        self.assertEqual(coverage["commented_event_count"], 1)
        self.assertEqual(coverage["coverage_percentage"], 25.0)

    def test_repeat_detection_uses_explicit_configured_rule(self):
        events = normalize_events([
            {
                "Serial Number": "A1",
                "Start Date": f"2026-05-{day:02d}T00:00:00",
                "End Date": f"2026-05-{day:02d}T02:00:00",
                "Duration": 2,
                "Downtime Driver": "Electrical System",
                "Work Type": "Unplanned",
            }
            for day in (1, 10, 20)
        ])
        result = detect_repeated_failures(events, window_days=30)
        self.assertTrue(result["patterns"])
        self.assertEqual(result["patterns"][0]["event_count"], 3)
        self.assertIn("Serial Number", result["logic"])

    def test_smcs_resolution_uses_explicit_codes_and_exact_descriptions(self):
        SMCSCode.objects.create(
            code="1408",
            description="Wiring Harness",
            validation_status="To Review",
        )
        SMCSCode.objects.create(
            code="108F",
            description="Diesel Particulate Filter",
            validation_status="To Review",
        )
        events = normalize_events([
            {
                "Serial Number": "A1",
                "Start Date": "2026-05-01T00:00:00",
                "End Date": "2026-05-01T04:00:00",
                "Duration": 4,
                "Comment": "Replaced damaged wiring harness.",
            },
            {
                "Serial Number": "A2",
                "Start Date": "2026-05-02T00:00:00",
                "End Date": "2026-05-02T06:00:00",
                "Duration": 6,
                "Comment": "Inspection completed under SMCS 108F.",
            },
        ])
        result = resolve_event_smcs(events)
        self.assertEqual([row["SMCS Code"] for row in result["rows"]], ["108F", "1408"])
        self.assertEqual(result["coverage"]["matched_event_count"], 2)
        self.assertIn("No AI-inferred code", result["matching_rule"])


class DowntimeExplorerPermissionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="api-user",
            email="api-user@example.com",
            password="password",
        )

    def test_open_requires_authentication(self):
        response = self.client.post(
            reverse("downtime-explorer-open"),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["error_code"], "AUTHENTICATION_REQUIRED")

    @patch(
        "reports.downtime_explorer_views.open_explorer",
        side_effect=Exception("Unexpected database failure"),
    )
    def test_open_returns_json_for_unexpected_error(self, _open_explorer):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("downtime-explorer-open"),
            data=json.dumps({"selected_value": "PM"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertFalse(response.json()["ok"])

    @patch(
        "reports.downtime_context_service.resolve_workspace_dataset_id",
        return_value="dataset-1",
    )
    def test_user_cannot_access_another_users_session(self, _resolver):
        owner = get_user_model().objects.create_user(
            username="session-owner",
            password="password",
        )
        session, _ = open_explorer(
            user=owner,
            conversation_id="",
            source_question="test",
            current_context={"filters": {"minesite": "Fekola"}},
            selected_driver="PM",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "downtime-explorer-summary",
                kwargs={"session_id": session.id},
            ),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
