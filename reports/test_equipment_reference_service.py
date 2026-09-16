from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from .equipment_reference_service import EquipmentReferenceImportService
from .machine_sales_service import MachineSalesSynchronizationService
from .models import EquipmentPrefixModelReference, EquipmentSerialReference


class EquipmentReferenceImportServiceTests(TestCase):
    def setUp(self):
        self.asset_path = Path(__file__)
        self.prefix_path = Path(__file__)
        self.serial_payloads = {
            "ABC0001": {
                "serial_number": "ABC0001", "serial_prefix": "ABC", "make": "CAT",
                "model": "6020B", "product_family": "Hydraulic Mining Shovel",
                "dealer_customer_name": "Customer A", "ownership_status": "Customer",
                "model_year": "2026", "subscription_status": "Active",
                "source_file_name": "assets.xlsx", "source_row_number": 2,
                "source_hash": "a" * 64, "active": True,
            }
        }
        self.prefix_payloads = {}
        for model, prefix, family, row_number, ambiguous in (
            ("6020", "ABC", "Hydraulic Mining Shovel", 2, True),
            ("6030", "ABC", "Hydraulic Mining Shovel", 3, True),
            ("777", "XYZ", "Off Highway Truck", 4, False),
        ):
            key = ("CAT", prefix, model, "Equipment", family)
            self.prefix_payloads[key] = {
                "brand": "CAT", "prefix": prefix, "model": model,
                "parent_product_family": "Equipment", "product_family": family,
                "equipment_type": "", "source_created_by": "Test",
                "ambiguous_prefix": ambiguous, "source_file_name": "prefixes.csv",
                "source_row_number": row_number, "source_hash": str(row_number) * 64,
                "active": True,
            }
        self.product_group_payloads = {
            "OTHER": {
                "code": "OTHER", "description": "Other", "priority": 11,
                "source_created_by": "Test", "source_file_name": "groups.csv",
                "source_row_number": 2, "source_hash": "g" * 64, "active": True,
            }
        }
        self.model_payloads = {
            "1156": {
                "source_record_id": "1156", "model": "777 WT", "normalized_model": "777WT",
                "brand": "CAT", "family": "OFF-HIGHWAY TRUCKS", "priority": 11,
                "equipment_type": "Water Trucks", "description": "", "source_status": "-1",
                "source_created_by": "Test", "product_group_code": "OTHER",
                "source_file_name": "models.csv", "source_row_number": 2,
                "source_hash": "m" * 64, "active": True,
            }
        }

    def import_references(self, include_catalog=False):
        with (
            patch.object(EquipmentReferenceImportService, "_read_serials", return_value=self.serial_payloads),
            patch.object(EquipmentReferenceImportService, "_read_prefixes", return_value=self.prefix_payloads),
            patch.object(EquipmentReferenceImportService, "_read_product_groups", return_value=self.product_group_payloads),
            patch.object(EquipmentReferenceImportService, "_read_models", return_value=self.model_payloads),
            patch("reports.equipment_reference_service._file_hash", return_value="f" * 64),
        ):
            return EquipmentReferenceImportService.import_files(
                asset_list_path=self.asset_path, prefix_csv_path=self.prefix_path,
                product_group_csv_path=self.asset_path if include_catalog else None,
                model_csv_path=self.prefix_path if include_catalog else None,
            )

    def test_import_is_audited_idempotent_and_marks_ambiguous_prefixes(self):
        first = self.import_references()
        second = self.import_references()

        serial = EquipmentSerialReference.objects.get(serial_number="ABC0001")
        self.assertEqual(serial.serial_prefix, "ABC")
        self.assertEqual(serial.model, "6020B")
        self.assertEqual(serial.make, "CAT")
        self.assertEqual(first.records_created, 4)
        self.assertEqual(second.records_unchanged, 4)
        self.assertTrue(
            EquipmentPrefixModelReference.objects.filter(prefix="ABC", ambiguous_prefix=True).exists()
        )
        self.assertFalse(
            EquipmentPrefixModelReference.objects.get(prefix="XYZ").ambiguous_prefix
        )

    def test_machine_enrichment_prefers_exact_serial_and_uses_only_safe_prefix(self):
        self.import_references()
        payloads = [
            {"serial_number": "abc-0001", "equipment_code": "", "model_name": "", "model_code": "", "equipment_family": "", "family_code": "", "brand": ""},
            {"serial_number": "XYZ9999", "equipment_code": "", "model_name": "", "model_code": "", "equipment_family": "", "family_code": "", "brand": ""},
            {"serial_number": "ABC9999", "equipment_code": "", "model_name": "", "model_code": "", "equipment_family": "", "family_code": "", "brand": ""},
        ]

        MachineSalesSynchronizationService._enrich_equipment_dimensions(payloads)

        self.assertEqual(payloads[0]["model_name"], "6020B")
        self.assertEqual(payloads[0]["family_code"], "HMS")
        self.assertEqual(payloads[1]["model_name"], "777")
        self.assertEqual(payloads[1]["family_code"], "OHT")
        self.assertEqual(payloads[2]["model_name"], "")

    def test_governed_model_catalog_overrides_generic_family_heuristic(self):
        run = self.import_references(include_catalog=True)
        payload = {
            "serial_number": "", "equipment_code": "", "model_name": "777 WT",
            "model_code": "777 WT", "equipment_family": "", "family_code": "", "brand": "CAT",
        }

        MachineSalesSynchronizationService._enrich_equipment_dimensions([payload])

        self.assertEqual(run.product_group_records_read, 1)
        self.assertEqual(run.model_records_read, 1)
        self.assertEqual(payload["family_code"], "OTHER")
        self.assertEqual(payload["equipment_family"], "OFF-HIGHWAY TRUCKS")
