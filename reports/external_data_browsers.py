import json
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from .models import DataBrowser, DataBrowserColumn
from .sqlserver import connect
from .system_configuration_service import decrypt_secrets


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ $.-]*$")


class ExternalBrowserError(ValueError):
    pass


def _quote_identifier(value: str) -> str:
    value = str(value or "").strip()
    if not value or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ExternalBrowserError(f"Invalid SQL identifier: {value or '(empty)'}")
    return f"[{value.replace(']', ']]')}]"


def _quote_object_name(value: str) -> str:
    parts = [part.strip() for part in str(value or "").split(".") if part.strip()]
    if not parts or len(parts) > 2:
        raise ExternalBrowserError("External source must use schema.object format.")
    return ".".join(_quote_identifier(part) for part in parts)


def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _connection_settings(browser: DataBrowser) -> dict:
    integration = browser.source_connection
    if not integration or not integration.is_active:
        raise ExternalBrowserError(
            "The external database connection is not configured or is disabled."
        )
    if integration.integration_type != "Database":
        raise ExternalBrowserError("The selected source connection is not a database integration.")
    values = dict(integration.settings_json or {})
    secrets = decrypt_secrets(integration)
    if not values.get("host") or not values.get("database"):
        raise ExternalBrowserError("The external database host and database are required.")
    return {
        "server": values.get("host"),
        "database": values.get("database"),
        "user": values.get("username") or None,
        "password": secrets.get("password") or None,
        "port": values.get("port") or None,
        "driver": values.get("driver") or None,
        "timeout_seconds": values.get("connection_timeout") or 30,
    }


@contextmanager
def external_browser_connection(browser: DataBrowser):
    with connect(**_connection_settings(browser)) as connection:
        yield connection


def validate_external_browser(browser: DataBrowser) -> None:
    _quote_object_name(browser.source_view_name)
    if not browser.source_connection_id:
        raise ExternalBrowserError("An external database connection is required.")
    if browser.write_strategy == "managed_table":
        raise ExternalBrowserError("External browsers cannot use the managed-table write strategy.")


def _column_name(column: DataBrowserColumn) -> str:
    return column.source_column_name or column.sql_name


def _parameter_marker(connection) -> str:
    module_name = connection.__class__.__module__.lower()
    return "%s" if "pytds" in module_name else "?"


def _parse_filters(filters) -> list[dict]:
    if not filters:
        return []
    if isinstance(filters, list):
        payload = filters
    else:
        try:
            payload = json.loads(str(filters))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExternalBrowserError("Invalid browser filters.") from exc
    if not isinstance(payload, list):
        raise ExternalBrowserError("Invalid browser filters.")
    return [item for item in payload if isinstance(item, dict)]


def _filter_column(columns: list[DataBrowserColumn], index: int) -> DataBrowserColumn:
    if index < 0 or index >= len(columns):
        raise ExternalBrowserError("Invalid filter column.")
    column = columns[index]
    if not column.is_filterable:
        raise ExternalBrowserError(f"{column.display_name} cannot be filtered.")
    return column


def _where_clause(connection, columns: list[DataBrowserColumn], filters) -> tuple[str, list]:
    marker = _parameter_marker(connection)
    clauses = []
    parameters = []
    for item in _parse_filters(filters):
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        column = _filter_column(columns, int(item.get("columnIndex") or 0))
        operator = str(item.get("operator") or "equal").strip().lower()
        joiner = "OR" if str(item.get("joiner") or "").upper() == "OR" else "AND"
        column_sql = _quote_identifier(_column_name(column))
        if operator == "like":
            expression = f"CONVERT(nvarchar(max), {column_sql}) LIKE {marker}"
            value = f"%{value}%"
        elif operator == "starts_with":
            expression = f"CONVERT(nvarchar(max), {column_sql}) LIKE {marker}"
            value = f"{value}%"
        else:
            expression = f"CONVERT(nvarchar(max), {column_sql}) = {marker}"
        clauses.append((joiner, expression))
        parameters.append(value)
    if not clauses:
        return "", []
    sql = " WHERE " + clauses[0][1]
    for joiner, expression in clauses[1:]:
        sql += f" {joiner} {expression}"
    return sql, parameters


def _sort_expression(browser: DataBrowser, columns: list[DataBrowserColumn], sort=None) -> str:
    requested = sort if isinstance(sort, list) else browser.default_sort_json
    items = []
    by_name = {
        _column_name(column).lower(): column
        for column in columns
        if column.is_sortable
    }
    for item in requested or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("column") or item.get("sql_name") or "").strip().lower()
        column = by_name.get(name)
        if not column:
            continue
        direction = "DESC" if str(item.get("direction") or "").upper() == "DESC" else "ASC"
        items.append(f"{_quote_identifier(_column_name(column))} {direction}")
    if not items:
        primary = next(
            (
                column
                for column in columns
                if _column_name(column).lower() == browser.primary_key_column.lower()
            ),
            columns[0],
        )
        items.append(f"{_quote_identifier(_column_name(primary))} DESC")
    return ", ".join(items)


def preview_external_browser_data(
    browser: DataBrowser,
    *,
    limit=100,
    filters=None,
    page=1,
    sort=None,
) -> dict:
    validate_external_browser(browser)
    columns = [column for column in browser.columns.all() if column.is_visible]
    if not columns:
        return {
            "columns": [],
            "column_types": [],
            "column_definitions": [],
            "rows": [],
            "row_values": [],
            "row_count": 0,
            "total_count": 0,
            "page": 1,
            "page_size": 0,
            "source_mode": browser.source_mode,
        }
    try:
        raw_limit = str(limit or browser.default_page_size).strip().lower()
        requested_limit = (
            browser.maximum_page_size
            if raw_limit in {"all", "0", "-1"}
            else int(raw_limit)
        )
    except (TypeError, ValueError) as exc:
        raise ExternalBrowserError("Invalid page size.") from exc
    page_size = max(1, min(requested_limit, browser.maximum_page_size))
    page_number = max(1, int(page or 1))
    offset = (page_number - 1) * page_size
    primary_column = next(
        (
            column
            for column in columns
            if _column_name(column).lower() == browser.primary_key_column.lower()
        ),
        columns[0],
    )
    filter_columns = [primary_column] + columns
    select_sql = ", ".join(
        [_quote_identifier(_column_name(primary_column))]
        + [_quote_identifier(_column_name(column)) for column in columns]
    )
    source_sql = _quote_object_name(browser.source_view_name)
    with external_browser_connection(browser) as connection:
        where_sql, parameters = _where_clause(connection, filter_columns, filters)
        order_sql = _sort_expression(browser, columns, sort)
        marker = _parameter_marker(connection)
        count_sql = f"SELECT COUNT_BIG(1) FROM {source_sql}{where_sql}"
        cursor = connection.cursor()
        cursor.execute(count_sql, tuple(parameters))
        total_count = int(cursor.fetchone()[0])
        query = (
            f"SELECT {select_sql} FROM {source_sql}{where_sql} "
            f"ORDER BY {order_sql} OFFSET {marker} ROWS FETCH NEXT {marker} ROWS ONLY"
        )
        cursor.execute(query, tuple(parameters + [offset, page_size]))
        raw_rows = cursor.fetchall()
    values = [[_json_safe(value) for value in row] for row in raw_rows]
    labels = ["BrowserRecordId"] + [column.display_name for column in columns]
    records = [dict(zip(labels, row)) for row in values]
    definitions = [{
        "id": None,
        "sql_name": "BrowserRecordId",
        "source_column_name": _column_name(primary_column),
        "display_name": "BrowserRecordId",
        "data_type": "Integer",
        "is_lookup": False,
        "is_editable": False,
        "is_filterable": True,
        "is_sortable": True,
    }] + [
        {
            "id": column.id,
            "sql_name": column.sql_name,
            "source_column_name": _column_name(column),
            "display_name": column.display_name,
            "data_type": column.data_type,
            "is_lookup": column.is_lookup,
            "is_editable": column.is_editable,
            "is_filterable": column.is_filterable,
            "is_sortable": column.is_sortable,
        }
        for column in columns
    ]
    return {
        "columns": labels,
        "column_types": [primary_column.data_type.lower()] + [
            column.data_type.lower() for column in columns
        ],
        "column_definitions": definitions,
        "rows": records,
        "row_values": values,
        "row_count": len(values),
        "total_count": total_count,
        "page": page_number,
        "page_size": page_size,
        "page_count": (total_count + page_size - 1) // page_size,
        "filters": _parse_filters(filters),
        "source_mode": browser.source_mode,
    }


def ensure_external_write_allowed(browser: DataBrowser, operation: str) -> None:
    capability = {
        "create": browser.allow_create,
        "edit": browser.allow_edit,
        "delete": browser.allow_delete,
        "import": browser.allow_import,
    }.get(operation, False)
    if not capability or browser.write_strategy == "read_only":
        raise ExternalBrowserError(
            f"{operation.title()} is disabled until the MiningProd write mapping has been validated."
        )
    raise ExternalBrowserError(
        "The MiningProd write adapter is not enabled for this browser yet."
    )
