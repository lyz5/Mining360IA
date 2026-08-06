from __future__ import annotations

from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from .downtime_comment_normalization_service import DowntimeCommentNormalizationService
from .downtime_smcs_classification_service import DowntimeSMCSClassificationService
from .models import (
    DowntimeSMCSClassification,
    SMCSClassificationConfig,
    SMCSCode,
    SMCSSynonym,
)
from .smcs_ai_classification_service import SMCSAIClassificationService, SMCSResultValidationService
from .smcs_deterministic_classification_service import SMCSDeterministicClassificationService


class SMCSClassificationTests(TestCase):
    def setUp(self):
        self.water_pump, _ = SMCSCode.objects.update_or_create(
            code="1361",
            defaults={
                "description": "Water Pump", "display_name": "Water Pump",
                "component": "Water Pump", "system": "Cooling System",
                "validation_status": "Validated",
            },
        )
        self.starter, _ = SMCSCode.objects.update_or_create(
            code="1453",
            defaults={
                "description": "Starter Motor", "display_name": "Starter Motor",
                "component": "Starter Motor", "validation_status": "Validated",
            },
        )
        self.normalizer = DowntimeCommentNormalizationService()
        self.deterministic = SMCSDeterministicClassificationService()

    def classify(self, comment, mode="Production"):
        return self.deterministic.classify(
            {"Comment": comment}, self.normalizer.normalize(comment), mode=mode
        )

    def test_explicit_known_code(self):
        result = self.classify("Repaired SMCS 1361.")
        self.assertEqual(result["primary_candidate"]["smcs_code"], "1361")
        self.assertEqual(result["primary_candidate"]["match_method"], "Explicit SMCS Code")

    def test_unknown_code_is_not_accepted(self):
        result = self.classify("Repaired SMCS 9999.")
        self.assertTrue(result["requires_ai"])
        self.assertIsNone(result["primary_candidate"])

    def test_exact_description(self):
        result = self.classify("Water Pump failure.")
        self.assertEqual(result["primary_candidate"]["smcs_code"], "1361")
        self.assertEqual(result["primary_candidate"]["match_method"], "Exact Description")

    def test_validated_synonym(self):
        SMCSSynonym.objects.create(
            smcs_reference=self.water_pump,
            synonym="waterpump",
            normalized_synonym="waterpump",
            validation_status="Validated",
        )
        result = self.classify("Waterpump replaced.")
        self.assertEqual(result["primary_candidate"]["match_method"], "Synonym Match")

    def test_draft_synonym_is_ignored_in_production(self):
        SMCSSynonym.objects.create(
            smcs_reference=self.water_pump,
            synonym="pump assy",
            normalized_synonym="pump assy",
            validation_status="To Review",
        )
        result = self.classify("Pump assy replaced.")
        self.assertIsNone(result["primary_candidate"])

    def test_empty_and_generic_comments(self):
        service = DowntimeSMCSClassificationService()
        config = SMCSClassificationConfig.objects.create(name="Tests")
        for comment in ("", "Machine down."):
            result = service.classify_event_preview(
                {"Event ID": "E1", "Comment": comment}, config
            )
            self.assertEqual(result["classification_status"], "unresolved")
            self.assertFalse(result["ai_used"])

    def test_negated_component_is_not_failed_component(self):
        result = self.classify("Starter Motor checked, no defect found.")
        self.assertIsNone(result["primary_candidate"])
        self.assertTrue(result["requires_ai"])
        self.assertEqual(result["secondary_mentions"][0]["mention_type"], "inspected")

    def test_result_validator_rejects_code_outside_candidates(self):
        result = {
            "classification_status": "matched",
            "primary_match": {"smcs_code": "1453", "confidence": 95},
            "secondary_mentions": [], "alternative_candidates": [],
            "detected_symptoms": [], "detected_causes": [],
            "detected_actions": [], "detected_delays": [],
        }
        with self.assertRaises(ValueError):
            SMCSResultValidationService().validate(
                result,
                [{"smcs_code": "1361", "smcs_description": "Water Pump"}],
                "Water pump replaced",
            )

    def test_confidence_thresholds(self):
        config = SMCSClassificationConfig.objects.create(
            name="Thresholds", auto_accept_threshold=85, review_threshold=70
        )
        candidates = [{"smcs_code": "1361"}]
        service = SMCSAIClassificationService()
        high = service.apply_thresholds({
            "primary_match": {"smcs_code": "1361", "confidence": 92},
            "alternative_candidates": [], "requires_review": False,
        }, candidates, config)
        medium = service.apply_thresholds({
            "primary_match": {"smcs_code": "1361", "confidence": 78},
            "alternative_candidates": [], "requires_review": False,
        }, candidates, config)
        low = service.apply_thresholds({
            "primary_match": {"smcs_code": "1361", "confidence": 55},
            "alternative_candidates": [], "requires_review": False,
        }, candidates, config)
        self.assertEqual(high["classification_status"], "matched")
        self.assertEqual(medium["classification_status"], "probable")
        self.assertEqual(low["classification_status"], "unresolved")
        self.assertIsNone(low["primary_match"])

    def test_preview_does_not_write_official_classification(self):
        ai_mock = Mock()
        ai_mock.classify.return_value = {
            "classification_status": "matched",
            "primary_match": {
                "smcs_code": "1361", "smcs_description": "Water Pump",
                "confidence": 97, "evidence_phrases": ["pump replaced"],
            },
            "alternative_candidates": [], "requires_review": False,
        }
        service = DowntimeSMCSClassificationService()
        service.ai = ai_mock
        service.candidates.retrieve = lambda *args, **kwargs: [{
            "smcs_code": "1361", "smcs_description": "Water Pump",
            "candidate_score": 90,
        }]
        config = SMCSClassificationConfig.objects.create(name="Preview")
        service.classify_event_preview({
            "Event ID": "E-1", "Comment": "Pump shaft leaking and pump replaced.",
            "Duration": 10,
        }, config)
        self.assertEqual(DowntimeSMCSClassification.objects.count(), 0)
