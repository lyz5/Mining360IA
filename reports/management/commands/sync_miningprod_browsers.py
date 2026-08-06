import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reports.models import DataBrowser, DataBrowserColumn, SystemIntegrationConfig
from reports.system_configuration_service import encrypt_secrets


METADATA_PATH = Path(__file__).resolve().parents[2] / "data" / "miningprod_browsers.json"
DISPLAY_NAME_OVERRIDES = {
    2406010: "Service Letters Tracking",
    2406026: "Neemba - Connectivity Status",
}
AUDIT_LABELS = {
    "created by",
    "created date",
    "date created",
    "last modified",
    "date modified",
    "modified by",
    "user_id",
}


def _enabled(value) -> bool:
    return str(value or "").strip().lower() in {"-1", "1", "true", "yes"}


def _data_type(sql_type: str) -> str:
    value = str(sql_type or "").lower()
    if value in {"bigint", "int", "smallint", "tinyint"}:
        return "Integer"
    if value in {"decimal", "numeric", "money", "smallmoney", "float", "real"}:
        return "Decimal"
    if value == "date":
        return "Date"
    if value in {"datetime", "datetime2", "smalldatetime", "datetimeoffset", "time"}:
        return "DateTime"
    if value == "bit":
        return "Boolean"
    return "Text"


def _text_length(column: dict) -> int | None:
    if _data_type(column.get("sql_type")) != "Text":
        return None
    raw = int(column.get("max_length") or 0)
    if raw < 0:
        return None
    if str(column.get("sql_type") or "").lower() in {"nvarchar", "nchar"}:
        raw //= 2
    return raw or None


def _source_object(value: str, form_id: int) -> str:
    value = str(value or "").strip()
    if not value:
        return f"META_FORM_VIEW_SCHEMA.v_metaform{form_id}"
    return value if "." in value else f"META_FORM_VIEW_SCHEMA.{value}"


def _default_sort(properties: dict, source_names: set[str]) -> list[dict]:
    sort_value = str(properties.get("Sort String") or "")
    result = []
    for source_name in re.findall(r"\[([^\]]+)\]", sort_value):
        if source_name in source_names:
            result.append({"column": source_name, "direction": "ASC"})
    return result


def _primary_key(columns: list[dict]) -> str:
    preferred = (
        "eventchainid",
        "equip id",
        "equipid",
        "id",
    )
    for candidate in preferred:
        for column in columns:
            label = str(column.get("display_name") or "").strip().lower()
            if label == candidate:
                return str(column["source_name"])
    unique = next((column for column in columns if column.get("unique")), None)
    return str((unique or columns[0])["source_name"])


class Command(BaseCommand):
    help = "Preview or synchronize the selected MiningProd MetaForm browsers into Mining 360."

    def add_arguments(self, parser):
        parser.add_argument("--preview", action="store_true")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--connection-code", default="miningprod-database")
        parser.add_argument("--form-id", action="append", type=int, dest="form_ids")
        parser.add_argument(
            "--legacy-web-config",
            help="One-time path to the legacy MiningProd web.config. The password is encrypted before storage.",
        )
        parser.add_argument(
            "--server-override",
            help="Override a legacy localhost SQL Server name when Mining 360 runs on another host.",
        )

    def handle(self, *args, **options):
        if options["preview"] == options["apply"]:
            raise CommandError("Choose exactly one mode: --preview or --apply.")
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8-sig"))
        selected_ids = set(options.get("form_ids") or [])
        definitions = [
            item
            for item in metadata.get("browsers", [])
            if not selected_ids or int(item["meta_form_id"]) in selected_ids
        ]
        if not definitions:
            raise CommandError("No matching MiningProd browser definition was found.")

        existing = {
            item.external_form_id: item
            for item in DataBrowser.objects.filter(
                external_form_id__in=[item["meta_form_id"] for item in definitions]
            )
        }
        create_count = sum(1 for item in definitions if item["meta_form_id"] not in existing)
        update_count = len(definitions) - create_count
        column_count = sum(len(item.get("columns") or []) for item in definitions)
        self.stdout.write(f"Browsers selected: {len(definitions)}")
        self.stdout.write(f"Browsers to create: {create_count}")
        self.stdout.write(f"Browsers to update: {update_count}")
        self.stdout.write(f"Columns to synchronize: {column_count}")
        self.stdout.write("Initial write mode: read only")
        self.stdout.write("OpenAI API calls: 0")
        if options["preview"]:
            for item in definitions:
                state = "UPDATE" if item["meta_form_id"] in existing else "CREATE"
                self.stdout.write(
                    f"{state} [{item['section']}] {item['name']} "
                    f"(MetaForm {item['meta_form_id']}, {len(item.get('columns') or [])} columns)"
                )
            return

        with transaction.atomic():
            connection = self._ensure_connection(
                options["connection_code"],
                legacy_web_config=options.get("legacy_web_config"),
                server_override=options.get("server_override"),
            )
            for position, definition in enumerate(definitions, start=1):
                self._synchronize_browser(connection, definition, position)
        self.stdout.write(self.style.SUCCESS(f"Synchronized {len(definitions)} MiningProd browsers."))

    def _ensure_connection(
        self,
        code: str,
        *,
        legacy_web_config: str | None = None,
        server_override: str | None = None,
    ) -> SystemIntegrationConfig:
        imported = self._legacy_connection_values(legacy_web_config) if legacy_web_config else {}
        if imported and server_override:
            imported["host"] = str(server_override).strip()
        defaults = {
            "name": "MiningProd Database",
            "integration_type": "Database",
            "provider": "SQL Server",
            "description": "Legacy MiningProd operational database used during browser migration.",
            "settings_json": {
                "engine": "SQL Server",
                "host": imported.get("host") or os.getenv("MININGPROD_SQL_SERVER", ""),
                "port": int(imported.get("port") or os.getenv("MININGPROD_SQL_PORT", "1433")),
                "database": imported.get("database") or os.getenv("MININGPROD_SQL_DATABASE", "MiningProd"),
                "schema": "dbo",
                "username": imported.get("username") or os.getenv("MININGPROD_SQL_USER", ""),
                "driver": os.getenv("MININGPROD_SQL_DRIVER", "ODBC Driver 18 for SQL Server"),
                "connection_timeout": 30,
                "encrypt": True,
                "trust_server_certificate": False,
            },
            "is_active": True,
            "is_default": False,
            "status": "Configured",
        }
        connection, created = SystemIntegrationConfig.objects.get_or_create(code=code, defaults=defaults)
        password = imported.get("password") or os.getenv("MININGPROD_SQL_PASSWORD", "")
        if imported and not created:
            settings_values = dict(connection.settings_json or {})
            settings_values.update({
                "engine": "SQL Server",
                "host": imported.get("host", ""),
                "port": int(imported.get("port") or 1433),
                "database": imported.get("database", "MiningProd"),
                "schema": "dbo",
                "username": imported.get("username", ""),
                "driver": os.getenv("MININGPROD_SQL_DRIVER", "ODBC Driver 18 for SQL Server"),
                "connection_timeout": 30,
            })
            connection.settings_json = settings_values
            connection.status = "Configured"
        if password:
            connection.encrypted_secrets = encrypt_secrets({"password": password})
            connection.configured_secret_keys = ["password"]
        if imported or password:
            connection.save()
        return connection

    def _legacy_connection_values(self, path_value: str) -> dict:
        path = Path(path_value).expanduser().resolve()
        if not path.is_file():
            raise CommandError("The legacy web.config path does not exist.")
        root = ET.parse(path).getroot()
        candidates = root.findall("./connectionStrings/add")
        node = next(
            (
                candidate
                for candidate in candidates
                if "miningprod" in str(candidate.attrib.get("connectionString") or "").lower()
            ),
            None,
        )
        if node is None:
            raise CommandError("No MiningProd connection string was found in the legacy web.config.")
        parts = {}
        for item in str(node.attrib.get("connectionString") or "").split(";"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            clean_value = value.strip()
            if (
                len(clean_value) >= 2
                and clean_value[0] == clean_value[-1]
                and clean_value[0] in {"'", '"'}
            ):
                clean_value = clean_value[1:-1]
            parts[key.strip().lower()] = clean_value
        server = parts.get("data source") or parts.get("server") or ""
        host, separator, raw_port = server.removeprefix("tcp:").partition(",")
        return {
            "host": host,
            "port": int(raw_port) if separator and raw_port.isdigit() else 1433,
            "database": parts.get("initial catalog") or parts.get("database") or "MiningProd",
            "username": parts.get("user id") or parts.get("uid") or "",
            "password": parts.get("password") or parts.get("pwd") or "",
        }

    def _synchronize_browser(
        self,
        connection: SystemIntegrationConfig,
        definition: dict,
        position: int,
    ) -> None:
        form_id = int(definition["meta_form_id"])
        columns = list(definition.get("columns") or [])
        properties = dict(definition.get("properties") or {})
        source_names = {str(column["source_name"]) for column in columns}
        source_capabilities = {
            "allow_create": _enabled(properties.get("For_Add")),
            "allow_edit": _enabled(properties.get("For_Edit")),
            "allow_delete": _enabled(properties.get("For_Delete")),
            "record_editor": _enabled(properties.get("Enable_Record_Editor")),
            "prompt_filters": _enabled(properties.get("Prompt Filters")),
            "load_all_records": _enabled(properties.get("Load_All_Records")),
        }
        name = DISPLAY_NAME_OVERRIDES.get(form_id, definition["name"])
        browser, _ = DataBrowser.objects.update_or_create(
            external_form_id=form_id,
            defaults={
                "name": name,
                "display_order": position,
                "section": definition.get("section") or "",
                "description": definition.get("description") or "",
                "table_name": f"miningprod.metaform_{form_id}",
                "source_view_name": _source_object(definition.get("read_view"), form_id),
                "source_mode": "miningprod_metaform",
                "source_connection": connection,
                "primary_key_column": _primary_key(columns),
                "write_strategy": "read_only",
                "allow_create": False,
                "allow_edit": False,
                "allow_delete": False,
                "allow_import": False,
                "allow_export": True,
                "default_page_size": 50,
                "maximum_page_size": 500,
                "default_sort_json": _default_sort(properties, source_names),
                "source_metadata_json": {
                    "source_name": definition["name"],
                    "data_mode": definition.get("data_mode"),
                    "properties": properties,
                    "source_capabilities": source_capabilities,
                },
                "migration_status": "read_only",
                "is_active": bool(definition.get("enabled", True)),
                "show_browser_record_id": False,
                "show_eventchain_id": False,
            },
        )
        current_names = set()
        for position, definition_column in enumerate(columns, start=1):
            source_name = str(definition_column["source_name"])
            current_names.add(source_name)
            label = str(definition_column.get("display_name") or source_name).strip()
            normalized_label = label.lower()
            DataBrowserColumn.objects.update_or_create(
                browser=browser,
                sql_name=source_name,
                defaults={
                    "source_column_name": source_name,
                    "source_field_id": definition_column.get("meta_field_id"),
                    "display_name": label,
                    "data_type": _data_type(definition_column.get("sql_type")),
                    "length": _text_length(definition_column),
                    "is_required": not bool(definition_column.get("nullable", True)),
                    "is_unique": bool(definition_column.get("unique")),
                    "display_order": position,
                    "is_visible": normalized_label not in {"user_id"},
                    "is_editable": False,
                    "is_filterable": True,
                    "is_sortable": True,
                    "is_searchable": _data_type(definition_column.get("sql_type")) == "Text",
                    "is_exportable": True,
                    "is_lookup": False,
                    "source_metadata_json": {
                        "control_type_id": definition_column.get("control_type_id"),
                        "field_type_id": definition_column.get("field_type_id"),
                        "lookup_id": definition_column.get("lookup_id"),
                        "column_type": definition_column.get("column_type"),
                        "source_editable_after_validation": normalized_label not in AUDIT_LABELS,
                    },
                },
            )
        browser.columns.exclude(sql_name__in=current_names).delete()
