import io
from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .miningprod_browser_write_service import (
    MiningProdMetaFormWriteService,
    MiningProdWritePreviewError,
    run_equipment_models_rollback_test,
    validate_miningprod_user_mapping,
)
from .models import (
    DataBrowser,
    DataBrowserWriteAuditLog,
    DataBrowserWriteMapping,
    MiningProdUserMapping,
)


class FakeUserCursor:
    def execute(self, query, params=()):
        self.params = params
        return self

    def fetchone(self):
        return (2577621, 2576414, "djimen")


class FakeUserConnection:
    def cursor(self):
        return FakeUserCursor()


@contextmanager
def fake_user_connection(_browser):
    yield FakeUserConnection()


class FakeRollbackCursor:
    def __init__(self, verification=False):
        self.verification = verification
        self.fetch_values = iter(
            [(0,), (321,), (1,), (1,)]
            if not verification
            else [(0,), (0,)]
        )

    def execute(self, query, params=()):
        return self

    def fetchone(self):
        return next(self.fetch_values)


class FakeRollbackConnection:
    def __init__(self, verification=False):
        self.cursor_instance = FakeRollbackCursor(verification=verification)
        self.rollback_called = False

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        self.rollback_called = True


class FakeRollbackConnectionFactory:
    def __init__(self):
        self.connections = []

    @contextmanager
    def __call__(self, _browser):
        connection = FakeRollbackConnection(verification=bool(self.connections))
        self.connections.append(connection)
        yield connection


class MiningProdBrowserWritePreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("sync_miningprod_browsers", apply=True, stdout=io.StringIO())
        call_command("bootstrap_miningprod_write_mappings", apply=True, stdout=io.StringIO())
        cls.user = get_user_model().objects.create_superuser(
            username="migration-admin",
            email="migration@example.com",
            password="test-password",
        )

    def test_bootstrap_is_idempotent_and_preserves_governance(self):
        mapping = DataBrowserWriteMapping.objects.get(browser__external_form_id=36)
        mapping.validation_status = "preview_validated"
        mapping.allow_create = True
        mapping.save(update_fields=["validation_status", "allow_create", "updated_at"])

        call_command("bootstrap_miningprod_write_mappings", apply=True, stdout=io.StringIO())

        mapping.refresh_from_db()
        self.assertEqual(DataBrowserWriteMapping.objects.count(), 5)
        self.assertEqual(mapping.validation_status, "preview_validated")
        self.assertTrue(mapping.allow_create)
        self.assertFalse(mapping.active)

    def test_direct_table_create_preview_never_opens_external_connection(self):
        browser = DataBrowser.objects.prefetch_related("columns").get(external_form_id=36)
        with patch(
            "reports.miningprod_browser_write_service.external_browser_connection"
        ) as external_connection:
            result = MiningProdMetaFormWriteService().preview(
                browser=browser,
                operation="create",
                values={
                    "Description": "Preview description",
                    "Status": -1,
                    "Model": "TEST-ONLY",
                    "Family": "Truck",
                },
                user=self.user,
            )

        external_connection.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["plan"]["steps"][0]["table"], "EQUIPTYPE")
        self.assertEqual(result["plan"]["steps"][1]["table"], "EQUIPTYPECMTVAL")
        self.assertIn("validated MiningProd user mapping", " ".join(result["blockers"]))
        self.assertEqual(DataBrowserWriteAuditLog.objects.count(), 1)

    def test_eventchain_create_preview_uses_curated_business_unit_and_cmt(self):
        MiningProdUserMapping.objects.create(
            user=self.user,
            external_employee_id=987,
            external_user_id=123,
            external_username="migration-admin",
            validation_status="validated",
        )
        browser = DataBrowser.objects.prefetch_related("columns").get(external_form_id=2405990)
        result = MiningProdMetaFormWriteService().preview(
            browser=browser,
            operation="create",
            values={"Country": "Mali", "MiningGroup": "Preview Group"},
            user=self.user,
        )

        self.assertEqual(result["plan"]["strategy"], "eventchain_eav")
        self.assertEqual(result["plan"]["steps"][0]["table"], "EVENTCHAIN")
        self.assertEqual(
            result["plan"]["steps"][1]["fixed_values"]["BUSINESS_UNIT_ID"],
            122756,
        )
        cmt_ids = {
            step.get("fixed_values", {}).get("EVENTCHAINCMTID")
            for step in result["plan"]["steps"]
        }
        self.assertIn(4640, cmt_ids)
        self.assertIn(4643, cmt_ids)
        self.assertFalse(result["execution_allowed"])

    def test_required_and_unknown_fields_are_rejected(self):
        browser = DataBrowser.objects.prefetch_related("columns").get(external_form_id=36)
        with self.assertRaisesMessage(
            MiningProdWritePreviewError,
            "Required fields are missing",
        ):
            MiningProdMetaFormWriteService().preview(
                browser=browser,
                operation="create",
                values={"Model": "TEST-ONLY"},
                user=self.user,
            )
        with self.assertRaisesMessage(
            MiningProdWritePreviewError,
            "Unknown browser fields",
        ):
            MiningProdMetaFormWriteService().preview(
                browser=browser,
                operation="create",
                values={
                    "Description": "Preview",
                    "Status": -1,
                    "Model": "TEST-ONLY",
                    "DangerousColumn": "blocked",
                },
                user=self.user,
            )

    def test_admin_preview_endpoint_returns_audited_plan(self):
        self.client.force_login(self.user)
        browser = DataBrowser.objects.get(external_form_id=2406017)
        response = self.client.post(
            reverse("data-browser-write-preview-api", args=[browser.id]),
            data={
                "operation": "create",
                "values": {
                    "Product Group Code": "TEST",
                    "Product Group Description": "Preview only",
                },
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["preview"]
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["execution_allowed"])
        self.assertEqual(payload["notice"], "Preview only. No statement was executed against MiningProd.")

    def test_edit_and_delete_build_plans_from_read_only_snapshot(self):
        browser = DataBrowser.objects.prefetch_related("columns").get(external_form_id=2406031)
        service = MiningProdMetaFormWriteService()
        with patch.object(service, "_fetch_record", return_value={"2436190": 77, "2436197": "OLD"}):
            edit = service.preview(
                browser=browser,
                operation="edit",
                record_id=77,
                values={"Customer Code": "NEW"},
                user=self.user,
            )
            delete = service.preview(
                browser=browser,
                operation="delete",
                record_id=77,
                values={},
                user=self.user,
            )

        self.assertEqual(edit["plan"]["steps"][0]["action"], "upsert_or_delete")
        self.assertEqual(delete["plan"]["steps"][-1]["table"], "EVENTCHAIN")
        self.assertEqual(DataBrowserWriteAuditLog.objects.count(), 2)

    def test_user_mapping_keeps_employee_primary_key_and_audit_user_id_separate(self):
        with patch(
            "reports.miningprod_browser_write_service.external_browser_connection",
            fake_user_connection,
        ):
            result = validate_miningprod_user_mapping(
                user=self.user,
                employee_id=2577621,
                username="djimen",
                validated_by=self.user,
            )

        self.assertEqual(result["employee_id"], 2577621)
        self.assertEqual(result["audit_user_id"], 2576414)
        self.assertEqual(result["username"], "djimen")
        self.assertEqual(result["validation_status"], "validated")

    def test_rollback_probe_verifies_transaction_and_persistence(self):
        MiningProdUserMapping.objects.create(
            user=self.user,
            external_employee_id=2577621,
            external_user_id=2576414,
            external_username="djimen",
            validation_status="validated",
        )
        factory = FakeRollbackConnectionFactory()
        with patch(
            "reports.miningprod_browser_write_service.external_browser_connection",
            factory,
        ):
            result = run_equipment_models_rollback_test(
                user=self.user,
                confirmation="RUN ROLLBACK TEST",
            )

        self.assertTrue(factory.connections[0].rollback_called)
        self.assertTrue(result["transaction_insert_verified"])
        self.assertTrue(result["rollback_verified"])
        self.assertEqual(result["persisted_root_rows"], 0)
        self.assertEqual(result["persisted_cmt_rows"], 0)
        audit = DataBrowserWriteAuditLog.objects.get(operation="rollback_test")
        self.assertEqual(audit.status, "validated")
