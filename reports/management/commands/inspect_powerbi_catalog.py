import json

from django.core.management.base import BaseCommand

from reports.models import AISemanticColumn, AISemanticMeasure, AISemanticRelationship, AISemanticTable
from reports.power_automate import execute_dax_via_flow
from reports.powerbi import (
    env_value,
    execute_dataset_dax,
    get_access_token,
    get_dataset_schema_catalog,
    list_workspace_datasets,
    list_workspace_reports,
)


class Command(BaseCommand):
    help = "List sanitized Power BI report and semantic-model metadata without changing configuration."

    def add_arguments(self, parser):
        parser.add_argument("--query", default="", help="Optional case-insensitive name filter.")
        parser.add_argument("--json", action="store_true", help="Return machine-readable JSON.")
        parser.add_argument("--schema", default="", help="Inspect one semantic model's object names through XMLA.")
        parser.add_argument(
            "--rest-schema",
            default="",
            help="Inspect one semantic model's object names through the Power BI ExecuteQueries API.",
        )
        parser.add_argument(
            "--local-schema",
            action="store_true",
            help="Inspect sanitized semantic metadata already imported into Mining 360.",
        )
        parser.add_argument(
            "--flow-schema",
            default="",
            help="Inspect table names through the configured Power Automate DAX flow.",
        )

    def handle(self, *args, **options):
        query = str(options["query"] or "").strip().casefold()
        workspace_id = env_value("POWERBI_WORKSPACE_ID")
        flow_schema_name = str(options["flow_schema"] or "").strip()
        if flow_schema_name:
            payload = self._flow_schema_payload(workspace_id, flow_schema_name, query)
            self._write_payload(payload, options["json"])
            return
        if options["local_schema"]:
            payload = self._local_schema_payload(workspace_id, query)
            self._write_payload(payload, options["json"])
            return
        rest_schema_name = str(options["rest_schema"] or "").strip()
        if rest_schema_name:
            payload = self._rest_schema_payload(workspace_id, rest_schema_name, query)
            self._write_payload(payload, options["json"])
            return
        schema_name = str(options["schema"] or "").strip()
        if schema_name:
            payload = self._schema_payload(workspace_id, schema_name, query)
            self._write_payload(payload, options["json"])
            return
        token = get_access_token()
        reports = [{
            "type": "report",
            "id": str(item.id),
            "name": item.name,
            "semantic_model_id": item.dataset_id,
        } for item in list_workspace_reports()]
        datasets = [{
            "type": "semantic_model",
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
        } for item in list_workspace_datasets(token, workspace_id)]
        items = reports + datasets
        if query:
            items = [item for item in items if query in item["name"].casefold()]
        items.sort(key=lambda item: (item["type"], item["name"].casefold(), item["id"]))
        payload = {"workspace_id": workspace_id, "count": len(items), "results": items}
        self._write_payload(payload, options["json"])

    def _write_payload(self, payload, as_json):
        if as_json:
            self.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2))
            return
        self.stdout.write(f"Workspace: {payload['workspace_id']}")
        self.stdout.write(f"Results: {payload['count']}")
        for item in payload["results"]:
            suffix = f" -> semantic model {item['semantic_model_id']}" if item["type"] == "report" else ""
            identifier = f" ({item['id']})" if item.get("id") else ""
            owner = f" [{item['table']}]" if item.get("table") else ""
            self.stdout.write(f"[{item['type']}] {item['name']}{owner}{identifier}{suffix}")

    @staticmethod
    def _schema_payload(workspace_id, schema_name, query):
        catalog = get_dataset_schema_catalog(
            env_value("POWERBI_WORKSPACE_NAME", "Efficience Mine Workspace"),
            schema_name,
        )
        table_names = []
        for row in catalog["tables"]:
            normalized = {str(key).casefold(): value for key, value in row.items()}
            name = normalized.get("name") or normalized.get("tablename") or normalized.get("displayname")
            if name:
                table_names.append(str(name))
        items = [{"type": "table", "name": name} for name in table_names]
        items.extend({"type": "column", "name": item["name"], "table": item["table"]} for item in catalog["columns"])
        items.extend({"type": "measure", "name": item["name"], "table": item["table"]} for item in catalog["measures"])
        if query:
            items = [item for item in items if query in f"{item.get('table', '')} {item['name']}".casefold()]
        items.sort(key=lambda item: (item["type"], item.get("table", "").casefold(), item["name"].casefold()))
        return {
            "workspace_id": workspace_id,
            "semantic_model": schema_name,
            "count": len(items),
            "results": items,
        }

    @staticmethod
    def _rest_schema_payload(workspace_id, schema_name, query):
        token = get_access_token()
        datasets = list_workspace_datasets(token, workspace_id)
        target = next(
            (
                item
                for item in datasets
                if str(item.get("name") or "").strip().casefold() == schema_name.casefold()
            ),
            None,
        )
        if not target:
            raise RuntimeError(f"Semantic model not found: {schema_name}")

        table_rows = execute_dataset_dax(str(target.get("id") or ""), "EVALUATE INFO.TABLES()")
        items = []
        for row in table_rows:
            normalized = {str(key).strip("[]").casefold(): value for key, value in row.items()}
            name = normalized.get("name")
            if name:
                items.append({"type": "table", "name": str(name)})
        if query:
            items = [item for item in items if query in item["name"].casefold()]
        items.sort(key=lambda item: item["name"].casefold())
        return {
            "workspace_id": workspace_id,
            "semantic_model": schema_name,
            "semantic_model_id": str(target.get("id") or ""),
            "count": len(items),
            "results": items,
        }

    @staticmethod
    def _local_schema_payload(workspace_id, query):
        items = []
        for item in AISemanticTable.objects.select_related("section").all():
            items.append({
                "type": "table",
                "name": item.table_name,
                "section": item.section.code,
                "source_report": item.source_report,
                "dataset_id": item.dataset_id,
            })
        for item in AISemanticColumn.objects.select_related("section").all():
            items.append({
                "type": "column",
                "name": item.column_name,
                "table": item.table_name,
                "section": item.section.code,
                "data_type": item.data_type,
                "is_filter": item.is_filter,
                "source_report": item.source_report,
                "dataset_id": item.dataset_id,
            })
        for item in AISemanticMeasure.objects.select_related("section").all():
            items.append({
                "type": "measure",
                "name": item.measure_name,
                "table": "",
                "section": item.section.code,
                "unit": item.unit,
                "category": item.category,
                "source_report": item.source_report,
                "dataset_id": item.dataset_id,
            })
        for item in AISemanticRelationship.objects.select_related("section").all():
            items.append({
                "type": "relationship",
                "name": f"{item.parent_table}[{item.parent_column}] -> {item.child_table}[{item.child_column}]",
                "table": item.parent_table,
                "section": item.section.code,
                "source_report": item.source_report,
                "dataset_id": item.dataset_id,
            })
        if query:
            items = [
                item for item in items
                if query in " ".join(str(value) for value in item.values()).casefold()
            ]
        items.sort(key=lambda item: (
            item["type"], item.get("section", ""), item.get("table", ""), item["name"]
        ))
        return {
            "workspace_id": workspace_id,
            "source": "mining360_imported_semantic_metadata",
            "count": len(items),
            "results": items,
        }

    @staticmethod
    def _flow_schema_payload(workspace_id, schema_name, query):
        token = get_access_token()
        datasets = list_workspace_datasets(token, workspace_id)
        target = next(
            (
                item
                for item in datasets
                if str(item.get("name") or "").strip().casefold() == schema_name.casefold()
            ),
            None,
        )
        if not target:
            raise RuntimeError(f"Semantic model not found: {schema_name}")
        response = execute_dax_via_flow({
            "datasetId": str(target.get("id") or ""),
            "datasetName": schema_name,
            "query": "EVALUATE INFO.TABLES()",
            "question": "Mining 360 sanitized semantic table inspection",
            "section": "administration",
            "filters": {},
            "roles": [],
        })
        rows = response.get("firstTableRows")
        if not isinstance(rows, list):
            try:
                rows = response["results"][0]["tables"][0]["rows"]
            except (KeyError, IndexError, TypeError):
                rows = []
        items = []
        for row in rows:
            normalized = {str(key).strip("[]").casefold(): value for key, value in row.items()}
            name = normalized.get("name")
            if name:
                items.append({"type": "table", "name": str(name)})
        if query:
            items = [item for item in items if query in item["name"].casefold()]
        items.sort(key=lambda item: item["name"].casefold())
        return {
            "workspace_id": workspace_id,
            "semantic_model": schema_name,
            "semantic_model_id": str(target.get("id") or ""),
            "source": "power_automate_sanitized_metadata",
            "count": len(items),
            "results": items,
        }
