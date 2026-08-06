import json
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import AIConfigSection, KnowledgeSynonym
from .powerbi_interaction_orchestrator import _apply_resolved_entities
from .synonym_resolution_service import resolve_synonyms


class SynonymModelTests(TestCase):
    def setUp(self):
        self.section = AIConfigSection.objects.create(name="Performance", code="synonym_test")

    def create(self, **overrides):
        values = {
            "section": self.section,
            "canonical_term": "availability",
            "synonym": "Physical Availability",
            "entity_type": "KPI",
            "language": "en",
            "validation_status": "Validated",
        }
        values.update(overrides)
        return KnowledgeSynonym.objects.create(**values)

    def test_manual_defaults_and_normalization(self):
        item = self.create()
        self.assertEqual(item.synonym_source, "Manual")
        self.assertEqual(item.normalized_value, "availability")
        self.assertEqual(item.normalized_synonym_key, "physical availability")
        self.assertEqual(item.match_type, "Phrase")
        self.assertEqual(item.usage_count, 0)

    def test_ai_generated_is_always_draft_on_creation(self):
        item = self.create(synonym="PA", synonym_source="AI Generated")
        self.assertEqual(item.validation_status, "Draft")

    def test_duplicate_is_case_space_and_accent_insensitive(self):
        self.create(synonym="Disponibilité Physique", language="fr")
        duplicate = KnowledgeSynonym(
            section=self.section,
            canonical_term="availability",
            synonym="  disponibilite   physique ",
            entity_type="KPI",
            language="fr",
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_conflicting_canonical_requires_ambiguity_flag(self):
        self.create(synonym="PA")
        conflict = KnowledgeSynonym(
            section=self.section,
            canonical_term="planned_activity",
            synonym="pa",
            entity_type="KPI",
            language="en",
        )
        with self.assertRaises(ValidationError):
            conflict.full_clean()
        conflict.is_ambiguous = True
        conflict.full_clean()


class SynonymResolutionTests(TestCase):
    def setUp(self):
        self.section = AIConfigSection.objects.create(
            name="Performance", code="resolution_test", synonym_ambiguity_threshold=90
        )

    def synonym(self, **overrides):
        values = {
            "section": self.section,
            "canonical_term": "availability",
            "normalized_value": "availability",
            "synonym": "PA",
            "entity_type": "KPI",
            "language": "en",
            "confidence": 100,
            "resolution_priority": 100,
            "match_type": "Abbreviation",
            "validation_status": "Validated",
            "is_active": True,
        }
        values.update(overrides)
        return KnowledgeSynonym.objects.create(**values)

    def test_exact_resolution_returns_normalized_metadata(self):
        self.synonym()
        result = resolve_synonyms("Give me PA", section_code=self.section.code)
        entity = result["resolved_entities"][0]
        self.assertEqual(entity["normalized_value"], "availability")
        self.assertEqual(entity["match_type"], "Abbreviation")
        self.assertFalse(result["requires_clarification"])

    def test_exact_single_token_and_phrase_are_resolved(self):
        self.synonym(synonym="availability", match_type="Exact")
        self.synonym(
            synonym="physical availability",
            match_type="Phrase",
            canonical_term="physical_availability",
            normalized_value="physical_availability",
        )
        result = resolve_synonyms(
            "Show physical availability and availability",
            section_code=self.section.code,
        )
        values = {item["normalized_value"] for item in result["resolved_entities"]}
        self.assertIn("availability", values)
        self.assertIn("physical_availability", values)

    def test_ambiguous_low_score_requests_clarification(self):
        self.synonym(is_ambiguous=True, resolution_priority=50, confidence=80)
        result = resolve_synonyms("Show me PA", section_code=self.section.code)
        self.assertTrue(result["requires_clarification"])

    def test_usage_is_atomic_and_test_does_not_count_by_default(self):
        item = self.synonym()
        resolve_synonyms("Give me PA", section_code=self.section.code)
        item.refresh_from_db()
        self.assertEqual(item.usage_count, 0)
        resolve_synonyms("Give me PA", section_code=self.section.code, count_usage=True)
        item.refresh_from_db()
        self.assertEqual(item.usage_count, 1)
        self.assertIsNotNone(item.last_used_at)
        self.assertEqual(item.last_used_question, "Give me PA")

    def test_draft_is_excluded_in_production_and_used_in_debug(self):
        self.synonym(validation_status="Draft")
        production = resolve_synonyms("Give me PA", section_code=self.section.code)
        debug = resolve_synonyms("Give me PA", section_code=self.section.code, mode="Debug")
        self.assertEqual(production["resolved_entities"], [])
        self.assertEqual(debug["resolved_entities"][0]["validation_status"], "Draft")

    def test_site_typo_and_worded_period_become_filters(self):
        self.synonym(
            canonical_term="Sangaredi/CBG",
            normalized_value="Sangaredi/CBG",
            synonym="GBG",
            entity_type="Mine Site",
            match_type="Abbreviation",
        )
        self.synonym(
            canonical_term="period",
            normalized_value="last 12 months",
            synonym="last twelve months",
            entity_type="Period",
            match_type="Phrase",
        )
        resolution = resolve_synonyms(
            "Give me availability for GBG over the last twelve months",
            section_code=self.section.code,
        )
        intent = _apply_resolved_entities(
            {
                "section": self.section.code,
                "metric": "availability",
                "intent_type": "single_kpi",
                "filters": {},
            },
            resolution,
        )
        self.assertEqual(intent["filters"]["minesite"], "Sangaredi/CBG")
        self.assertEqual(intent["filters"]["period"], "last 12 months")


class SynonymAdminApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("syn-admin", "syn@example.com", "password")
        self.section = AIConfigSection.objects.create(name="Performance", code="syn_api")
        self.client.force_login(self.admin)

    def test_create_tracks_user_and_defaults(self):
        response = self.client.post(
            "/knowledge-base/api/synonym-library/",
            data=json.dumps({
                "section": self.section.code,
                "canonical_term": "availability",
                "synonym": "physical availability",
                "entity_type": "KPI",
                "language": "en",
                "confidence": 100,
                "validation_status": "Validated",
                "is_active": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = KnowledgeSynonym.objects.get(
            section=self.section,
            synonym="physical availability",
        )
        self.assertEqual(item.created_by, self.admin)
        self.assertEqual(item.validated_by, self.admin)
        self.assertIsNotNone(item.validated_at)

    def test_critical_edit_resets_validated_record(self):
        item = KnowledgeSynonym.objects.create(
            section=self.section, canonical_term="availability", synonym="availability",
            entity_type="KPI", validation_status="Validated",
        )
        response = self.client.put(
            f"/knowledge-base/api/synonym-library/{item.id}/",
            data=json.dumps({
                "section": self.section.code,
                "canonical_term": "availability",
                "synonym": "physical availability",
                "normalized_value": "availability",
                "entity_type": "KPI",
                "language": "en",
                "confidence": 100,
                "match_type": "Phrase",
                "resolution_priority": 50,
                "is_ambiguous": False,
                "synonym_source": "Business",
                "validation_status": "Validated",
                "is_active": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertEqual(item.validation_status, "To Review")

    def test_resolution_test_is_admin_only_and_does_not_count(self):
        item = KnowledgeSynonym.objects.create(
            section=self.section, canonical_term="availability", synonym="PA",
            normalized_value="availability", entity_type="KPI", match_type="Abbreviation",
            confidence=100, resolution_priority=100, validation_status="Validated",
        )
        response = self.client.post(
            "/knowledge-base/api/synonym-resolution-test/",
            data=json.dumps({"question": "Give me PA", "section": self.section.code}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.usage_count, 0)

    def test_standard_user_cannot_use_admin_resolution_or_analytics(self):
        standard = User.objects.create_user("standard", password="password")
        self.client.force_login(standard)
        resolution = self.client.post(
            "/knowledge-base/api/synonym-resolution-test/",
            data=json.dumps({"question": "Give me PA"}),
            content_type="application/json",
        )
        analytics = self.client.get("/knowledge-base/api/synonym-analytics/")
        self.assertIn(resolution.status_code, {302, 403})
        self.assertIn(analytics.status_code, {302, 403})

    def test_threshold_is_configurable(self):
        response = self.client.put(
            f"/knowledge-base/api/synonym-settings/{self.section.code}/",
            data=json.dumps({"ambiguity_threshold": 93}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.section.refresh_from_db()
        self.assertEqual(self.section.synonym_ambiguity_threshold, 93)

    def test_csv_import_and_filtered_json_export(self):
        csv_content = (
            "Section Code,Canonical Term,Synonym,Normalized Value,Entity Type,"
            "Language,Confidence,Synonym Source,Match Type,Resolution Priority,"
            "Is Ambiguous,Ambiguity Notes,Owner,Validation Status,Active\r\n"
            f"{self.section.code},availability,dispo,availability,KPI,fr,95,"
            "Business,Exact,80,No,,Reliability,Validated,Yes\r\n"
        ).encode("utf-8")
        upload = SimpleUploadedFile("synonyms.csv", csv_content, content_type="text/csv")
        response = self.client.post("/knowledge-base/synonyms/import/", {"file": upload})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["summary"]["created"], 1)
        export = self.client.get(
            f"/knowledge-base/synonyms/export/json/?section={self.section.code}&q=dispo"
        )
        self.assertEqual(export.status_code, 200)
        payload = json.loads(export.content)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["synonym"], "dispo")
        self.assertNotIn("usage_count", csv_content.decode("utf-8").splitlines()[0].lower())
