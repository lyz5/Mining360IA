import json
import tempfile
from unittest.mock import patch
import uuid
from django.conf import settings
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from reports.models import (
    EquipmentFleetAnalysis,
    MappingSynchronizationRun,
    MineSite,
    MineSiteAlias,
    MappingPublication,
    PlatformUser,
    RevenueSourceSnapshot,
)

from .models import CodexChatbotPilot, CodexConversation, CodexEvidence, CodexMessage, CodexRun
from .async_service import process_next_run, run_payload
from codex_integration.app_server_turn import (
    AppServerTurnError,
    AppServerTurnInterrupted,
    AppServerTurnTimedOut,
    CodexTurnResult,
)


User = get_user_model()


class CodexChatbotAccessTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user("root", password="test", is_superuser=True, is_staff=True)
        self.staff = User.objects.create_user("staff", password="test", is_staff=True)
        self.pilot = User.objects.create_user("pilot", password="test")
        self.platform_admin = User.objects.create_user("platform-admin", password="test")
        PlatformUser.objects.create(
            azure_ad_id="platform-admin",
            user_principal_name="platform-admin@example.test",
            display_name="Platform Admin",
            django_user=self.platform_admin,
            is_platform_admin=True,
        )

    @override_settings(ENABLE_CODEX_CHATBOT="Admin Only")
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("codex_chatbot:home"))

        self.assertRedirects(
            response,
            f"{settings.LOGIN_URL}?next={reverse('codex_chatbot:home')}",
            fetch_redirect_response=False,
        )

    @override_settings(ENABLE_CODEX_CHATBOT="Admin Only", ENABLE_CODEX_ADMIN="Admin Only")
    def test_superuser_sees_both_codex_menu_entries(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("excellence-center"))

        self.assertContains(response, reverse("codex_chatbot:home"), count=1)
        self.assertContains(response, "<span>M360 Chatbot</span>", count=1, html=True)
        self.assertContains(response, reverse("codex_admin:home"), count=1)
        self.assertContains(response, "Codex Admin", count=1)

    @override_settings(ENABLE_CODEX_CHATBOT="Admin Only")
    def test_chatbot_uses_m360_brand_and_exposes_business_review_entrypoint(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("codex_chatbot:home"))

        self.assertContains(response, "M360 Chatbot")
        self.assertContains(response, "BUSINESS OVERVIEW")
        self.assertContains(response, "Revenue Parts YTD")
        self.assertNotContains(response, "Codex Chatbot")

    @override_settings(ENABLE_CODEX_CHATBOT="Admin Only", ENABLE_CODEX_ADMIN="Admin Only")
    def test_platform_administrator_sees_and_opens_both_codex_modules(self):
        self.client.force_login(self.platform_admin)

        dashboard = self.client.get(reverse("excellence-center"))

        self.assertContains(dashboard, reverse("codex_chatbot:home"), count=1)
        self.assertContains(dashboard, reverse("codex_admin:home"), count=1)
        self.assertEqual(self.client.get(reverse("codex_chatbot:home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("codex_admin:home")).status_code, 200)

    @override_settings(ENABLE_CODEX_CHATBOT="Disabled")
    def test_disabled_flag_denies_superuser(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("codex_chatbot:home")).status_code, 403)

    @override_settings(ENABLE_CODEX_CHATBOT="Pilot")
    def test_explicit_pilot_is_allowed(self):
        CodexChatbotPilot.objects.create(user=self.pilot)
        self.client.force_login(self.pilot)
        self.assertEqual(self.client.get(reverse("codex_chatbot:home")).status_code, 200)

    @override_settings(ENABLE_CODEX_CHATBOT="Admin Only")
    def test_staff_retains_existing_ai_access_after_merge(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("codex_chatbot:home")).status_code, 200)

    @override_settings(
        ENABLE_CODEX_CHATBOT="Pilot",
        CODEX_CHATBOT_APP_SERVER_ENABLED=False,
    )
    def test_pilot_cannot_resolve_minesite_outside_governed_scope(self):
        CodexChatbotPilot.objects.create(user=self.pilot)
        PlatformUser.objects.create(
            azure_ad_id="pilot-scope",
            user_principal_name="pilot@example.test",
            display_name="Pilot",
            django_user=self.pilot,
            business_performance_scope={"minesites": ["Fekola"]},
        )
        sync = MappingSynchronizationRun.objects.create(status="Completed")
        EquipmentFleetAnalysis.objects.create(
            synchronization_run=sync,
            source_record_id="SECRET-1",
            semantic_model_id="fleet-model",
            equipment_id="SECRET-EQ",
            site="Restricted Mine",
            normalized_site="restricted mine",
            serial_number="SECRET-SN",
            source_hash="secret-hash",
            active=True,
            source_last_seen_at=timezone.now(),
        )
        self.client.force_login(self.pilot)

        response = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Fleet du site Restricted Mine"}),
            content_type="application/json",
        )

        payload = response.json()
        self.assertEqual(payload["message"]["answer_status"], "NEEDS_CLARIFICATION")
        self.assertNotIn("Restricted Mine", payload["message"]["content"])
        self.assertEqual(CodexEvidence.objects.count(), 0)

    @override_settings(
        ENABLE_CODEX_CHATBOT="Pilot",
        CODEX_CHATBOT_APP_SERVER_ENABLED=False,
    )
    def test_pilot_without_financial_permission_cannot_read_revenue(self):
        CodexChatbotPilot.objects.create(user=self.pilot)
        self.client.force_login(self.pilot)

        response = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Quel est le Revenue Parts YTD ?"}),
            content_type="application/json",
        )

        payload = response.json()
        self.assertEqual(payload["message"]["answer_status"], "ACCESS_RESTRICTED")
        self.assertEqual(CodexEvidence.objects.count(), 0)

    @override_settings(
        ENABLE_CODEX_CHATBOT="Pilot",
        ENABLE_BUSINESS_REVIEW="Production",
        ENABLE_BUSINESS_COMMAND_CENTER="Production",
        CODEX_CHATBOT_APP_SERVER_ENABLED=False,
    )
    def test_pilot_with_command_center_ai_permissions_can_read_scoped_revenue(self):
        CodexChatbotPilot.objects.create(user=self.pilot)
        permissions = Permission.objects.filter(codename__in={
            "view_business_review",
            "view_business_review_financials",
            "view_business_command_center",
            "view_business_command_center_ai",
            "view_business_line_revenue",
        })
        self.pilot.user_permissions.add(*permissions)
        run = MappingSynchronizationRun.objects.create(status="Completed", completed_at=timezone.now())
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run,
            source_record_id="PILOT-PARTS",
            source_account_code="PILOT-ACCOUNT",
            source_account_name="Pilot Mining",
            business_date=date(2026, 9, 11),
            period_year=2026,
            division="MI",
            lob="PARTS",
            source_lob="PARTS",
            revenue_eur=Decimal("125.00"),
            source_hash="pilot-parts",
            active=True,
            source_last_seen_at=timezone.now(),
        )
        self.client.force_login(self.pilot)

        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Quel est le Revenue Parts YTD ?"}),
            content_type="application/json",
        ).json()

        self.assertEqual(payload["message"]["answer_status"], "ANSWERABLE")
        self.assertEqual(payload["evidence"][0]["value"]["hero"]["revenue"], 125.0)
        self.assertNotIn("top_customers", payload["evidence"][0]["value"])


@override_settings(
    ENABLE_CODEX_CHATBOT="Admin Only",
    CODEX_CHATBOT_APP_SERVER_ENABLED=False,
)
class CodexChatbotVerticalPathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("codex-owner", password="test", is_superuser=True)
        self.other = User.objects.create_user("other", password="test", is_superuser=True)
        run = MappingSynchronizationRun.objects.create(
            source="Customer Fleet & Revenue Planning Model",
            status="Completed",
            completed_at=timezone.now(),
        )
        for index, model in enumerate(("777G", "785D"), start=1):
            EquipmentFleetAnalysis.objects.create(
                synchronization_run=run,
                source_record_id=f"FEK-{index}",
                semantic_model_id="fleet-model",
                equipment_id=f"EQ-{index}",
                site="Fekola",
                normalized_site="fekola",
                model=model,
                serial_number=f"FEK-SN-{index}",
                equipment_family="OFF-HIGHWAY TRUCK",
                brand="CAT",
                source_hash=f"hash-{index}",
                active=True,
                source_last_seen_at=timezone.now(),
            )
        EquipmentFleetAnalysis.objects.create(
            synchronization_run=run,
            source_record_id="SIG-1",
            semantic_model_id="fleet-model",
            equipment_id="SIG-EQ-1",
            site="Siguiri",
            normalized_site="siguiri",
            model="777",
            serial_number="SIG-SN-1",
            equipment_family="OFF-HIGHWAY TRUCK",
            brand="CAT",
            source_hash="hash-siguiri",
            active=True,
            source_last_seen_at=timezone.now(),
        )
        for source_id, business_date, lob, amount in (
            ("REV-2026-P", date(2026, 9, 11), "PARTS", "100.00"),
            ("REV-2026-M", date(2026, 9, 11), "PRIME", "200.00"),
            ("REV-2025-P", date(2025, 9, 11), "PARTS", "80.00"),
            ("REV-2025-M", date(2025, 9, 11), "PRIME", "100.00"),
        ):
            RevenueSourceSnapshot.objects.create(
                synchronization_run=run,
                source_record_id=source_id,
                source_account_code="TEST-ACCOUNT",
                source_account_name="Test Mining",
                business_date=business_date,
                period_year=business_date.year,
                division="MI",
                lob=lob,
                source_lob=lob,
                revenue_eur=Decimal(amount),
                source_hash=source_id,
                active=True,
                source_last_seen_at=timezone.now(),
            )
        MappingPublication.objects.create(
            version=1,
            status="Published",
            mapping_count=1,
            account_count=1,
            snapshot_json={
                "accounts": [{
                    "account_id": "canonical-test",
                    "account_code": "TEST",
                    "account_name": "Test Mining",
                    "customer_country_group_id": "group-fekola",
                    "customer_country_group_name": "Fekola",
                    "business_country": "Mali",
                    "key_account_id": "key-b2gold",
                    "key_account_name": "B2GOLD",
                    "source_account_codes": ["TEST-ACCOUNT"],
                }],
            },
            published_by=self.user,
            published_at=timezone.now(),
        )
        self.client.force_login(self.user)

    def test_question_uses_real_fleet_tool_and_persists_proof(self):
        response = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Combien d'équipements sont sur Fekola ?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("2 équipements distincts", payload["message"]["content"])
        self.assertEqual(payload["message"]["answer_status"], "ANSWERABLE")
        self.assertEqual(CodexConversation.objects.count(), 1)
        self.assertEqual(CodexMessage.objects.count(), 2)
        self.assertEqual(CodexRun.objects.get().tool_code, "fleet_inventory_by_site")
        evidence = CodexEvidence.objects.get()
        self.assertEqual(evidence.value_json["source_table"], "EquipmentList_MiningProd / bm_equipment_fleet_analysis")
        self.assertEqual(evidence.value_json["equipment_count"], 2)
        self.assertEqual(payload["runtime"]["mode"], "governed_tools")

    def test_refresh_and_reopen_returns_persisted_messages(self):
        first = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Fleet Fekola"}),
            content_type="application/json",
        ).json()
        conversation_id = first["conversation_id"]

        reopened = self.client.get(reverse("codex_chatbot:conversation", args=[conversation_id]))
        api = self.client.get(reverse("codex_chatbot:conversation-api", args=[conversation_id]))

        self.assertContains(reopened, "Fekola compte 2 équipements distincts")
        self.assertEqual(len(api.json()["conversation"]["messages"]), 2)

    def test_conversation_cannot_be_read_by_another_user(self):
        conversation = CodexConversation.objects.create(owner=self.user)
        self.client.force_login(self.other)

        response = self.client.get(reverse("codex_chatbot:conversation-api", args=[conversation.id]))

        self.assertEqual(response.status_code, 404)

    def test_missing_site_requests_clarification_without_evidence(self):
        response = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Combien d'équipements avons-nous ?"}),
            content_type="application/json",
        )

        payload = response.json()
        self.assertEqual(payload["message"]["answer_status"], "NEEDS_CLARIFICATION")
        self.assertEqual(CodexEvidence.objects.count(), 0)

    def test_legacy_ai_route_is_unchanged(self):
        self.assertEqual(reverse("ai-home"), "/ai/")

    def test_async_submission_is_immediate_and_idempotent(self):
        request_id = str(uuid.uuid4())
        payload = {"question": "Fleet Fekola", "request_id": request_id}

        first = self.client.post(
            reverse("codex_chatbot:submit-run"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        second = self.client.post(
            reverse("codex_chatbot:submit-run"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 202)
        self.assertTrue(first.json()["created"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(first.json()["run"]["status"], "QUEUED")
        self.assertEqual(CodexRun.objects.count(), 1)
        self.assertEqual(CodexMessage.objects.filter(role="USER").count(), 1)

    def test_worker_processes_queued_run_and_status_returns_result(self):
        submitted = self.client.post(
            reverse("codex_chatbot:submit-run"),
            data=json.dumps({"question": "Fleet Fekola", "request_id": str(uuid.uuid4())}),
            content_type="application/json",
        ).json()

        processed = process_next_run()
        status = self.client.get(
            reverse("codex_chatbot:run-status", args=[submitted["run"]["id"]])
        ).json()["run"]

        self.assertIsNotNone(processed)
        self.assertTrue(status["terminal"])
        self.assertEqual(status["status"], "SUCCEEDED")
        self.assertEqual(status["progress_percent"], 100)
        self.assertIn("2 équipements distincts", status["message"]["content"])
        self.assertEqual(status["evidence_count"], 1)

    def test_running_run_exposes_verified_provisional_answer(self):
        conversation = CodexConversation.objects.create(owner=self.user)
        run = CodexRun.objects.create(
            conversation=conversation,
            user=self.user,
            question="Fleet Fekola",
            status="RUNNING",
        )
        CodexEvidence.objects.create(
            run=run,
            source_type="DATABASE_TABLE",
            source_record_id="Fekola",
            label="Governed analysis: Fekola",
            value_json={
                "kind": "site_inventory",
                "site": "Fekola",
                "equipment_count": 2,
                "serial_count": 2,
                "models": [],
            },
        )

        payload = run_payload(run)

        self.assertEqual(payload["provisional_message"]["answer_status"], "VERIFIED_FACTS")
        self.assertIn("2 équipements distincts", payload["provisional_message"]["content"])
        self.assertEqual(payload["result"]["site"], "Fekola")

    def test_queued_run_can_be_cancelled(self):
        submitted = self.client.post(
            reverse("codex_chatbot:submit-run"),
            data=json.dumps({"question": "Fleet Fekola", "request_id": str(uuid.uuid4())}),
            content_type="application/json",
        ).json()
        response = self.client.post(
            reverse("codex_chatbot:cancel-run", args=[submitted["run"]["id"]])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run"]["status"], "CANCELLED")
        self.assertIsNone(process_next_run())

    def test_async_run_status_is_private_to_owner(self):
        submitted = self.client.post(
            reverse("codex_chatbot:submit-run"),
            data=json.dumps({"question": "Fleet Fekola", "request_id": str(uuid.uuid4())}),
            content_type="application/json",
        ).json()
        self.client.force_login(self.other)

        response = self.client.get(
            reverse("codex_chatbot:run-status", args=[submitted["run"]["id"]])
        )

        self.assertEqual(response.status_code, 404)

    def test_serial_lookup_returns_governed_machine_detail(self):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Numéro de série FEK-SN-1"}),
            content_type="application/json",
        ).json()

        result = payload["evidence"][0]["value"]
        self.assertEqual(result["kind"], "machine_detail")
        self.assertEqual(result["machine"]["model"], "777G")
        self.assertEqual(result["machine"]["equipment_family"], "OFF-HIGHWAY TRUCK")
        self.assertEqual(CodexRun.objects.get().tool_code, "fleet_machine_by_serial")

    def test_fleet_coverage_distinguishes_available_fields(self):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Quelle est la couverture qualité des données Fleet ?"}),
            content_type="application/json",
        ).json()

        result = payload["evidence"][0]["value"]
        self.assertEqual(result["kind"], "fleet_coverage")
        self.assertEqual(result["coverage_percent"]["serial_number"], 100.0)
        self.assertEqual(result["coverage_percent"]["equipment_family"], 100.0)

    @patch("codex_chatbot.tools.performance.HomepageAvailabilityService")
    def test_availability_question_uses_governed_performance_service(self, service_class):
        service = service_class.return_value
        service.metric = {"powerbi_measure_name": "[Avail Per Equip]", "metric_label": "Availability Per Equip"}
        service.request_from_params.side_effect = lambda params: params
        service.get.return_value = {
            "context": {
                "metric_code": "availability",
                "metric_label": "Physical Availability",
                "period_code": "ytd",
                "period_label": "Year to Date",
                "start_date": "2026-01-01",
                "end_date": "2026-09-30",
                "breakdown": "overall",
                "filters": {"model": "777", "minesite": "Siguiri"},
            },
            "availability": {
                "raw_value": 0.8453,
                "formatted_value": "84.53%",
                "comparison": {"label": "vs same period last year", "delta_points": 2.16},
            },
            "summary": {"equipment_count": 35, "minesite_count": 19, "downtime_hours": 39511.3},
            "trend": [],
            "breakdown": [],
            "data_quality": {"latest_available_date": "2026-09-30", "is_stale": False},
            "warnings": [],
            "meta": {"cached": False},
        }

        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Donne-moi la disponibilité des 777 de Siguiri en 2026"}),
            content_type="application/json",
        ).json()

        result = payload["evidence"][0]["value"]
        self.assertEqual(result["kind"], "availability_summary")
        self.assertEqual(result["context"]["filters"], {"model": "777", "minesite": "Siguiri"})
        self.assertEqual(result["context"]["period_code"], "ytd")
        self.assertEqual(result["availability"]["formatted_value"], "84.53%")
        self.assertEqual(result["source_measure"], "[Avail Per Equip]")
        self.assertFalse(result["presentation"]["show_trend"])
        self.assertFalse(result["presentation"]["show_breakdown"])
        self.assertIn("84.53%", payload["message"]["content"])
        self.assertIn("modèle 777 à Siguiri", payload["message"]["content"])
        self.assertEqual(CodexRun.objects.get().tool_code, "fleet_physical_availability")
        service.request_from_params.assert_called_once_with({
            "period": "ytd", "breakdown": "overall", "model": "777", "minesite": "Siguiri",
        })
        service.get.assert_called_once()

    @patch("codex_chatbot.tools.performance.HomepageAvailabilityService")
    def test_validated_minesite_alias_resolves_to_canonical_site(self, service_class):
        site = MineSite.objects.create(
            minesite_code="SITE-SANGAREDI",
            canonical_minesite_name="Sangaredi/CBG",
            normalized_minesite_name="sangaredi cbg",
            active=True,
        )
        MineSiteAlias.objects.create(
            minesite=site,
            alias="Mine de Sangaredi",
            source_system="Business Mapping Studio",
            validation_status="Validated",
            active=True,
        )
        service = service_class.return_value
        service.metric = {"powerbi_measure_name": "[Avail Per Equip]"}
        service.request_from_params.side_effect = lambda params: params
        service.get.return_value = {
            "context": {"period_code": "ytd", "period_label": "Year to Date", "filters": {"minesite": "Sangaredi/CBG"}},
            "availability": {"raw_value": 0.91, "formatted_value": "91.00%"},
            "summary": {},
        }

        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Disponibilité de la mine de Sangaredi YTD"}),
            content_type="application/json",
        ).json()

        result = payload["evidence"][0]["value"]
        self.assertEqual(result["minesite_resolution"]["canonical_name"], "Sangaredi/CBG")
        self.assertEqual(result["minesite_resolution"]["match_method"], "validated_alias")
        service.request_from_params.assert_called_once_with({
            "period": "ytd", "breakdown": "overall", "minesite": "Sangaredi/CBG",
        })

    @patch("codex_chatbot.tools.performance.HomepageAvailabilityService")
    def test_ambiguous_minesite_alias_requires_clarification(self, service_class):
        for suffix in ("Corica", "KGM"):
            site = MineSite.objects.create(
                minesite_code=f"SITE-KOUROUSSA-{suffix.upper()}",
                canonical_minesite_name=f"Kouroussa/{suffix}",
                normalized_minesite_name=f"kouroussa {suffix.casefold()}",
                active=True,
            )
            MineSiteAlias.objects.create(
                minesite=site,
                alias="Kouroussa",
                source_system="Business Mapping Studio",
                validation_status="Validated",
                active=True,
            )

        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Disponibilité de Kouroussa YTD"}),
            content_type="application/json",
        ).json()

        self.assertEqual(payload["message"]["answer_status"], "NEEDS_CLARIFICATION")
        self.assertIn("Kouroussa/Corica", payload["message"]["content"])
        self.assertIn("Kouroussa/KGM", payload["message"]["content"])
        service_class.assert_not_called()

    def test_fleet_export_uses_persisted_evidence_and_is_private(self):
        with tempfile.TemporaryDirectory() as artifact_root, self.settings(
            CODEX_CHATBOT_ARTIFACT_ROOT=artifact_root
        ):
            submitted = self.client.post(
                reverse("codex_chatbot:submit-run"),
                data=json.dumps({"question": "Fleet Fekola", "request_id": str(uuid.uuid4())}),
                content_type="application/json",
            ).json()
            process_next_run()
            exported = self.client.post(
                reverse("codex_chatbot:create-export", args=[submitted["run"]["id"]])
            )
            artifact = exported.json()["artifact"]

            self.assertEqual(exported.status_code, 200)
            self.assertEqual(artifact["row_count"], 2)
            self.client.force_login(self.other)
            denied = self.client.get(artifact["download_url"])
            self.assertEqual(denied.status_code, 404)

    def test_revenue_uses_business_command_center_period_and_lob(self):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Quel est le Revenue Parts YTD ?"}),
            content_type="application/json",
        ).json()

        result = payload["evidence"][0]["value"]
        self.assertEqual(result["kind"], "revenue_summary")
        self.assertEqual(result["context"]["business_line"], "parts")
        self.assertEqual(result["context"]["start_date"], "2026-01-01")
        self.assertEqual(result["hero"]["revenue"], 100.0)
        self.assertEqual(result["hero"]["comparison_revenue"], 80.0)
        self.assertEqual(result["reconciliation"]["status"], "RECONCILED")
        self.assertEqual(CodexRun.objects.get().tool_code, "business_revenue_summary")

    def test_revenue_resolves_published_customer_country_group(self):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Quel est le Revenue Parts de Fekola en YTD ?"}),
            content_type="application/json",
        ).json()

        result = payload["evidence"][0]["value"]
        self.assertEqual(result["request"]["resolved_filters"], {"customer_group_ids": "group-fekola"})
        self.assertEqual(result["hero"]["revenue"], 100.0)

    def test_spoken_french_parts_sales_resolve_customer_year_and_amount(self):
        publication = MappingPublication.objects.get(status="Published")
        publication.snapshot_json["accounts"][0]["customer_country_group_name"] = "SNIM"
        publication.save(update_fields=["snapshot_json"])
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Dis moi combien on a vendu en pièce à la SNIM en 2026"}),
            content_type="application/json",
        ).json()

        result = payload["evidence"][0]["value"]
        self.assertEqual(payload["message"]["answer_status"], "ANSWERABLE")
        self.assertEqual(result["request"]["resolved_filters"], {"customer_group_ids": "group-fekola"})
        self.assertEqual(result["context"]["business_line"], "parts")
        self.assertEqual(result["context"]["start_date"], "2026-01-01")
        self.assertEqual(result["hero"]["revenue"], 100.0)
        self.assertIn("EUR", payload["message"]["content"])

    def test_english_parts_sales_use_same_governed_measure(self):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "What were our parts sales to Fekola in 2025?"}),
            content_type="application/json",
        ).json()
        result = payload["evidence"][0]["value"]
        self.assertEqual(result["context"]["business_line"], "parts")
        self.assertEqual(result["context"]["start_date"], "2025-01-01")
        self.assertEqual(result["context"]["end_date"], "2025-12-31")
        self.assertEqual(result["hero"]["revenue"], 80.0)

    def test_ambiguous_revenue_group_does_not_fall_back_to_group_total(self):
        publication = MappingPublication.objects.get(status="Published")
        publication.snapshot_json["accounts"][0]["customer_country_group_name"] = "B2GOLD Fekola"
        publication.snapshot_json["accounts"].append({
            "account_id": "canonical-fekola-sa",
            "account_code": "FEKOLA-SA",
            "account_name": "Fekola SA",
            "customer_country_group_id": "group-fekola-sa",
            "customer_country_group_name": "Fekola SA",
            "business_country": "Mali",
            "source_account_codes": ["OTHER-ACCOUNT"],
        })
        publication.save(update_fields=["snapshot_json"])

        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Quel est le CA de Fekola YTD ?"}),
            content_type="application/json",
        ).json()

        self.assertEqual(payload["message"]["answer_status"], "NEEDS_CLARIFICATION")
        self.assertEqual(CodexEvidence.objects.get().value_json["kind"], "revenue_scope_ambiguous")
        self.assertIn("Fekola SA", payload["message"]["content"])

    def _published_fekola_groups(self, count=13, same_key=True):
        publication = MappingPublication.objects.get(status="Published")
        base = publication.snapshot_json["accounts"][0]
        publication.snapshot_json["accounts"] = [
            {**base, "account_id":f"account-{i}", "account_name":"FEKOLA SA",
             "customer_country_group_id":f"group-{i}",
             "customer_country_group_name":f"FEKOLA SA · MININGACCOUNTS:{i+1}-12515",
             "key_account_id":"key-b2gold" if same_key else f"key-{i}"}
            for i in range(count)
        ]
        publication.save(update_fields=["snapshot_json"])

    def test_fekola_technical_groups_are_selected_completely_without_double_counting(self):
        self._published_fekola_groups()
        payload = self.client.post(reverse("codex_chatbot:ask"),
            data=json.dumps({"question":"What is the Revenue Parts YTD for Fekola?"}),
            content_type="application/json").json()
        evidence = payload["evidence"][0]["value"]
        self.assertEqual(payload["message"]["answer_status"], "ANSWERABLE")
        self.assertEqual(set(evidence["request"]["resolved_filters"]["customer_group_ids"].split(",")),
                         {f"group-{i}" for i in range(13)})
        self.assertEqual(evidence["hero"]["revenue"], 100.0)
        self.assertEqual(evidence["request"]["resolved_scope"]["customer_group_ids"]["name"], "FEKOLA SA")
        self.assertIn("13 published customer groups", payload["message"]["content"])
        self.assertTrue(payload["message"]["content"].startswith("Parts revenue"))

    def test_same_customer_label_under_different_keys_remains_ambiguous_in_english(self):
        self._published_fekola_groups(count=2, same_key=False)
        payload = self.client.post(reverse("codex_chatbot:ask"),
            data=json.dumps({"question":"What is the Revenue Parts YTD for Fekola?"}),
            content_type="application/json").json()
        self.assertEqual(payload["message"]["answer_status"], "NEEDS_CLARIFICATION")
        self.assertTrue(payload["message"]["content"].startswith("Several published customers"))

    def test_explicit_technical_customer_reference_keeps_its_single_group(self):
        self._published_fekola_groups(count=2)
        payload = self.client.post(reverse("codex_chatbot:ask"),
            data=json.dumps({"question":"Revenue Parts YTD for FEKOLA SA · MININGACCOUNTS:2-12515"}),
            content_type="application/json").json()
        self.assertEqual(payload["evidence"][0]["value"]["request"]["resolved_filters"]["customer_group_ids"], "group-1")

    def test_english_question_words_do_not_match_unrelated_customers(self):
        self._published_fekola_groups(count=2)
        publication = MappingPublication.objects.get(status="Published")
        for i, name in enumerate(["THE DEVELOPMENT INITIATIVE LTD", "Z FOR MINING"]):
            publication.snapshot_json["accounts"].append({
                **publication.snapshot_json["accounts"][0], "account_id":f"unrelated-{i}",
                "customer_country_group_id":f"unrelated-group-{i}", "customer_country_group_name":name,
                "account_name":name, "source_account_codes":[f"UNRELATED-{i}"],
            })
        publication.save(update_fields=["snapshot_json"])
        payload = self.client.post(reverse("codex_chatbot:ask"),
            data=json.dumps({"question":"What is the Revenue Parts YTD for Fekola?"}),
            content_type="application/json").json()
        self.assertEqual(payload["message"]["answer_status"], "ANSWERABLE")
        self.assertEqual(payload["evidence"][0]["value"]["request"]["resolved_filters"]["customer_group_ids"], "group-0,group-1")

    def test_customer_family_only_contains_authorized_published_rows(self):
        self._published_fekola_groups(count=3)
        with patch("reports.business_command_center_service.filter_published_rows", side_effect=lambda rows,user:rows[:2]):
            payload = self.client.post(reverse("codex_chatbot:ask"),
                data=json.dumps({"question":"What is the Revenue Parts YTD for Fekola?"}),
                content_type="application/json").json()
        self.assertEqual(payload["evidence"][0]["value"]["request"]["resolved_filters"]["customer_group_ids"], "group-0,group-1")

    def test_revenue_export_uses_persisted_business_line_values(self):
        with tempfile.TemporaryDirectory() as artifact_root, self.settings(
            CODEX_CHATBOT_ARTIFACT_ROOT=artifact_root
        ):
            payload = self.client.post(
                reverse("codex_chatbot:ask"),
                data=json.dumps({"question": "Revenue Mining YTD"}),
                content_type="application/json",
            ).json()
            exported = self.client.post(
                reverse("codex_chatbot:create-export", args=[payload["run_id"]])
            ).json()["artifact"]

            self.assertEqual(exported["row_count"], 5)

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True)
    @patch("codex_chatbot.orchestrator.run_grounded_turn")
    @patch("codex_chatbot.orchestrator.shutil.which", return_value="codex")
    def test_general_question_uses_independent_codex_conversation(self, _which, run_turn):
        run_turn.return_value = CodexTurnResult(
            "general-thread-1",
            "general-turn-1",
            "Bonjour ! Nous pouvons discuter de nombreux sujets.",
        )

        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Bonjour, est-ce qu'on peut discuter ?"}),
            content_type="application/json",
        ).json()

        self.assertEqual(payload["message"]["answer_status"], "ANSWERABLE")
        self.assertEqual(payload["runtime"]["mode"], "codex_app_server")
        self.assertEqual(CodexRun.objects.get().tool_code, "general_codex_conversation")
        self.assertEqual(CodexEvidence.objects.count(), 0)
        self.assertIn("general model knowledge", run_turn.call_args.kwargs["base_instructions"])
        self.assertEqual(run_turn.call_args.kwargs["timeout_seconds"], 120.0)

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True)
    @patch("codex_chatbot.orchestrator.run_grounded_turn")
    def test_unconnected_business_data_question_is_not_invented_by_general_mode(self, run_turn):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Combien de pièces ont été vendues à B2GOLD ?"}),
            content_type="application/json",
        ).json()

        self.assertEqual(payload["message"]["answer_status"], "NEEDS_CLARIFICATION")
        self.assertIn("pas encore raccordées", payload["message"]["content"])
        run_turn.assert_not_called()

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True, CODEX_CHATBOT_WEB_SEARCH_ENABLED=True)
    @patch("codex_chatbot.orchestrator.run_grounded_turn")
    @patch("codex_chatbot.orchestrator.shutil.which", return_value="codex")
    def test_web_search_is_audited_and_excludes_business_history(self, _which, run_turn):
        conversation = CodexConversation.objects.create(owner=self.user, native_thread_id="internal-thread")
        internal = CodexMessage.objects.create(conversation=conversation, role="ASSISTANT", content="PRIVATE_REVENUE_12345")
        CodexRun.objects.create(conversation=conversation, user=self.user, question="PRIVATE_CUSTOMER_QUERY",
                               tool_code="business_revenue_summary", result_message=internal)
        general = CodexMessage.objects.create(conversation=conversation, role="ASSISTANT", content="Gorée is an island.")
        CodexRun.objects.create(conversation=conversation, user=self.user, question="Tell me about Gorée",
                               tool_code="general_codex_conversation", result_message=general)
        run_turn.return_value = CodexTurnResult("public-thread", "public-turn",
            "See [UNESCO](https://whc.unesco.org/en/list/26/).", web_search_count=2)
        payload = self.client.post(reverse("codex_chatbot:ask"),
            data=json.dumps({"question":"Search the Internet for UNESCO's page about that island", "conversation_id":str(conversation.id)}),
            content_type="application/json").json()
        call = run_turn.call_args.kwargs
        self.assertTrue(call["web_search_enabled"])
        self.assertEqual(call["native_thread_id"], "")
        self.assertNotIn("PRIVATE_", call["prompt"])
        self.assertIn("Gorée", call["prompt"])
        self.assertEqual(payload["message"]["answer_status"], "ANSWERABLE")
        self.assertEqual(CodexEvidence.objects.get().value_json, {"kind":"web_sources", "search_count":2})

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True, CODEX_CHATBOT_WEB_SEARCH_ENABLED=True)
    @patch("codex_chatbot.orchestrator.run_grounded_turn")
    @patch("codex_chatbot.orchestrator.shutil.which", return_value="codex")
    def test_revenue_does_not_enable_web_even_when_general_web_is_enabled(self, _which, run_turn):
        run_turn.return_value = CodexTurnResult("business-thread", "business-turn", "Verified revenue.")
        self.client.post(reverse("codex_chatbot:ask"),
            data=json.dumps({"question":"Revenue Parts YTD"}), content_type="application/json")
        self.assertFalse(run_turn.call_args.kwargs.get("web_search_enabled", False))

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True)
    @patch("codex_chatbot.orchestrator.shutil.which", return_value="codex")
    @patch("codex_chatbot.orchestrator.run_grounded_turn")
    def test_running_cancel_request_interrupts_without_assistant_message(self, run_turn, _which):
        def interrupt(*args, **kwargs):
            run = CodexRun.objects.get(status="RUNNING")
            run.status = "CANCEL_REQUESTED"
            run.save(update_fields=["status"])
            raise AppServerTurnInterrupted("interrupted")

        run_turn.side_effect = interrupt
        self.client.post(
            reverse("codex_chatbot:submit-run"),
            data=json.dumps({"question": "Fleet Fekola", "request_id": str(uuid.uuid4())}),
            content_type="application/json",
        )

        process_next_run()
        run = CodexRun.objects.get()

        self.assertEqual(run.status, "CANCELLED")
        self.assertIsNone(run.result_message)
        self.assertEqual(CodexMessage.objects.filter(role="ASSISTANT").count(), 0)

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True)
    @patch("codex_chatbot.orchestrator.shutil.which", return_value="codex")
    @patch(
        "codex_chatbot.orchestrator.run_grounded_turn",
        side_effect=AppServerTurnTimedOut("timeout"),
    )
    def test_timeout_is_explicit_and_preserves_verified_answer(self, _run_turn, _which):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Fleet Fekola"}),
            content_type="application/json",
        ).json()

        self.assertEqual(payload["runtime"]["status"], "TIMED_OUT")
        self.assertIn("2 équipements distincts", payload["message"]["content"])
        self.assertEqual(CodexRun.objects.get().error_code, "CODEX_RUNTIME_TIMEOUT")

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True)
    @patch("codex_chatbot.orchestrator.run_grounded_turn")
    @patch("codex_chatbot.orchestrator.shutil.which", return_value="codex")
    def test_codex_runtime_thread_is_persisted_and_resumed(self, _which, run_turn):
        run_turn.side_effect = [
            CodexTurnResult("thread-360", "turn-1", "Réponse Codex initiale."),
            CodexTurnResult("thread-360", "turn-2", "Réponse Codex reprise."),
        ]
        first = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Fleet Fekola"}),
            content_type="application/json",
        ).json()
        second = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({
                "question": "Et quels sont les modèles sur Fekola ?",
                "conversation_id": first["conversation_id"],
            }),
            content_type="application/json",
        ).json()

        self.assertEqual(first["runtime"]["mode"], "codex_app_server")
        self.assertTrue(second["runtime"]["native_thread_active"])
        self.assertEqual(CodexConversation.objects.get().native_thread_id, "thread-360")
        self.assertEqual(run_turn.call_args_list[1].kwargs["native_thread_id"], "thread-360")
        self.assertCountEqual(
            CodexRun.objects.values_list("native_turn_id", flat=True),
            ["turn-1", "turn-2"],
        )

    @override_settings(CODEX_CHATBOT_APP_SERVER_ENABLED=True)
    @patch("codex_chatbot.orchestrator.run_grounded_turn", side_effect=AppServerTurnError("timeout"))
    @patch("codex_chatbot.orchestrator.shutil.which", return_value="codex")
    def test_codex_runtime_failure_keeps_verified_fleet_answer(self, _which, _run_turn):
        payload = self.client.post(
            reverse("codex_chatbot:ask"),
            data=json.dumps({"question": "Fleet Fekola"}),
            content_type="application/json",
        ).json()

        self.assertEqual(payload["runtime"]["mode"], "governed_fallback")
        self.assertEqual(payload["message"]["answer_status"], "PARTIALLY_ANSWERABLE")
        self.assertIn("2 équipements distincts", payload["message"]["content"])
        self.assertEqual(CodexRun.objects.get().error_code, "CODEX_RUNTIME_UNAVAILABLE")
