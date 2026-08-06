from django.test import SimpleTestCase

from .downtime_comment_analysis_service import (
    REQUIRED_RESULT_KEYS,
    ROOT_CAUSE_OUTPUT_SCHEMA,
    ROOT_CAUSE_PROMPT_NAME,
    _validate_result,
)


class DowntimeCommentAnalysisContractTests(SimpleTestCase):
    def test_root_cause_prompt_is_selected_by_stable_name(self):
        self.assertEqual(
            ROOT_CAUSE_PROMPT_NAME,
            "Downtime Root Cause Comment Analysis",
        )

    def test_structured_output_requires_every_business_section(self):
        self.assertEqual(
            set(ROOT_CAUSE_OUTPUT_SCHEMA["required"]),
            REQUIRED_RESULT_KEYS,
        )
        self.assertFalse(ROOT_CAUSE_OUTPUT_SCHEMA["additionalProperties"])

    def test_valid_root_cause_payload_is_accepted(self):
        _validate_result({
            "coverage": {},
            "themes": [{"evidence_event_ids": ["EVT-1"]}],
            "repeated_patterns": [],
            "data_quality_findings": [],
            "summary": "Parts availability is explicitly mentioned.",
            "limitations": [],
            "suggested_investigations": [],
        })

    def test_invalid_payload_reports_missing_keys(self):
        with self.assertRaisesRegex(ValueError, "Missing keys"):
            _validate_result({"themes": []})
