import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class InspectPowerBICatalogTests(SimpleTestCase):
    @patch("reports.management.commands.inspect_powerbi_catalog.get_dataset_schema_catalog")
    @patch("reports.management.commands.inspect_powerbi_catalog.env_value")
    def test_schema_mode_filters_sanitized_object_names(self, env, schema):
        env.side_effect = lambda name, *args: {
            "POWERBI_WORKSPACE_ID": "workspace-id",
            "POWERBI_WORKSPACE_NAME": "workspace-name",
        }[name]
        schema.return_value = {
            "tables": [{"Name": "GlobalCA"}],
            "columns": [{"table": "GlobalCA", "name": "Customer"}],
            "measures": [{"table": "Sales", "name": "Revenue"}],
        }
        output = StringIO()

        call_command(
            "inspect_powerbi_catalog", "--schema", "Mine Logistics Report v2",
            "--query", "globalca", "--json", stdout=output,
        )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["count"], 2)
        self.assertEqual({item["type"] for item in payload["results"]}, {"table", "column"})

    @patch("reports.management.commands.inspect_powerbi_catalog.list_workspace_datasets")
    @patch("reports.management.commands.inspect_powerbi_catalog.list_workspace_reports")
    @patch("reports.management.commands.inspect_powerbi_catalog.get_access_token", return_value="secret-token")
    @patch("reports.management.commands.inspect_powerbi_catalog.env_value", return_value="workspace-id")
    def test_filtered_json_contains_only_sanitized_metadata(
        self, _env, _token, reports, datasets,
    ):
        reports.return_value = [SimpleNamespace(
            id="report-id", name="Mine Logistics V2", dataset_id="dataset-id",
        )]
        datasets.return_value = [
            {"id": "dataset-id", "name": "GlobalCA"},
            {"id": "other-id", "name": "Fleet Performance"},
        ]
        output = StringIO()

        call_command("inspect_powerbi_catalog", "--query", "globalca", "--json", stdout=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["name"], "GlobalCA")
        self.assertNotIn("secret-token", output.getvalue())
