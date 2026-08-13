from types import SimpleNamespace
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from .availability_diagnostics_service import (
    build_availability_diagnostics_dax,
    parse_availability_diagnostics_rows,
)
from .availability_reference_service import resolve_availability_references
from .dax_generator_service import generate_dax_from_intent
from .intent_extractor_service import extract_intent
from .powerbi_interaction_orchestrator import (
    _apply_resolved_entities,
    _answer_payload,
    _availability_confirmation_answer,
)
from .powerbi_interaction_service import is_follow_up_question, merge_conversation_intent


METRIC = {
    "metric_code": "availability",
    "metric_label": "Physical Availability",
    "powerbi_measure_name": "[Avail Per Equip]",
    "is_active": True,
}

FILTERS = [
    {
        "filter_code": "minesite",
        "powerbi_table_name": "MineSiteList_MiningProd",
        "powerbi_column_name": "MineSite",
        "data_type": "Text",
        "is_required": False,
        "is_active": True,
    },
    {
        "filter_code": "model",
        "powerbi_table_name": "EquipmentList_MiningProd",
        "powerbi_column_name": "Model",
        "data_type": "Text",
        "is_required": False,
        "is_active": True,
    },
    {
        "filter_code": "serial_number",
        "powerbi_table_name": "EquipmentList_MiningProd",
        "powerbi_column_name": "SN",
        "data_type": "Text",
        "is_required": False,
        "is_active": True,
    },
    {
        "filter_code": "period",
        "powerbi_table_name": "Date",
        "powerbi_column_name": "Year Month",
        "data_type": "Date",
        "is_required": False,
        "is_active": True,
    },
]


class AvailabilityIntentTests(SimpleTestCase):
    def _extract(self, question):
        with (
            patch(
                "reports.intent_extractor_service.get_section_by_code",
                return_value=SimpleNamespace(code="performance"),
            ),
            patch(
                "reports.intent_extractor_service.build_section_catalog",
                return_value={
                    "sections": [{
                        "metrics": [{
                            "metric_code": "availability",
                            "metric_label": "Physical Availability",
                        }],
                        "filters": [
                            {"filter_code": "minesite"},
                            {"filter_code": "model"},
                            {"filter_code": "family"},
                            {"filter_code": "serial_number"},
                            {"filter_code": "period"},
                        ],
                        "synonyms": [],
                    }]
                },
            ),
            patch("reports.intent_extractor_service.openai_extract_intent") as openai,
        ):
            intent = extract_intent(question, "performance")
        openai.assert_not_called()
        return intent

    def test_model_value_does_not_capture_rest_of_question(self):
        intent = self._extract(
            "Give me physical availability for model 6020 at Fekola in May 2026"
        )
        self.assertEqual(intent["metric"], "availability")
        self.assertEqual(intent["filters"]["model"], "6020")

    def test_explicit_family_and_serial_number_are_detected(self):
        intent = self._extract(
            "Availability family: Large Mining Trucks, serial number A1B2345 for 2025-05",
        )
        self.assertEqual(intent["filters"]["family"], "Large Mining Trucks")
        self.assertEqual(intent["filters"]["serial_number"], "A1B2345")
        self.assertEqual(intent["filters"]["period"], "2025-05")

    def test_availability_for_serial_number_remains_a_single_kpi(self):
        intent = self._extract(
            "Quelle est la disponibilité du serial number A1B2345 en juin 2026 ?"
        )

        self.assertEqual(intent["intent_type"], "single_kpi")
        self.assertEqual(intent["scope_type"], "serial_number")
        self.assertEqual(intent["filters"]["serial_number"], "A1B2345")
        self.assertEqual(intent["filters"]["period"], "2026-06")

    def test_trend_and_year_are_detected_locally(self):
        intent = self._extract("Show the monthly availability trend for Fekola in 2025")
        self.assertEqual(intent["intent_type"], "trend_analysis")
        self.assertEqual(intent["filters"]["period"], "2025")

    def test_lowest_models_is_a_ranking(self):
        intent = self._extract("Which models have the lowest availability at Fekola?")
        self.assertEqual(intent["intent_type"], "ranking")
        self.assertEqual(intent["comparison"]["dimension"], "model")
        self.assertEqual(intent["comparison"]["direction"], "asc")
        self.assertNotIn("model", intent["filters"])

    def test_relative_period_aliases_are_canonicalized(self):
        cases = {
            "Availability YTD for Fekola": "year to date",
            "Disponibilité depuis le début de l'année pour Fekola": "year to date",
            "Availability MTD for Fekola": "month to date",
            "Disponibilité mois à date pour Fekola": "month to date",
            "Availability rolling 12 months for Fekola": "last 12 months",
            "Disponibilité sur les 12 mois glissants pour Fekola": "last 12 months",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                intent = self._extract(question)
                self.assertEqual(intent["filters"]["period"], expected)

    def test_month_without_year_uses_current_year(self):
        intent = self._extract(
            "Donne moi la disponibilité de Fekola pour les 777 en Mai"
        )
        self.assertEqual(intent["filters"]["period"], f"{date.today().year}-05")


class AvailabilityDaxTests(SimpleTestCase):
    def _generate(self, intent):
        with (
            patch(
                "reports.dax_generator_service.get_section_by_code",
                return_value=SimpleNamespace(code="performance"),
            ),
            patch(
                "reports.dax_generator_service.get_metric_mapping",
                return_value=[METRIC],
            ),
            patch(
                "reports.dax_generator_service.get_filter_mapping",
                return_value=FILTERS,
            ),
            patch(
                "reports.dax_generator_service.get_dax_template",
                return_value={"template_code": "single_metric_by_filters"},
            ),
        ):
            return generate_dax_from_intent(intent)["dax"]

    def test_single_value_uses_all_configured_filters(self):
        dax = self._generate({
            "section": "performance",
            "intent_type": "single_kpi",
            "metric": "availability",
            "filters": {
                "minesite": "Fekola",
                "model": "777",
                "period": "2025-05",
            },
        })
        self.assertIn('[Avail Per Equip]', dax)
        self.assertIn('TREATAS({"Fekola"}', dax)
        self.assertIn('TREATAS({"777"}', dax)
        self.assertIn("DATE(2025, 5, 1)", dax)

    def test_single_machine_availability_filters_the_serial_number(self):
        dax = self._generate({
            "section": "performance",
            "intent_type": "single_kpi",
            "metric": "availability",
            "filters": {
                "serial_number": "A1B2345",
                "period": "2026-06",
            },
        })

        self.assertIn("[Avail Per Equip]", dax)
        self.assertIn('TREATAS({"A1B2345"}, \'EquipmentList_MiningProd\'[SN])', dax)
        self.assertIn("DATE(2026, 6, 1)", dax)


    def test_comparison_uses_multiple_site_values(self):
        dax = self._generate({
            "section": "performance",
            "intent_type": "comparison",
            "metric": "availability",
            "filters": {"period": "2025-05"},
            "comparison": {"minesite": ["Fekola", "Siguiri"]},
        })
        self.assertIn('TREATAS({"Fekola", "Siguiri"}', dax)
        self.assertIn("'MineSiteList_MiningProd'[MineSite]", dax)

    def test_trend_groups_and_orders_by_month(self):
        dax = self._generate({
            "section": "performance",
            "intent_type": "trend",
            "metric": "availability",
            "filters": {"minesite": "Fekola", "period": "2025"},
        })
        self.assertIn("'Date'[Year Month]", dax)
        self.assertIn("DATE(2025, 1, 1)", dax)
        self.assertIn("ORDER BY 'Date'[Year Month Number]", dax)

    def test_relative_periods_generate_controlled_dax(self):
        cases = {
            "year to date": "DATE(YEAR(TODAY()), 1, 1), TODAY()",
            "month to date": "DATE(YEAR(TODAY()), MONTH(TODAY()), 1), TODAY()",
            "last 12 months": "DATESINPERIOD('Date'[Date], TODAY(), -12, MONTH)",
        }
        for period, expected in cases.items():
            with self.subTest(period=period):
                dax = self._generate({
                    "section": "performance",
                    "intent_type": "single_kpi",
                    "metric": "availability",
                    "filters": {"minesite": "Fekola", "period": period},
                })
                self.assertIn(expected, dax)
                self.assertIn("ROW(", dax)


class AvailabilityReferenceTests(SimpleTestCase):
    @patch(
        "reports.availability_reference_service._serial_catalog",
        return_value={},
    )
    @patch(
        "reports.availability_reference_service._family_catalog",
        return_value={},
    )
    def test_explicit_serial_is_preserved_when_reference_database_is_unavailable(
        self, _families, _serials
    ):
        filters, unresolved = resolve_availability_references(
            "availability serial number a1b2345",
            {"serial_number": "a1b2345"},
        )

        self.assertEqual(filters["serial_number"], "A1B2345")
        self.assertEqual(unresolved, [])

    def test_single_machine_answer_names_the_serial_number(self):
        answer = _answer_payload(
            {
                "intent_type": "single_kpi",
                "metric": "availability",
                "metric_label": "Physical Availability",
                "filters": {"serial_number": "A1B2345", "period": "2026-06"},
            },
            [{"Physical Availability": 0.8532}],
            "Quelle est la disponibilité du serial number A1B2345 en juin 2026 ?",
        )

        self.assertIn("machine A1B2345", answer["answer"])
        self.assertIn("85,32 %", answer["answer"])
        self.assertIn("juin 2026", answer["answer"])


class AvailabilityDiagnosticsTests(SimpleTestCase):
    def test_diagnostics_reuses_availability_filters(self):
        diagnostic_metric = {
            "metric_code": "downtime_hours",
            "metric_label": "Downtime Hours",
            "powerbi_measure_name": "[DonwtimeHours]",
            "is_active": True,
        }
        driver_filter = {
            "filter_code": "downtime_driver",
            "filter_label": "Downtime Driver",
            "powerbi_table_name": "DowntimeData_MiningProd",
            "powerbi_column_name": "DescriptionCat",
            "data_type": "Text",
            "is_required": False,
            "is_active": True,
        }
        with (
            patch(
                "reports.availability_diagnostics_service.get_metric_mapping",
                return_value=[METRIC, diagnostic_metric],
            ),
            patch(
                "reports.availability_diagnostics_service.get_filter_mapping",
                return_value=[*FILTERS, driver_filter],
            ),
        ):
            payload = build_availability_diagnostics_dax({
                "section": "performance",
                "metric": "availability",
                "filters": {
                    "minesite": "Fekola",
                    "model": "777",
                    "period": "2026-05",
                },
            }, work_type="Unplanned")
        self.assertIn("[DonwtimeHours]", payload["dax"])
        self.assertIn("'DowntimeData_MiningProd'[DescriptionCat]", payload["dax"])
        self.assertIn('TREATAS({"Fekola"}', payload["dax"])
        self.assertIn('TREATAS({"777"}', payload["dax"])
        self.assertIn("DATE(2026, 5, 1)", payload["dax"])
        self.assertIn('TREATAS({"Unplanned"}', payload["dax"])
        self.assertEqual(payload["work_type"], "Unplanned")

    def test_diagnostics_calculates_pareto_percentages(self):
        result = parse_availability_diagnostics_rows([
            {
                "DowntimeData_MiningProd[DescriptionCat]": "Engine",
                "[Downtime Hours]": 60,
                "[Total Downtime Hours]": 100,
            },
            {
                "DowntimeData_MiningProd[DescriptionCat]": "Electrical",
                "[Downtime Hours]": 25,
                "[Total Downtime Hours]": 100,
            },
        ])
        self.assertEqual(result["total_downtime_hours"], 100)
        self.assertEqual(result["drivers"][0]["share_percentage"], 60)
        self.assertEqual(result["drivers"][1]["cumulative_percentage"], 85)


class AvailabilityConversationTests(SimpleTestCase):
    def test_single_kpi_answer_uses_natural_english_context(self):
        payload = _answer_payload(
            {
                "intent_type": "single_kpi",
                "filters": {
                    "minesite": "Essakane",
                    "model": "785",
                    "period": "last 12 months",
                },
            },
            [{"[Availability]": 0.8282}],
            "What is the availability of Essakane 785 for the last 12 months?",
        )
        self.assertEqual(
            payload["answer"],
            "The physical availability of the 785 fleet at Essakane is 82.82% over the last 12 months.",
        )
        self.assertNotIn("model=", payload["answer"])
        self.assertNotIn("minesite=", payload["answer"])
        self.assertNotIn("period=", payload["answer"])

    def test_single_kpi_answer_uses_natural_french_context(self):
        payload = _answer_payload(
            {
                "intent_type": "single_kpi",
                "filters": {
                    "minesite": "Essakane",
                    "model": "785",
                    "period": "last 12 months",
                },
            },
            [{"[Availability]": 0.8282}],
            "Quelle est la disponibilité des 785 à Essakane ?",
        )
        self.assertEqual(
            payload["answer"],
            "La disponibilité physique du parc 785 à Essakane est de 82,82 % sur les 12 derniers mois.",
        )

    def test_canonical_period_does_not_require_a_synonym_record(self):
        extracted = {
            "section": "performance",
            "metric": "availability",
            "filters": {"period": "2026-05"},
        }
        with patch(
            "reports.powerbi_interaction_orchestrator.KnowledgeSynonym.objects"
        ) as objects:
            objects.filter.return_value.values_list.return_value = []
            resolved = _apply_resolved_entities(
                extracted,
                {"resolved_entities": []},
            )
        self.assertEqual(resolved["filters"]["period"], "2026-05")
        self.assertNotIn("_unresolved_filters", resolved)

    def test_complete_question_does_not_inherit_previous_model(self):
        previous = {
            "section": "performance",
            "metric": "availability",
            "filters": {"minesite": "Fekola", "model": "777", "period": "2025-05"},
        }
        current = {
            "section": "performance",
            "intent_type": "single_kpi",
            "metric": "availability",
            "filters": {"minesite": "Essakane", "period": "year to date"},
        }
        question = "Give me the availability of Essakane on year to date?"
        self.assertFalse(is_follow_up_question(question))
        merged = merge_conversation_intent(
            current,
            previous,
            inherit_previous=False,
        )
        self.assertEqual(
            merged["filters"],
            {"minesite": "Essakane", "period": "year to date"},
        )
        self.assertNotIn("model", merged["filters"])

    def test_short_follow_up_reuses_other_filters(self):
        previous = {
            "section": "performance",
            "metric": "availability",
            "filters": {"minesite": "Fekola", "model": "777", "period": "2025-05"},
        }
        current = {
            "section": "performance",
            "intent_type": "single_kpi",
            "metric": "availability",
            "filters": {"minesite": "Essakane"},
        }
        self.assertTrue(is_follow_up_question("And Essakane?"))
        merged = merge_conversation_intent(
            current,
            previous,
            inherit_previous=True,
        )
        self.assertEqual(merged["filters"]["minesite"], "Essakane")
        self.assertEqual(merged["filters"]["model"], "777")
        self.assertEqual(merged["filters"]["period"], "2025-05")

    def test_confirmation_is_a_follow_up_and_rechecks_value(self):
        question = "Tu es sûr que c'est 91.97% ?"
        self.assertTrue(is_follow_up_question(question))
        answer = _availability_confirmation_answer(
            question,
            [{"[Physical Availability]": 0.9197}],
        )
        self.assertIn("physical availability is 91.97%", answer)

    def test_incorrect_claim_is_corrected(self):
        answer = _availability_confirmation_answer(
            "Are you sure it is 91.97%?",
            [{"[Physical Availability]": 0.8831}],
        )
        self.assertIn("88.31%", answer)
        self.assertIn("not 91.97%", answer)
