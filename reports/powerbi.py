import json
import os
import time
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


for _proxy_var in (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
):
    os.environ.pop(_proxy_var, None)


DEFAULT_TENANT_ID = ""
DEFAULT_CLIENT_ID = ""
DEFAULT_WORKSPACE_ID = ""
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
POWERBI_ROOT = "https://api.powerbi.com/v1.0/myorg"
DISPLAY_TIMEZONE = ZoneInfo("Atlantic/Reykjavik")
REPORT_LIST_CACHE_SECONDS = 300
ACCESS_TOKEN_CACHE_SECONDS = 45 * 60
_REPORT_LIST_CACHE: tuple[float, list["PowerBIReport"]] | None = None
_ACCESS_TOKEN_CACHE: tuple[float, str] | None = None
HTTP = requests.Session()
HTTP.trust_env = False
LOCAL_POWERBI_CREDENTIALS = Path(__file__).resolve().parents[1] / "powerbi_credentials.local.json"
LOCAL_POWERBI_REPORT_CONFIG = Path(__file__).resolve().parents[1] / "powerbi_report_connections.json"
XMLA_CLIENT_DLL_CANDIDATES = [
    r"C:\Program Files\Microsoft Office\root\Office16\ADDINS\Microsoft Power Query for Excel Integrated\bin\Microsoft.PowerBI.AdomdClient.dll",
    r"C:\Program Files\Microsoft Office\root\vfs\ProgramFilesCommonX64\Microsoft Shared\Office16\DataModel\Microsoft.Excel.AdomdClient.dll",
]
FOCUSED_REPORT_NAMES = {
    "FPR Global DB + RLS",
    "Fuel Monitoring Report V1",
    "LCC Dashboard",
    "Mine Logistics & AfterMarket",
    "Mine Logistics Report",
    "Mine Operator Induced Report",
    "Neemba Monthly Report Ext",
    "Neemba Monthly Report_New",
    "Neemba SOS Analysis Report",
    "POCA Report",
    "Prime Movers Operational Status",
    "Prime Movers Operational Status v2",
}
REPORT_DISPLAY_ALIASES = {
    "FPR Global DB + RLS": "Fleet Perormance Report",
    "Fuel Monitoring Report V1": "Fuel Monitoring Report",
    "LCC Dashboard": "LCC Dashboard",
    "Mine Logistics & AfterMarket": "Mining AfterMarket Perormance - Parts",
    "Mine Logistics Report": "Mine Logistics Report",
    "Mine Operator Induced Report": "Mine Operator Induced Report",
    "Neemba Monthly Report Ext": "Mine Monthly Report - Customer",
    "Neemba Monthly Report_New": "Mine Monthly Report - Neembers",
    "Neemba SOS Analysis Report": "Neemba SOS Analysis Report",
    "POCA Report": "Percentage Of Connected Assets Report",
    "Prime Movers Operational Status": "Prime Movers Operational Status",
    "Prime Movers Operational Status v2": "Prime Movers Operational Status V2",
}
RLS_ROLE_OPTIONS = [
    "Global",
    "Fekola",
    "Sangaredi/CBG",
    "Seguela",
    "Siguiri",
    "Simandou/Mota",
    "SNIM",
    "Tongon",
    "Bonikro/Mota",
    "Agbaou/Mota",
    "Essakane",
    "Kiaka",
    "Kouroussa",
    "Goulamina/CORICA",
    "Boto/Mota",
    "Sadiola/Mota",
    "SMB",
    "SNIM-Guelb",
    "SNTP",
]
KNOWN_DATASET_NAMES = {
    "fpr global db + rls": "364edd69-532c-4e10-867f-3b3d4dfdb6c7",
    "fpr global + rls": "364edd69-532c-4e10-867f-3b3d4dfdb6c7",
    "mine logistics report": "9db59281-164a-4992-b0a2-0c51837d1579",
}
DATASET_ROLE_ALIASES = {
    "neemba monthly report_new": {
        "global": "Global User",
        "fekola": "Fekola User",
        "sangaredi/cbg": "Sangaredi",
    },
    "fpr global db + rls": {
        "global user": "Global",
        "fekola user": "Fekola",
        "sangaredi": "Sangaredi/CBG",
        "sangaredi/cbg": "Sangaredi/CBG",
    },
    "fuel monitoring report v1": {
        "global": [
            "Agbaou/Mota",
            "Bonikro/Mota",
            "Essakane",
            "Fekola",
            "Goulamina/CORICA",
            "Kouroussa",
            "Sadiola/Mota",
            "Sangaredi/CBG",
            "Seguela",
            "Siguiri",
            "Simandou/Mota",
            "SMB",
            "SNIM-Guelb",
            "SNTP",
            "Tongon",
        ],
    },
}
REPORT_LINKED_DATASET_HINTS = {
    "neemba sos analysis report": [
        "FPR Global DB + RLS",
        "Mine Logistics Report",
    ],
}


@dataclass(frozen=True)
class PowerBIReport:
    id: str
    name: str
    display_name: str
    dataset_id: str
    web_url: str
    embed_url: str
    report_type: str
    last_refresh: str = ""
    refresh_status: str = ""


def _local_powerbi_credentials() -> dict:
    if not LOCAL_POWERBI_CREDENTIALS.exists():
        return {}
    try:
        with LOCAL_POWERBI_CREDENTIALS.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key).upper(): str(value) for key, value in data.items() if value}


@lru_cache(maxsize=1)
def _local_powerbi_report_config() -> dict:
    if not LOCAL_POWERBI_REPORT_CONFIG.exists():
        return {}
    try:
        with LOCAL_POWERBI_REPORT_CONFIG.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_report_connection_options(report: "PowerBIReport") -> dict:
    config = _local_powerbi_report_config()
    for item in config.get("reports", []):
        if item.get("report_id") == report.id or item.get("name") == report.name:
            return item
    return {}


def env_value(name: str, default: str | None = None) -> str:
    value = os.getenv(name)
    if not value and name.startswith("POWERBI_"):
        field_map = {
            "POWERBI_WORKSPACE_ID": ("workspace_id", False),
            "POWERBI_WORKSPACE_NAME": ("workspace_name", False),
            "POWERBI_TENANT_ID": ("tenant_id", False),
            "POWERBI_CLIENT_ID": ("client_id", False),
            "POWERBI_CLIENT_SECRET": ("client_secret", True),
            "POWERBI_API_ROOT": ("api_root", False),
            "POWERBI_SCOPE": ("scope", False),
            "POWERBI_EFFECTIVE_ROLES": ("effective_roles", False),
            "POWERBI_EFFECTIVE_USERNAME": ("effective_username", False),
        }
        mapping = field_map.get(name)
        if mapping:
            try:
                from .system_configuration_service import integration_value

                value = integration_value("Power BI", mapping[0], "", secret=mapping[1])
            except Exception:
                value = ""
    if not value and name.startswith("POWERBI_"):
        value = _local_powerbi_credentials().get(name)
    if not value:
        value = default
    if not value:
        raise RuntimeError(f"Variable d'environnement manquante: {name}")
    return value


def powerbi_root() -> str:
    return env_value("POWERBI_API_ROOT", POWERBI_ROOT).rstrip("/")


def powerbi_scope() -> str:
    return env_value("POWERBI_SCOPE", POWERBI_SCOPE)


def _configured_integer(integration_key: str, parameter_key: str, default: int) -> int:
    try:
        from .system_configuration_service import integration_value, parameter_value

        value = integration_value("Power BI", integration_key, None)
        if value in (None, ""):
            value = parameter_value(parameter_key, default)
        return int(value or default)
    except Exception:
        return default


def _display_timezone():
    try:
        from .system_configuration_service import parameter_value

        return ZoneInfo(str(parameter_value("default-timezone", "UTC") or "UTC"))
    except Exception:
        return DISPLAY_TIMEZONE


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def get_report_display_aliases() -> dict[str, str]:
    try:
        from .mining360_repository import fetch_report_aliases

        aliases = fetch_report_aliases()
        if aliases:
            return aliases
    except Exception:
        pass
    return REPORT_DISPLAY_ALIASES


def get_access_token() -> str:
    global _ACCESS_TOKEN_CACHE
    now = time.monotonic()
    if _ACCESS_TOKEN_CACHE and now - _ACCESS_TOKEN_CACHE[0] < ACCESS_TOKEN_CACHE_SECONDS:
        return _ACCESS_TOKEN_CACHE[1]

    tenant_id = env_value("POWERBI_TENANT_ID", DEFAULT_TENANT_ID)
    client_id = env_value("POWERBI_CLIENT_ID", DEFAULT_CLIENT_ID)
    client_secret = env_value("POWERBI_CLIENT_SECRET")

    response = HTTP.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": powerbi_scope(),
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Power BI authentication failed ({response.status_code}): {response.text}"
        )
    token = response.json()["access_token"]
    _ACCESS_TOKEN_CACHE = (now, token)
    return token


def list_workspace_reports() -> list[PowerBIReport]:
    global _REPORT_LIST_CACHE
    now = time.monotonic()
    cache_seconds = _configured_integer("report_cache_seconds", "default-cache-duration", REPORT_LIST_CACHE_SECONDS)
    if _REPORT_LIST_CACHE and now - _REPORT_LIST_CACHE[0] < cache_seconds:
        return list(_REPORT_LIST_CACHE[1])

    workspace_id = env_value("POWERBI_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    token = get_access_token()
    display_aliases = get_report_display_aliases()
    response = HTTP.get(
        f"{powerbi_root()}/groups/{workspace_id}/reports",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Unable to retrieve Power BI reports ({response.status_code}): {response.text}"
        )

    reports = []
    for item in response.json().get("value", []):
        reports.append(
            PowerBIReport(
                id=item.get("id", ""),
                name=item.get("name", ""),
                display_name=display_aliases.get(item.get("name", ""), item.get("name", "")),
                dataset_id=item.get("datasetId", ""),
                web_url=item.get("webUrl", ""),
                embed_url=item.get("embedUrl", ""),
                report_type=item.get("reportType", ""),
            )
        )
    reports = sorted(reports, key=lambda report: report.name.lower())
    _REPORT_LIST_CACHE = (now, reports)
    return list(reports)


def list_report_pages(report_id: str, token: str | None = None, workspace_id: str | None = None) -> list[dict]:
    token = token or get_access_token()
    workspace_id = workspace_id or env_value("POWERBI_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    response = HTTP.get(
        f"{powerbi_root()}/groups/{workspace_id}/reports/{report_id}/pages",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Unable to retrieve Power BI pages ({response.status_code}): {response.text}"
        )
    return [item for item in response.json().get("value", []) if isinstance(item, dict)]


def get_latest_refresh(token: str, workspace_id: str, dataset_id: str) -> tuple[str, str]:
    if not dataset_id:
        return "", ""
    response = HTTP.get(
        f"{powerbi_root()}/groups/{workspace_id}/datasets/{dataset_id}/refreshes?$top=1",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        return "", "Unavailable"
    values = response.json().get("value", [])
    if not values:
        return "", "No refresh"
    latest = values[0]
    refresh_time = (
        latest.get("endTime")
        or latest.get("startTime")
        or latest.get("refreshStartTime")
        or ""
    )
    return format_refresh_datetime(refresh_time), latest.get("status", "")


def format_refresh_datetime(value: str) -> str:
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    return parsed.astimezone(_display_timezone()).strftime("%Y-%m-%d %I:%M %p")


def list_workspace_reports_with_refresh() -> list[PowerBIReport]:
    workspace_id = env_value("POWERBI_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    token = get_access_token()
    reports = list_workspace_reports()
    enriched = []
    for report in reports:
        last_refresh, refresh_status = get_latest_refresh(token, workspace_id, report.dataset_id)
        enriched.append(
            PowerBIReport(
                id=report.id,
                name=report.name,
                display_name=report.display_name,
                dataset_id=report.dataset_id,
                web_url=report.web_url,
                embed_url=report.embed_url,
                report_type=report.report_type,
                last_refresh=last_refresh,
                refresh_status=refresh_status,
            )
        )
    return enriched


def list_workspace_datasets(token: str, workspace_id: str) -> list[dict]:
    response = HTTP.get(
        f"{powerbi_root()}/groups/{workspace_id}/datasets",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Unable to retrieve semantic models ({response.status_code}): {response.text}"
        )
    return response.json().get("value", [])


def get_dataset_metadata(token: str, workspace_id: str, dataset_id: str) -> dict:
    response = HTTP.get(
        f"{powerbi_root()}/groups/{workspace_id}/datasets/{dataset_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Unable to retrieve the semantic model ({response.status_code}): {response.text}"
        )
    return response.json()


def resolve_workspace_dataset_id(dataset_name: str) -> str:
    workspace_id = env_value("POWERBI_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    token = get_access_token()
    normalized_target = normalize_name(dataset_name)
    for item in list_workspace_datasets(token, workspace_id):
        name = item.get("name", "")
        if normalize_name(name) == normalized_target:
            return item.get("id", "")
    dataset_id = KNOWN_DATASET_NAMES.get(dataset_name.lower()) or KNOWN_DATASET_NAMES.get(normalized_target)
    if dataset_id:
        return dataset_id
    raise RuntimeError(f"Dataset Power BI introuvable: {dataset_name}")


def execute_dataset_dax(dataset_id: str, dax_query: str) -> list[dict]:
    workspace_id = env_value("POWERBI_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    token = get_access_token()
    response = HTTP.post(
        f"{powerbi_root()}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "queries": [{"query": dax_query}],
            "serializerSettings": {"includeNulls": True},
        },
        timeout=_configured_integer("query_timeout_seconds", "default-query-timeout", 300),
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"DAX execution failed ({response.status_code}): {response.text}"
        )
    results = response.json().get("results", [])
    if not results:
        return []
    tables = results[0].get("tables", [])
    if not tables:
        return []
    return tables[0].get("rows", [])


def discover_dataset_measures_rest(dataset_id: str) -> list[dict]:
    query = """
EVALUATE
SELECTCOLUMNS(
    INFO.MEASURES(),
    "Table", [Table],
    "Name", [Name],
    "Expression", [Expression],
    "Description", [Description],
    "Display Folder", [DisplayFolder]
)
ORDER BY [Table], [Name]
""".strip()
    return execute_dataset_dax(dataset_id, query)


def get_workspace_details(token: str, workspace_id: str) -> dict:
    response = HTTP.get(
        f"{powerbi_root()}/groups/{workspace_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Unable to retrieve the workspace ({response.status_code}): {response.text}"
        )
    return response.json()


def _load_adomd_types():
    import clr

    for candidate in XMLA_CLIENT_DLL_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            clr.AddReference(str(path))
            break
    else:
        raise RuntimeError("Client ADOMD introuvable sur la machine.")

    clr.AddReference("System")
    import System
    from Microsoft.AnalysisServices.AdomdClient import AccessToken, AdomdConnection

    return System, AdomdConnection, AccessToken


def _open_xmla_connection(workspace_name: str, dataset_name: str):
    token = get_access_token()
    System, AdomdConnection, AccessToken = _load_adomd_types()

    connection = AdomdConnection(
        "Data Source=powerbi://api.powerbi.com/v1.0/myorg/{workspace};"
        "Initial Catalog={dataset};"
        "Persist Security Info=True;"
        .format(
            workspace=workspace_name,
            dataset=dataset_name,
        )
    )
    connection.AccessToken = AccessToken(
        token,
        System.DateTimeOffset.UtcNow.AddMinutes(50),
        None,
    )
    connection.Open()
    return connection


def _coerce_xmla_value(value):
    try:
        import System
        if value is None or value == System.DBNull.Value:
            return None
    except Exception:
        if value is None:
            return None
    if isinstance(value, datetime):
        return value.isoformat()
    value_type = type(value).__name__
    if value_type in {"DateTime", "DateTimeOffset"}:
        try:
            return value.ToString("o")
        except Exception:
            return str(value)
    if value_type not in {"str", "int", "float", "bool", "list", "dict"}:
        if hasattr(value, "ToString"):
            try:
                return value.ToString()
            except Exception:
                return str(value)
    return value


def _fetch_xmla_rows(connection, command_text: str) -> list[dict]:
    command = connection.CreateCommand()
    command.CommandText = command_text
    reader = command.ExecuteReader()
    columns = [reader.GetName(i) for i in range(reader.FieldCount)]
    rows = []
    try:
        while reader.Read():
            row = {}
            for i, column in enumerate(columns):
                row[column] = _coerce_xmla_value(reader.GetValue(i))
            rows.append(row)
        return rows
    finally:
        reader.Close()


def _row_value(row: dict, *candidates: str) -> object:
    normalized = {re.sub(r"[^a-z0-9]+", "", str(key).lower()): value for key, value in row.items()}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if key in normalized:
            return normalized[key]
    return None


def _clean_measure_folder(folder: object) -> str:
    value = str(folder or "").strip()
    if not value:
        return ""
    normalized = normalize_name(value)
    if "timeintelligence" in normalized or normalized.startswith("timeintelligence"):
        return ""
    return value


@lru_cache(maxsize=256)
def get_dataset_schema_catalog(workspace_name: str, dataset_name: str) -> dict:
    connection = _open_xmla_connection(workspace_name, dataset_name)
    try:
        tables = _fetch_xmla_rows(
            connection,
            "SELECT * FROM $SYSTEM.TMSCHEMA_TABLES",
        )
        columns = _fetch_xmla_rows(
            connection,
            "SELECT * FROM $SYSTEM.TMSCHEMA_COLUMNS",
        )
        measures_raw = _fetch_xmla_rows(
            connection,
            "SELECT * FROM $SYSTEM.TMSCHEMA_MEASURES",
        )
        table_lookup = {
            str(_row_value(row, "ID", "TableID", "Table_Id", "ObjectID", "ObjectId")): _row_value(row, "Name", "TableName", "DisplayName") or ""
            for row in tables
        }
        columns_with_table = []
        for row in columns:
            table_id_value = _row_value(row, "TableID", "Table_Id", "Table ID", "Table")
            table_id = str(table_id_value) if table_id_value is not None else ""
            columns_with_table.append(
                {
                    "name": _row_value(
                        row,
                        "Name",
                        "ExplicitName",
                        "InferredName",
                        "ColumnName",
                        "DisplayName",
                    ) or "",
                    "table": table_lookup.get(table_id, ""),
                }
            )
        measures = []
        for row in measures_raw:
            table_id_value = _row_value(row, "TableID", "Table_Id", "Table ID", "Table")
            table_id = str(table_id_value) if table_id_value is not None else ""
            measures.append(
                {
                    "name": _row_value(row, "Name", "MeasureName", "DisplayName") or "",
                    "table": table_lookup.get(table_id, ""),
                    "display_folder": _clean_measure_folder(_row_value(row, "DisplayFolder", "Display Folder")),
                    "description": _row_value(row, "Description") or "",
                    "expression": _row_value(row, "Expression") or "",
                }
            )
        return {
            "table_count": len(tables),
            "column_count": len(columns),
            "measure_count": len(measures),
            "tables": tables,
            "columns": columns_with_table,
            "measures": measures,
        }
    finally:
        connection.Close()


@lru_cache(maxsize=256)
def get_dataset_schema_counts(workspace_name: str, dataset_name: str) -> dict[str, int]:
    catalog = get_dataset_schema_catalog(workspace_name, dataset_name)
    return {
        "table_count": catalog["table_count"],
        "column_count": catalog["column_count"],
        "measure_count": catalog["measure_count"],
    }


def _escape_dax_identifier(value: str) -> str:
    return value.replace("]", "]]")


def _escape_dax_string(value: str) -> str:
    return value.replace('"', '""')


def _escape_dax_table_name(value: str) -> str:
    return value.replace("'", "''")


def _dax_table_column_ref(table_name: str, column_name: str) -> str:
    return f"'{_escape_dax_table_name(table_name)}'[{_escape_dax_identifier(column_name)}]"


def _dax_measure_ref(measure_name: str, table_name: str = "") -> str:
    if table_name:
        return f"'{_escape_dax_table_name(table_name)}'[{_escape_dax_identifier(measure_name)}]"
    return f"[{_escape_dax_identifier(measure_name)}]"


def _build_date_filter_clause(date_table: str, date_column: str, start_date: str | None, end_date: str | None) -> str:
    clauses = []
    ref = _dax_table_column_ref(date_table, date_column)
    if start_date:
        year, month, day = (int(part) for part in start_date.split("-"))
        clauses.append(f"{ref} >= DATE({year}, {month}, {day})")
    if end_date:
        year, month, day = (int(part) for part in end_date.split("-"))
        clauses.append(f"{ref} < DATE({year}, {month}, {day}) + 1")
    if not clauses:
        return ""
    return f"FILTER(ALL({ref}), {' && '.join(clauses)})"


def _execute_single_row_query(connection, command_text: str) -> dict[str, object]:
    rows = _fetch_xmla_rows(connection, command_text)
    return rows[0] if rows else {}


def _execute_single_value_query(connection, command_text: str) -> object:
    row = _execute_single_row_query(connection, command_text)
    if not row:
        return None
    return next(iter(row.values()))


@lru_cache(maxsize=128)
def get_dataset_measures(workspace_name: str, dataset_name: str) -> list[dict]:
    catalog = get_dataset_schema_catalog(workspace_name, dataset_name)
    return catalog["measures"]


def resolve_date_dimension(catalog: dict) -> tuple[str, str]:
    columns = catalog.get("columns", [])
    preferred_table_tokens = ("date", "calendar", "time")
    preferred_column_tokens = ("date", "datekey", "fulldate", "day", "datetime")

    def is_preferred_table(name: str) -> bool:
        normalized = normalize_name(name)
        return any(token in normalized for token in preferred_table_tokens)

    def is_preferred_column(name: str) -> bool:
        normalized = normalize_name(name)
        return any(token == normalized or token in normalized for token in preferred_column_tokens)

    for column in columns:
        table_name = column.get("table", "")
        column_name = column.get("name", "")
        if table_name and is_preferred_table(table_name) and is_preferred_column(column_name):
            return table_name, column_name

    for column in columns:
        table_name = column.get("table", "")
        column_name = column.get("name", "")
        if table_name and is_preferred_column(column_name):
            return table_name, column_name

    return "", ""


def query_dataset_measure_values(
    workspace_name: str,
    dataset_name: str,
    measures: list[dict],
    start_date: str | None = None,
    end_date: str | None = None,
    date_table: str = "Date",
    date_column: str = "Date",
    chunk_size: int = 12,
) -> dict[str, object]:
    connection = _open_xmla_connection(workspace_name, dataset_name)
    try:
        value_map: dict[str, object] = {}
        catalog = get_dataset_schema_catalog(workspace_name, dataset_name)
        resolved_date_table, resolved_date_column = resolve_date_dimension(catalog)
        date_filter = ""
        if start_date or end_date:
            if resolved_date_table and resolved_date_column:
                date_filter = _build_date_filter_clause(
                    resolved_date_table,
                    resolved_date_column,
                    start_date,
                    end_date,
                )
        for measure in measures:
            measure_name = measure.get("name", "")
            ref = _dax_measure_ref(measure_name)
            query = f'EVALUATE ROW("Value", CALCULATE({ref}{", " + date_filter if date_filter else ""}))'
            try:
                value_map[measure_name] = _coerce_xmla_value(_execute_single_value_query(connection, query))
            except Exception:
                fallback_query = f'EVALUATE ROW("Value", {ref})'
                try:
                    value_map[measure_name] = _coerce_xmla_value(_execute_single_value_query(connection, fallback_query))
                except Exception as exc:
                    value_map[measure_name] = f"ERROR: {exc}"

        return value_map
    finally:
        connection.Close()


def resolve_dataset_roles(dataset_name: str, roles: list[str]) -> list[str]:
    aliases = DATASET_ROLE_ALIASES.get(dataset_name.lower(), {})
    resolved = []
    for role in roles:
        resolved_role = aliases.get(role.lower(), role)
        if isinstance(resolved_role, list):
            for item in resolved_role:
                if item not in resolved:
                    resolved.append(item)
            continue
        if resolved_role not in resolved:
            resolved.append(resolved_role)
    return resolved


def get_linked_powerbi_dataset_ids(token: str, workspace_id: str, dataset_id: str) -> list[str]:
    response = HTTP.get(
        f"{powerbi_root()}/groups/{workspace_id}/datasets/{dataset_id}/datasources",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        return []

    linked_ids = []
    dataset_lookup = {}
    for item in list_workspace_datasets(token, workspace_id):
        name = item.get("name", "")
        dataset_lookup[normalize_name(name)] = item.get("id")
        dataset_lookup[name.lower()] = item.get("id")
    for item in response.json().get("value", []):
        if item.get("datasourceType") != "AnalysisServices":
            continue
        database = item.get("connectionDetails", {}).get("database", "").lower()
        dataset_id_value = (
            dataset_lookup.get(normalize_name(database))
            or dataset_lookup.get(database)
            or KNOWN_DATASET_NAMES.get(database)
            or KNOWN_DATASET_NAMES.get(normalize_name(database))
        )
        if dataset_id_value and dataset_id_value not in linked_ids:
            linked_ids.append(dataset_id_value)
    return linked_ids


def get_report_hint_dataset_ids(token: str, workspace_id: str, report_name: str) -> list[str]:
    hints = REPORT_LINKED_DATASET_HINTS.get(normalize_name(report_name), [])
    if not hints:
        return []

    dataset_lookup = {}
    for item in list_workspace_datasets(token, workspace_id):
        name = item.get("name", "")
        dataset_lookup[normalize_name(name)] = item.get("id")
        dataset_lookup[name.lower()] = item.get("id")

    resolved = []
    for hint in hints:
        dataset_id_value = (
            dataset_lookup.get(normalize_name(hint))
            or dataset_lookup.get(hint.lower())
            or KNOWN_DATASET_NAMES.get(hint.lower())
            or KNOWN_DATASET_NAMES.get(normalize_name(hint))
        )
        if dataset_id_value and dataset_id_value not in resolved:
            resolved.append(dataset_id_value)
    return resolved


def get_workspace_report(report_id: str, reports: list[PowerBIReport] | None = None) -> PowerBIReport:
    reports = reports or list_workspace_reports()
    for report in reports:
        if str(report.id) == str(report_id):
            return report
    raise RuntimeError(f"Report not found: {report_id}")


def generate_report_embed_token(report: PowerBIReport, selected_roles: list[str] | None = None) -> str:
    workspace_id = env_value("POWERBI_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
    token = get_access_token()
    connection_options = get_report_connection_options(report)
    dataset_ids = [
        dataset_id
        for dataset_id in connection_options.get("dataset_ids", [])
        if dataset_id
    ]
    if not dataset_ids:
        dataset_ids = [report.dataset_id]
        for hinted_id in get_report_hint_dataset_ids(token, workspace_id, report.name):
            if hinted_id not in dataset_ids:
                dataset_ids.append(hinted_id)
        for linked_id in get_linked_powerbi_dataset_ids(token, workspace_id, report.dataset_id):
            if linked_id not in dataset_ids:
                dataset_ids.append(linked_id)

    payload = {
        "reports": [{"id": report.id}],
        "datasets": [{"id": dataset_id, "xmlaPermissions": "ReadOnly"} for dataset_id in dataset_ids],
        "targetWorkspaces": [{"id": workspace_id}],
    }
    effective_username = connection_options.get("embed", {}).get("effective_username", "")
    try:
        effective_username = effective_username or env_value("POWERBI_EFFECTIVE_USERNAME")
    except RuntimeError:
        pass
    effective_roles = selected_roles or [
        role.strip()
        for role in (os.getenv("POWERBI_EFFECTIVE_ROLES") or _local_powerbi_credentials().get("POWERBI_EFFECTIVE_ROLES", "")).split(",")
        if role.strip()
    ]

    identities = []
    if effective_username:
        for dataset_id in dataset_ids:
            metadata = get_dataset_metadata(token, workspace_id, dataset_id)
            if not metadata.get("isEffectiveIdentityRequired"):
                continue
            identity = {
                "username": effective_username,
                "datasets": [dataset_id],
            }
            if metadata.get("isEffectiveIdentityRolesRequired"):
                dataset_roles = resolve_dataset_roles(metadata.get("name", ""), effective_roles)
                if not dataset_roles:
                    raise RuntimeError(
                        f"Le dataset {metadata.get('name', dataset_id)} exige un role RLS. "
                        "Definis POWERBI_EFFECTIVE_ROLES."
                    )
                identity["roles"] = dataset_roles
            identities.append(identity)
    if identities:
        payload["identities"] = identities

    response = HTTP.post(
        f"{powerbi_root()}/GenerateToken",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Embed token generation failed ({response.status_code}): {response.text}"
        )
    return response.json()["token"]
