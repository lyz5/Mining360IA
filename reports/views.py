import csv
import json
import re
import time
from urllib.parse import unquote, urlparse

from django.db import models, transaction
from django.core.cache import cache
from django.apps import apps
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from datetime import date, datetime
from django.utils import timezone

try:  # pragma: no cover - optional dependency
    import snowflake.connector as snowflake_connector
except ImportError:  # pragma: no cover
    snowflake_connector = None

from .live_sources import (
    add_live_source,
    add_live_view,
    delete_live_source,
    delete_live_view,
    execute_live_view,
    get_live_source,
    get_live_view,
    list_live_sources,
    set_live_source_verification,
    update_live_source,
    update_live_view,
)
from .sqlserver import connect
from .powerbi import (
    RLS_ROLE_OPTIONS,
    discover_dataset_measures_rest,
    execute_dataset_dax,
    get_access_token,
    generate_report_embed_token,
    get_workspace_report,
    env_value,
    list_workspace_reports_with_refresh,
    list_workspace_reports,
    resolve_workspace_dataset_id,
    resolve_dataset_roles,
)
from .resource_library import (
    get_resource,
    get_resource_path,
    list_resource_facets,
    list_resources,
    read_text_resource,
    save_uploaded_resource,
)
from .semantic_engine import build_availability_matrix_question, build_availability_question
from .power_automate import execute_dax_via_flow
from .openai_assistant import (
    chat_semantic_response_with_openai,
    interpret_semantic_answer_with_openai,
    is_openai_configured,
    parse_semantic_question_with_openai,
)
from .openai_service import generate_chat_response, extract_intent as openai_extract_intent
from .intent_extractor_service import extract_intent
from .dax_generator_service import generate_dax_from_intent, validate_intent, IntentValidationError
from .ai_config_service import (
    build_section_catalog,
    get_active_section_objects,
    get_active_sections,
    get_dax_template,
    get_filter_mapping,
    get_metric_mapping,
    get_prompt_template,
    get_question_examples,
    get_section_by_code,
    get_synonyms,
)
from .data_quality import (
    DataQualityContext,
    build_context_summary,
    compute_score,
    run_checks,
    serialize_result,
    available_checks,
)
from .models import (
    AIConfigSection,
    AIDaxTemplate,
    AIFilterMapping,
    AIBusinessRule,
    AIBusinessVocabulary,
    AIDebugRun,
    AIFewShotExample,
    AIKPITarget,
    AIMetricMapping,
    AIPowerBIPage,
    AIPromptTemplate,
    AIQuestionExample,
    AIRecommendedAction,
    AISemanticColumn,
    AISemanticMeasure,
    AISemanticRelationship,
    AISemanticTable,
    AISynonym,
    AIVisualMapping,
    BusinessPerformanceConfig,
    BusinessPerformanceMapping,
    DataBrowser,
    DataBrowserColumn,
    DataQualityRun,
    KnowledgeAILog,
    KnowledgeBusinessGlossary,
    KnowledgeBusinessRule,
    KnowledgeKPIDictionary,
    KnowledgeMiningTerminology,
    KnowledgePrompt,
    KnowledgeQuestion,
    KnowledgeRecommendedAction,
    KnowledgeSynonym,
    KnowledgeUserFeedback,
    PowerBIReport,
    SystemDatabaseConfig,
    SystemManagedTable,
)
from .business_performance_service import (
    BusinessPerformanceError,
    BusinessPerformanceService,
    MappingNotConfigured,
)
from .models import PlatformUser
from .access_control import has_module_access, is_platform_admin, user_module_access, wants_json
from .powerbi_interaction_orchestrator import process_user_question
from .ad_auth import exchange_code, fetch_me, login_url, search_directory_users
from .data_browsers import (
    DataBrowserValidationError,
    delete_browser_records,
    inspect_import_file,
    import_browser_records,
    import_browser_records_batch,
    get_import_job_status,
    insert_browser_record,
    lookup_options,
    preview_browser_data,
    start_import_job,
    sync_browser_sql,
    update_browser_record,
    validate_browser_definition,
)


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _normalize_snowflake_account(value: str) -> str:
    account = (value or "").strip()
    if not account:
        return ""
    account = account.removeprefix("https://").removeprefix("http://")
    account = account.replace(".snowflakecomputing.com", "")
    account = account.rstrip("/")
    return account


def _source_inventory(source):
    summary = {
        "label": "Inventory",
        "count": None,
        "custom_views": len(source.views),
    }

    engine = source.engine.lower()
    if engine == "sql server":
        summary["label"] = "Databases"
        try:
            with connect(
                server=source.server,
                database=source.database or "master",
                user=source.user or None,
                password=source.password or None,
                port=source.port or None,
            ) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM sys.databases
                    WHERE database_id > 4
                      AND state = 0
                    """
                )
                row = cursor.fetchone() or (0,)
            summary["count"] = int(row[0] or 0)
        except Exception:
            summary["count"] = None
        return summary

    if engine == "snowflake":
        summary["label"] = "Schemas"
        if snowflake_connector is None:
            return summary
        account = source.connection_details.get("account") or source.server
        warehouse = source.connection_details.get("warehouse")
        role = source.connection_details.get("role") or None
        database = source.database or source.connection_details.get("database") or None
        if not account or not warehouse or not source.user:
            return summary
        try:
            connect_kwargs = {
                "account": _normalize_snowflake_account(account),
                "user": source.user,
                "password": source.password or None,
                "warehouse": warehouse,
                "role": role,
            }
            if database:
                connect_kwargs["database"] = database
            connection = snowflake_connector.connect(**connect_kwargs)
            try:
                cursor = connection.cursor()
                if database:
                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM INFORMATION_SCHEMA.SCHEMATA
                        WHERE SCHEMA_NAME <> 'INFORMATION_SCHEMA'
                        """
                    )
                else:
                    cursor.execute("SHOW SCHEMAS IN ACCOUNT")
                row = cursor.fetchone() or (0,)
            finally:
                connection.close()
            summary["count"] = int(row[0] or 0)
        except Exception:
            summary["count"] = None

    return summary


def _source_databases(source):
    databases = []
    if source.engine.lower() != "sql server":
        return databases

    connection_targets = [source.database or "master"]
    if connection_targets[0].lower() != "master":
        connection_targets.append("master")

    for database_name in connection_targets:
        try:
            with connect(
                server=source.server,
                database=database_name,
                user=source.user or None,
                password=source.password or None,
                port=source.port or None,
            ) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    SELECT name
                    FROM sys.databases
                    WHERE database_id > 4
                      AND state = 0
                    ORDER BY name
                    """
                )
                databases = [str(row[0]) for row in cursor.fetchall() or [] if row and row[0]]
                break
        except Exception:
            databases = []

    selected = (source.database or "").strip()
    if selected and selected not in databases:
        databases.insert(0, selected)
    return databases


def _source_catalog(source):
    catalog = {
            "tables": [],
            "views": [],
            "custom_views": [
                {
                    "key": view.key,
                    "name": view.name,
                    "description": view.description,
                    "sql": view.sql,
                    "preview_url": reverse("source-object-preview", args=[source.key, "custom", view.key]),
                    "edit_url": reverse("source-custom-view-edit", args=[source.key, view.key]),
                    "delete_url": reverse("source-custom-view-delete", args=[source.key, view.key]),
                }
                for view in source.views
            ],
        }

    if source.engine.lower() != "sql server":
        return catalog

    try:
        with connect(
            server=source.server,
            database=source.database or "master",
            user=source.user or None,
            password=source.password or None,
            port=source.port or None,
        ) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT s.name AS schema_name, t.name AS table_name
                FROM sys.tables t
                INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                WHERE t.is_ms_shipped = 0
                ORDER BY s.name, t.name
                """
            )
            catalog["tables"] = [
                {
                    "schema": row[0],
                    "name": row[1],
                    "qualified_name": f"{row[0]}.{row[1]}",
                    "preview_url": reverse("source-object-preview", args=[source.key, "table", f"{row[0]}.{row[1]}"]),
                }
                for row in cursor.fetchall() or []
            ]

            cursor.execute(
                """
                SELECT s.name AS schema_name, v.name AS view_name
                FROM sys.views v
                INNER JOIN sys.schemas s ON s.schema_id = v.schema_id
                WHERE v.is_ms_shipped = 0
                ORDER BY s.name, v.name
                """
            )
            catalog["views"] = [
                {
                    "schema": row[0],
                    "name": row[1],
                    "qualified_name": f"{row[0]}.{row[1]}",
                    "preview_url": reverse("source-object-preview", args=[source.key, "view", f"{row[0]}.{row[1]}"]),
                }
                for row in cursor.fetchall() or []
            ]
    except Exception:
        pass

    return catalog


def _normalize_preview_limit(value):
    text = str(value or "").strip().lower()
    if not text or text == "1000":
        return 1000
    if text == "all":
        return None
    try:
        parsed = int(text)
    except ValueError:
        return 1000
    return max(parsed, 1)


def _normalize_preview_operator(value):
    operator = str(value or "equal").strip().lower()
    return operator if operator in {"equal", "like"} else "equal"


def _normalize_preview_joiner(value):
    joiner = str(value or "AND").strip().upper()
    return joiner if joiner in {"AND", "OR"} else "AND"


def _parse_preview_filters(raw_filters):
    if not raw_filters:
        return []

    if isinstance(raw_filters, str):
        try:
            payload = json.loads(raw_filters)
        except Exception:
            return []
    elif isinstance(raw_filters, list):
        payload = raw_filters
    else:
        return []

    if not isinstance(payload, list):
        return []

    filters = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column") or item.get("column_name") or "").strip()
        value = item.get("value")
        if not column or value is None or str(value).strip() == "":
            continue
        filters.append(
            {
                "column": column,
                "operator": _normalize_preview_operator(item.get("operator")),
                "value": str(value),
                "joiner": _normalize_preview_joiner(item.get("joiner")),
                "type": str(item.get("type") or "").strip().lower(),
            }
        )
    return filters


def _escape_sql_identifier(value: str) -> str:
    return f"[{str(value).replace(']', ']]')}]"


def _quote_sql_literal(value: str, force_text: bool = False) -> str:
    text = str(value or "").replace("'", "''")
    return f"N'{text}'" if force_text else f"'{text}'"


def _preview_sql_literal(value: str, preview_type: str) -> str:
    text = str(value or "").strip()
    if preview_type == "number" and text:
        try:
            float(text)
        except ValueError:
            return _quote_sql_literal(text, force_text=True)
        return text
    return _quote_sql_literal(text, force_text=True)


def _normalize_object_identifier(value: str) -> str:
    return unquote(str(value or "").strip()).rstrip("/").strip()


def _build_preview_filter_clause(filter_data: dict) -> str:
    column = _escape_sql_identifier(filter_data["column"])
    operator = _normalize_preview_operator(filter_data.get("operator"))
    value = str(filter_data.get("value") or "").strip()
    preview_type = str(filter_data.get("type") or "").strip().lower()

    if preview_type == "date":
        return f"CONVERT(date, {column}) = {_quote_sql_literal(value[:10], force_text=True)}"

    if operator == "like":
        return f"{column} LIKE {_quote_sql_literal(f'%{value}%', force_text=True)}"

    if preview_type == "number":
        return f"{column} = {_preview_sql_literal(value, 'number')}"

    return f"{column} = {_quote_sql_literal(value, force_text=True)}"


def _build_preview_sql(object_sql: str, filters: list[dict], limit_value):
    preview_limit = _normalize_preview_limit(limit_value)
    select_prefix = "SELECT *" if preview_limit is None else f"SELECT TOP ({preview_limit}) *"
    sql = f"{select_prefix}\nFROM {object_sql}"

    active_filters = [item for item in filters if str(item.get("value") or "").strip()]
    if active_filters:
        clauses = []
        for index, filter_data in enumerate(active_filters):
            clause = _build_preview_filter_clause(filter_data)
            if index == 0:
                clauses.append(f"({clause})")
            else:
                joiner = _normalize_preview_joiner(filter_data.get("joiner"))
                clauses.append(f"{joiner} ({clause})")
        sql += "\nWHERE " + " ".join(clauses)
    return sql


def _table_preview_sql(qualified_name: str, limit="1000") -> str:
    parts = [part.strip("[] ") for part in qualified_name.split(".", 1)]
    if len(parts) != 2 or not all(parts):
        raise ValueError("Invalid table identifier.")
    schema, table = parts
    object_sql = f"{_escape_sql_identifier(schema)}.{_escape_sql_identifier(table)}"
    return _build_preview_sql(object_sql, [], limit)


def _preview_column_type(value) -> str:
    from datetime import date as _date, datetime as _datetime
    from decimal import Decimal as _decimal

    if value is None:
        return "text"
    if isinstance(value, bool):
        return "text"
    if isinstance(value, (_datetime, _date)):
        return "date"
    if isinstance(value, (int, float, _decimal)):
        return "number"

    text = str(value).strip()
    if not text:
        return "text"
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return "date"
    return "text"


def _fetch_query_preview(source, sql: str, object_name: str) -> dict:
    with connect(
        server=source.server,
        database=source.database or "master",
        user=source.user or None,
        password=source.password or None,
        port=source.port or None,
    ) as connection:
        cursor = connection.cursor()
        rows = cursor.execute(sql).fetchall()
        columns = [column[0] for column in cursor.description or []]

    column_types = []
    for column_index, _column in enumerate(columns):
        detected_type = "text"
        for row in rows:
            sample_value = row[column_index] if column_index < len(row) else None
            detected_type = _preview_column_type(sample_value)
            if detected_type != "text" or sample_value not in (None, ""):
                break
        column_types.append(detected_type)

    records = [
        {column: _json_safe(value) for column, value in zip(columns, row)}
        for row in rows
    ]
    row_values = [
        [_json_safe(value) for value in row]
        for row in rows
    ]
    return {
        "sql": sql,
        "columns": columns,
        "column_types": column_types,
        "rows": records,
        "row_values": row_values,
        "row_count": len(records),
        "qualified_name": object_name,
    }


def _preview_payload_from_url(source, preview_url: str) -> dict:
    if not preview_url:
        raise ValueError("No preview target selected.")

    object_sql, object_name, target = _resolve_preview_object(source, preview_url)

    sql = f"SELECT *\nFROM {object_sql}"
    preview = _fetch_query_preview(source, sql, object_name)
    return {
        "kind": target["kind"],
        "identifier": target["identifier"],
        "sql": sql,
        "preview": preview,
        "object_name": object_name,
    }


def _resolve_preview_target_from_url(source, preview_url: str) -> dict:
    if not preview_url:
        raise ValueError("No preview target selected.")

    parsed = urlparse(preview_url)
    path = parsed.path or preview_url
    object_sql, object_name, target = _resolve_preview_object(source, preview_url)

    return {
        "kind": target["kind"],
        "identifier": target["identifier"],
        "object_name": object_name,
    }


def _resolve_preview_object(source, preview_url: str) -> tuple[str, str, dict]:
    parsed = urlparse(preview_url)
    path = parsed.path or preview_url
    match = re.search(
        r"/data-sources/(?P<source_key>[^/]+)/preview/(?P<kind>[^/]+)/(?P<identifier>.+?)/?$",
        path,
    )
    if match and match.group("source_key").lower() != source.key.lower():
        raise ValueError("Preview source mismatch.")

    if match:
        kind = match.group("kind").strip().lower()
        identifier = _normalize_object_identifier(match.group("identifier"))
    else:
        table_match = re.search(
            r"/data-sources/(?P<source_key>[^/]+)/tables/(?P<identifier>.+?)/preview/?$",
            path,
        )
        if not table_match:
            raise ValueError("Unsupported preview target.")
        if table_match.group("source_key").lower() != source.key.lower():
            raise ValueError("Preview source mismatch.")
        kind = "table"
        identifier = _normalize_object_identifier(table_match.group("identifier"))

    if kind in {"table", "tables", "view", "views"}:
        object_sql = ".".join(_escape_sql_identifier(part.strip("[] ")) for part in identifier.split(".", 1))
        object_name = identifier
    elif kind in {"custom", "custom-view", "custom_view"}:
        _, view = get_live_view(source.key, identifier)
        object_sql = f"(\n{view.sql}\n) AS dq_source"
        object_name = view.name
    else:
        raise ValueError("Unknown preview object type.")

    return object_sql, object_name, {
        "kind": kind,
        "identifier": identifier,
        "object_name": object_name,
    }


def _preview_export_rows(source, preview_url: str, filters: list[dict] | None = None) -> dict:
    object_sql, object_name, target = _resolve_preview_object(source, preview_url)
    sql = _build_preview_sql(object_sql, filters or [], "all")
    preview = _fetch_query_preview(source, sql, object_name)
    return {
        "kind": target["kind"],
        "identifier": target["identifier"],
        "object_name": object_name,
        "sql": sql,
        "preview": preview,
    }


def _rows_from_preview_snapshot(preview_snapshot: dict) -> list[dict]:
    if not isinstance(preview_snapshot, dict):
        return []

    rows = preview_snapshot.get("rows")
    if isinstance(rows, list):
        return rows

    columns = preview_snapshot.get("columns") if isinstance(preview_snapshot.get("columns"), list) else []
    row_values = preview_snapshot.get("row_values")
    if not isinstance(row_values, list) or not columns:
        return []

    normalized_rows = []
    for row in row_values:
        if not isinstance(row, (list, tuple)):
            continue
        normalized_rows.append({column: value for column, value in zip(columns, row)})
    return normalized_rows


def _data_quality_context_from_request(source, preview_url: str, request_payload: dict | None = None) -> tuple[DataQualityContext, dict]:
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    embedded_preview = request_payload.get("preview") if isinstance(request_payload, dict) else None
    if isinstance(embedded_preview, dict) and embedded_preview.get("columns") is not None:
        target = _resolve_preview_target_from_url(source, preview_url)
        rows = _rows_from_preview_snapshot(embedded_preview)
        preview = {
            "sql": embedded_preview.get("sql") or "",
            "columns": embedded_preview.get("columns") or [],
            "column_types": embedded_preview.get("column_types") or [],
            "rows": rows,
            "row_values": embedded_preview.get("row_values") or [],
            "row_count": embedded_preview.get("row_count") or len(rows),
            "qualified_name": embedded_preview.get("qualified_name") or target["object_name"],
            "filters": embedded_preview.get("filters") or [],
            "limit": embedded_preview.get("limit") or "1000",
        }
        payload = {
            "kind": target["kind"],
            "identifier": target["identifier"],
            "sql": embedded_preview.get("sql") or "",
            "preview": preview,
            "object_name": target["object_name"],
        }
    else:
        payload = _preview_payload_from_url(source, preview_url)
        preview = payload["preview"]
    previous_run = (
        DataQualityRun.objects.filter(
            source_key=source.key,
            object_kind=payload["kind"],
            object_name=payload["object_name"],
            status="Completed",
        )
        .order_by("-created_at")
        .first()
    )
    previous_summary = {}
    if previous_run and isinstance(previous_run.summary, dict):
        previous_summary = previous_run.summary

    context = DataQualityContext(
        source_key=source.key,
        source_name=source.name,
        object_kind=payload["kind"],
        object_name=payload["object_name"],
        columns=preview.get("columns", []),
        column_types=preview.get("column_types", []),
        records=preview.get("rows", []),
        preview_url=preview_url,
        previous_summary=previous_summary,
        metadata=(request_payload or {}).get("metadata", {}) if isinstance(request_payload, dict) else {},
    )
    return context, payload


def _run_data_quality(source, preview_url: str, control_key: str | None = None, request_payload: dict | None = None):
    context, payload = _data_quality_context_from_request(source, preview_url, request_payload)
    keys = [control_key] if control_key else None
    results = run_checks(context, keys)
    summary = build_context_summary(context)
    score = compute_score(results)
    stored_payload = dict(request_payload or {})
    stored_payload["preview_url"] = preview_url
    run = DataQualityRun.objects.create(
        source_key=source.key,
        source_name=source.name,
        object_kind=context.object_kind,
        object_name=context.object_name,
        run_type="single" if control_key else "all",
        status="Completed",
        score=score,
        total_rows=context.row_count,
        controls_count=len(results),
        summary=summary,
        results=[serialize_result(result) for result in results],
        request_payload=stored_payload,
        finished_at=timezone.now(),
    )
    return run, context, payload, results, summary, score


def _is_ajax_request(request) -> bool:
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _user_is_platform_admin(user) -> bool:
    return is_platform_admin(user)


def _platform_role_payload(data) -> dict:
    is_admin = data.get("is_platform_admin") == "on"
    scope = {}
    if not is_admin:
        for field, scope_key in (("bp_scope_countries", "country"), ("bp_scope_customers", "customer")):
            values = [item.strip() for item in data.get(field, "").split(",") if item.strip()]
            if values:
                scope[scope_key] = values
        if data.get("bp_rls_role", "").strip():
            scope["rls_role"] = data.get("bp_rls_role", "").strip()
    return {
        "is_platform_admin": is_admin,
        "can_access_reporting": is_admin or data.get("can_access_reporting") == "on",
        "can_access_ai": is_admin or data.get("can_access_ai") == "on",
        "can_access_data": is_admin or data.get("can_access_data") == "on",
        "can_access_sources": is_admin or data.get("can_access_sources") == "on",
        "business_performance_role": "Administrator" if is_admin else data.get("business_performance_role", ""),
        "business_performance_scope": scope,
    }


def login_page(request):
    if request.user.is_authenticated:
        return redirect(request.GET.get("next") or "dashboard")
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if username == "djibril" and password == "djibril" and not User.objects.filter(username="djibril").exists():
            user, _ = User.objects.get_or_create(username="djibril")
            user.set_password("djibril")
            user.email = "djibril@local.mining360ia"
            user.first_name = "Djibril"
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.save()
            PlatformUser.objects.update_or_create(
                user_principal_name="djibril@local.mining360ia",
                defaults={
                    "azure_ad_id": "local-djibril",
                    "email": "djibril@local.mining360ia",
                    "display_name": "Djibril",
                    "job_title": "Super Admin",
                    "is_active": True,
                    "is_platform_admin": True,
                    "can_access_reporting": True,
                    "can_access_ai": True,
                    "can_access_data": True,
                    "can_access_sources": True,
                    "business_performance_role": "Administrator",
                    "django_user": user,
                },
            )
        authenticated_user = authenticate(request, username=username, password=password)
        if authenticated_user and authenticated_user.is_active:
            platform_user = getattr(authenticated_user, "platformuser", None)
            if platform_user and platform_user.is_active:
                django_login(request, authenticated_user)
                return redirect(next_url or "dashboard")
            if authenticated_user.is_superuser or authenticated_user.is_staff:
                django_login(request, authenticated_user)
                return redirect(next_url or "dashboard")
            messages.error(request, "Your Mining360 profile is inactive or not authorized.")
            return render(request, "reports/login.html", {"next": next_url, "username": username})
        messages.error(request, "Invalid local username or password.")
    return render(request, "reports/login.html", {"next": next_url, "username": request.POST.get("username", "")})


def auth_start(request):
    request.session["login_next"] = request.GET.get("next") or request.POST.get("next") or "/"
    return redirect(login_url(request))


def auth_callback(request):
    expected_state = request.session.get("azure_ad_state")
    received_state = request.GET.get("state")
    if not expected_state or received_state != expected_state:
        messages.error(request, "Invalid Microsoft sign-in state.")
        return redirect("login")
    if request.GET.get("error"):
        messages.error(request, request.GET.get("error_description") or request.GET.get("error"))
        return redirect("login")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "Microsoft sign-in did not return an authorization code.")
        return redirect("login")

    try:
        token = exchange_code(request, code)
        profile = fetch_me(token["access_token"])
    except Exception as exc:
        messages.error(request, str(exc))
        return redirect("login")

    upn = (profile.get("userPrincipalName") or profile.get("mail") or "").strip().lower()
    azure_id = profile.get("id", "")
    if not upn or not azure_id:
        messages.error(request, "Microsoft profile is missing userPrincipalName or id.")
        return redirect("login")

    first_platform_user = not PlatformUser.objects.exists()
    platform_user = PlatformUser.objects.filter(azure_ad_id=azure_id).first() or PlatformUser.objects.filter(user_principal_name=upn).first()
    if not platform_user and first_platform_user:
        platform_user = PlatformUser.objects.create(
            azure_ad_id=azure_id,
            user_principal_name=upn,
            email=profile.get("mail") or upn,
            display_name=profile.get("displayName") or upn,
            job_title=profile.get("jobTitle") or "",
            is_active=True,
            is_platform_admin=True,
            can_access_reporting=True,
            can_access_ai=True,
            can_access_data=True,
            can_access_sources=True,
            business_performance_role="Administrator",
        )
    if not platform_user or not platform_user.is_active:
        messages.error(request, "Your account is not authorized for Mining360.")
        return redirect("login")

    user, _ = User.objects.get_or_create(
        username=upn,
        defaults={
            "email": platform_user.email or upn,
            "first_name": platform_user.display_name[:150],
            "is_staff": platform_user.is_platform_admin,
            "is_superuser": platform_user.is_platform_admin,
        },
    )
    user.email = platform_user.email or upn
    user.first_name = platform_user.display_name[:150]
    user.is_active = platform_user.is_active
    user.is_staff = platform_user.is_platform_admin
    user.is_superuser = platform_user.is_platform_admin
    user.save()
    platform_user.django_user = user
    platform_user.azure_ad_id = azure_id
    platform_user.user_principal_name = upn
    platform_user.email = profile.get("mail") or upn
    platform_user.display_name = profile.get("displayName") or platform_user.display_name
    platform_user.job_title = profile.get("jobTitle") or platform_user.job_title
    platform_user.save()
    django_login(request, user)
    return redirect(request.session.pop("login_next", None) or "dashboard")


def logout_page(request):
    django_logout(request)
    return redirect("login")


@login_required
def users_manage(request):
    if not _user_is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    query = request.GET.get("q", "").strip()
    directory_results = []
    search_error = ""
    if query:
        try:
            directory_results = search_directory_users(query)
            for person in directory_results:
                person["primary_email"] = person.get("mail") or person.get("userPrincipalName") or ""
        except Exception as exc:
            search_error = str(exc)
    return render(
        request,
        "reports/users.html",
        {
            "active_section": "users",
            "query": query,
            "directory_results": directory_results,
            "search_error": search_error,
            "platform_users": PlatformUser.objects.all(),
            "role_choices": PlatformUser.ROLE_CHOICES,
            "bp_role_choices": PlatformUser.BUSINESS_PERFORMANCE_ROLES,
            "sidebar_stats": [
                {"label": "Users", "value": PlatformUser.objects.count()},
                {"label": "Auth", "value": "AD"},
            ],
        },
    )


@login_required
def users_add(request):
    if not _user_is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    if request.method != "POST":
        return redirect("users-manage")
    azure_id = request.POST.get("azure_ad_id", "").strip()
    upn = request.POST.get("user_principal_name", "").strip().lower()
    display_name = request.POST.get("display_name", "").strip() or upn
    email = request.POST.get("email", "").strip() or upn
    job_title = request.POST.get("job_title", "").strip()
    role_payload = _platform_role_payload(request.POST)
    if not azure_id or not upn:
        messages.error(request, "Missing Azure AD user id or user principal name.")
        return redirect("users-manage")
    platform_user, _ = PlatformUser.objects.update_or_create(
        azure_ad_id=azure_id,
        defaults={
            "user_principal_name": upn,
            "email": email,
            "display_name": display_name,
            "job_title": job_title,
            "is_active": True,
            **role_payload,
        },
    )
    messages.success(request, f"{platform_user.display_name} added to Mining360.")
    return redirect("users-manage")


@login_required
def users_toggle(request, user_id):
    if not _user_is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    platform_user = get_object_or_404(PlatformUser, id=user_id)
    if request.method == "POST":
        platform_user.is_active = not platform_user.is_active
        platform_user.save()
        messages.success(request, f"{platform_user.display_name} status updated.")
    return redirect("users-manage")


@login_required
def users_roles_update(request, user_id):
    if not _user_is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    if request.method != "POST":
        return redirect("users-manage")
    platform_user = get_object_or_404(PlatformUser, id=user_id)
    for field, value in _platform_role_payload(request.POST).items():
        setattr(platform_user, field, value)
    platform_user.save()
    if platform_user.django_user_id:
        platform_user.django_user.is_staff = platform_user.is_platform_admin
        platform_user.django_user.is_superuser = platform_user.is_platform_admin
        platform_user.django_user.save(update_fields=["is_staff", "is_superuser"])
    messages.success(request, f"{platform_user.display_name} roles updated.")
    return redirect("users-manage")


def dashboard(request):
    module_access = user_module_access(request.user)
    modules = [
        {
            "name": "Reporting",
            "description": "Open and control the focused Power BI reports.",
            "url_name": "reporting",
            "module": "reporting",
        },
        {
            "name": "AI",
            "description": "OpenAI-powered analysis and assistance workflows.",
            "url_name": "ai-home",
            "module": "ai",
        },
        {
            "name": "Sources",
            "description": "Catalog and monitor Mining360 data connections.",
            "url_name": "data-sources",
            "module": "sources",
        },
        {
            "name": "Data",
            "description": "Analyze datasets, run checks and prepare operational data workflows.",
            "url_name": "data-home",
            "module": "data",
        },
        {
            "name": "Resources",
            "description": "Search CAT reference documents and knowledge resources.",
            "url_name": "resources",
        },
    ]
    if _user_is_platform_admin(request.user):
        modules.insert(
            2,
            {
                "name": "IA Config",
                "description": "Configure intent extraction, glossary, mappings and DAX templates.",
                "url_name": "ia-config-home",
            },
        )
    modules = [
        item
        for item in modules
        if (
            (not item.get("module") or module_access.get(item["module"]) or _user_is_platform_admin(request.user))
        )
    ]
    return render(
        request,
        "reports/dashboard.html",
        {
            "modules": modules,
            "active_section": "dashboard",
            "sidebar_stats": [
                {"label": "Modules", "value": len(modules)},
                {"label": "Mode", "value": "Admin"},
            ],
        },
    )


def data_home(request):
    cards = [
        {
            "name": "Data Quality Center",
            "description": "Run quality controls, inspect failed records and export impacted rows.",
            "url_name": "data-quality-center",
        },
        {
            "name": "Source Data Preview",
            "description": "Open registered sources and explore tables, views and custom views.",
            "url_name": "data-sources",
        },
    ]
    browsers = DataBrowser.objects.prefetch_related("columns").all()
    return render(
        request,
        "reports/data_home.html",
        {
            "cards": cards,
            "browsers": [_browser_payload(browser, include_columns=False) for browser in browsers],
            "browser_state": [_browser_payload(browser, include_columns=True) for browser in browsers],
            "active_section": "data",
            "sidebar_stats": [
                {"label": "Workflows", "value": len(cards)},
                {"label": "Focus", "value": "Data"},
            ],
        },
    )


def _request_payload(request) -> dict:
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return request.POST.dict()


def _browser_column_payload(column: DataBrowserColumn) -> dict:
    return {
        "id": column.id,
        "display_name": column.display_name,
        "sql_name": column.sql_name,
        "data_type": column.data_type,
        "length": column.length,
        "is_required": column.is_required,
        "is_unique": column.is_unique,
        "default_value": column.default_value,
        "display_order": column.display_order,
        "is_visible": column.is_visible,
        "is_lookup": column.is_lookup,
        "lookup_source_name": column.lookup_source_name,
        "lookup_value_column": column.lookup_value_column,
        "lookup_label_column": column.lookup_label_column,
        "lookup_filter": column.lookup_filter,
    }


def _browser_payload(browser: DataBrowser, include_columns: bool = True) -> dict:
    payload = {
        "id": browser.id,
        "name": browser.name,
        "display_order": browser.display_order,
        "description": browser.description,
        "table_name": browser.table_name,
        "source_view_name": browser.source_view_name,
        "is_active": browser.is_active,
        "show_browser_record_id": browser.show_browser_record_id,
        "show_eventchain_id": browser.show_eventchain_id,
        "last_synced_at": browser.last_synced_at.isoformat() if browser.last_synced_at else "",
        "last_sync_status": browser.last_sync_status,
        "last_sync_message": browser.last_sync_message,
        "created_at": browser.created_at.isoformat() if browser.created_at else "",
        "updated_at": browser.updated_at.isoformat() if browser.updated_at else "",
    }
    if include_columns:
        payload["columns"] = [_browser_column_payload(column) for column in browser.columns.all()]
    return payload


def _bool_payload(payload: dict, key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _int_payload(payload: dict, key: str, default: int | None = None) -> int | None:
    value = payload.get(key)
    if value in (None, ""):
        return default
    return int(value)


def _apply_browser_payload(browser: DataBrowser, payload: dict) -> DataBrowser:
    browser.name = str(payload.get("name", browser.name or "")).strip()
    browser.description = str(payload.get("description", browser.description or "")).strip()
    browser.table_name = str(payload.get("table_name", browser.table_name or "")).strip()
    browser.source_view_name = str(payload.get("source_view_name", browser.source_view_name or "")).strip()
    browser.is_active = _bool_payload(payload, "is_active", browser.is_active)
    browser.show_browser_record_id = _bool_payload(
        payload, "show_browser_record_id", browser.show_browser_record_id
    )
    browser.show_eventchain_id = _bool_payload(
        payload, "show_eventchain_id", browser.show_eventchain_id
    )
    if not browser.name:
        raise DataBrowserValidationError("Browser name is required.")
    if not browser.table_name:
        raise DataBrowserValidationError("SQL table name is required.")
    if not browser.source_view_name:
        raise DataBrowserValidationError("Source view name is required.")
    return browser


def _apply_column_payload(column: DataBrowserColumn, payload: dict) -> DataBrowserColumn:
    column.display_name = str(payload.get("display_name", column.display_name or "")).strip()
    column.sql_name = str(payload.get("sql_name", column.sql_name or "")).strip()
    column.data_type = str(payload.get("data_type", column.data_type or "Text")).strip()
    column.length = _int_payload(payload, "length", column.length)
    if "allow_null" in payload:
        column.is_required = not _bool_payload(payload, "allow_null", not column.is_required)
    else:
        column.is_required = _bool_payload(payload, "is_required", column.is_required)
    column.is_unique = _bool_payload(payload, "is_unique", column.is_unique)
    column.default_value = str(payload.get("default_value", column.default_value or "")).strip()
    column.display_order = _int_payload(payload, "display_order", column.display_order or 0) or 0
    column.is_visible = _bool_payload(payload, "is_visible", column.is_visible)
    column.is_lookup = _bool_payload(payload, "is_lookup", column.is_lookup)
    column.lookup_source_name = str(payload.get("lookup_source_name", column.lookup_source_name or "")).strip()
    column.lookup_value_column = str(payload.get("lookup_value_column", column.lookup_value_column or "")).strip()
    column.lookup_label_column = str(payload.get("lookup_label_column", column.lookup_label_column or "")).strip()
    column.lookup_filter = str(payload.get("lookup_filter", column.lookup_filter or "")).strip()
    if not column.display_name:
        raise DataBrowserValidationError("Column display name is required.")
    if not column.sql_name:
        raise DataBrowserValidationError("Column SQL name is required.")
    if column.data_type not in dict(DataBrowserColumn.DATA_TYPES):
        raise DataBrowserValidationError("Invalid column data type.")
    return column


def _json_error(message: str, status: int = 400):
    return JsonResponse({"ok": False, "error": message}, status=status)


@require_http_methods(["GET", "POST"])
def data_browsers_api(request):
    if request.method == "GET":
        browsers = DataBrowser.objects.prefetch_related("columns").all()
        return JsonResponse({"ok": True, "browsers": [_browser_payload(browser, include_columns=False) for browser in browsers]})
    try:
        browser = _apply_browser_payload(DataBrowser(), _request_payload(request))
        browser.display_order = (
            DataBrowser.objects.aggregate(max_order=models.Max("display_order")).get("max_order") or 0
        ) + 1
        browser.save()
        validate_browser_definition(browser)
        sync_browser_sql(browser)
    except Exception as exc:
        if "browser" in locals() and browser.pk:
            browser.delete()
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "browser": _browser_payload(browser)}, status=201)


@require_http_methods(["POST"])
def data_browsers_reorder_api(request):
    payload = _request_payload(request)
    raw_ids = payload.get("browser_ids")
    if not isinstance(raw_ids, list):
        return _json_error("browser_ids must be a list.")
    try:
        browser_ids = [int(browser_id) for browser_id in raw_ids]
    except (TypeError, ValueError):
        return _json_error("Every Browser ID must be an integer.")
    if len(browser_ids) != len(set(browser_ids)):
        return _json_error("The Browser order contains duplicate IDs.")

    browsers = list(DataBrowser.objects.all())
    existing_ids = {browser.id for browser in browsers}
    if set(browser_ids) != existing_ids:
        return _json_error("The submitted order must contain every Browser exactly once.")

    browsers_by_id = {browser.id: browser for browser in browsers}
    with transaction.atomic():
        for position, browser_id in enumerate(browser_ids, start=1):
            browsers_by_id[browser_id].display_order = position
        DataBrowser.objects.bulk_update(browsers, ["display_order"])
    return JsonResponse({
        "ok": True,
        "browsers": [
            _browser_payload(browsers_by_id[browser_id], include_columns=False)
            for browser_id in browser_ids
        ],
    })


@require_http_methods(["GET", "PUT", "DELETE"])
def data_browser_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    if request.method == "GET":
        return JsonResponse({"ok": True, "browser": _browser_payload(browser)})
    if request.method == "DELETE":
        browser.delete()
        return JsonResponse({"ok": True})
    try:
        browser = _apply_browser_payload(browser, _request_payload(request))
        validate_browser_definition(browser)
        browser.save()
        sync_browser_sql(browser)
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "browser": _browser_payload(browser)})


@require_http_methods(["POST"])
def data_browser_columns_api(request, browser_id):
    browser = get_object_or_404(DataBrowser, id=browser_id)
    try:
        column = _apply_column_payload(DataBrowserColumn(browser=browser), _request_payload(request))
        column.save()
        validate_browser_definition(browser)
        sync_browser_sql(browser)
    except Exception as exc:
        if "column" in locals() and column.pk:
            column.delete()
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "column": _browser_column_payload(column)}, status=201)


@require_http_methods(["POST"])
def data_browser_columns_reorder_api(request, browser_id):
    browser = get_object_or_404(DataBrowser, id=browser_id)
    payload = _request_payload(request)
    raw_ids = payload.get("column_ids")
    if not isinstance(raw_ids, list):
        return _json_error("column_ids must be a list.")

    try:
        column_ids = [int(column_id) for column_id in raw_ids]
    except (TypeError, ValueError):
        return _json_error("Every column ID must be an integer.")

    if len(column_ids) != len(set(column_ids)):
        return _json_error("The column order contains duplicate IDs.")

    columns = list(browser.columns.all())
    existing_ids = {column.id for column in columns}
    if set(column_ids) != existing_ids:
        return _json_error("The submitted order must contain every Browser column exactly once.")

    columns_by_id = {column.id: column for column in columns}
    with transaction.atomic():
        for position, column_id in enumerate(column_ids, start=1):
            column = columns_by_id[column_id]
            column.display_order = position
        DataBrowserColumn.objects.bulk_update(columns, ["display_order"])

    ordered_columns = [columns_by_id[column_id] for column_id in column_ids]
    return JsonResponse({
        "ok": True,
        "columns": [_browser_column_payload(column) for column in ordered_columns],
    })


@require_http_methods(["PUT", "DELETE"])
def data_browser_column_api(request, browser_id, column_id):
    browser = get_object_or_404(DataBrowser, id=browser_id)
    column = get_object_or_404(DataBrowserColumn, browser=browser, id=column_id)
    if request.method == "DELETE":
        column.delete()
        return JsonResponse({"ok": True})
    try:
        column = _apply_column_payload(column, _request_payload(request))
        column.save()
        validate_browser_definition(browser)
        sync_browser_sql(browser)
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "column": _browser_column_payload(column)})


@require_http_methods(["POST"])
def data_browser_sync_sql_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    try:
        result = sync_browser_sql(browser)
    except Exception as exc:
        browser.last_sync_status = "Failed"
        browser.last_sync_message = str(exc)
        browser.last_synced_at = timezone.now()
        browser.save(update_fields=["last_sync_status", "last_sync_message", "last_synced_at", "updated_at"])
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "result": result, "browser": _browser_payload(browser)})


@require_http_methods(["POST"])
def data_browser_import_preview_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return _json_error("Import file is required.")
    try:
        result = inspect_import_file(uploaded_file)
    except Exception as exc:
        return _json_error(str(exc))
    browser_payload = _browser_payload(browser)
    browser_payload["columns"] = [
        {
            "id": column.id,
            "display_name": column.display_name,
            "sql_name": column.sql_name,
            "data_type": column.data_type,
            "is_required": column.is_required,
            "is_unique": column.is_unique,
            "default_value": column.default_value,
            "is_lookup": column.is_lookup,
        }
        for column in browser.columns.all()
    ]
    return JsonResponse({"ok": True, "import_preview": result, "browser": browser_payload})


@require_http_methods(["POST"])
def data_browser_import_batch_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    payload = _request_payload(request)
    token = str(payload.get("token") or "").strip()
    if not token:
        return _json_error("Import token is required.")
    try:
        mapping_raw = payload.get("mapping", "{}")
        mapping = json.loads(mapping_raw) if isinstance(mapping_raw, str) else (mapping_raw if isinstance(mapping_raw, dict) else {})
    except Exception:
        mapping = {}
    try:
        result = import_browser_records_batch(
            browser,
            token,
            mapping=mapping,
            start=int(payload.get("start", 0) or 0),
            batch_size=int(payload.get("batch_size", 50) or 50),
        )
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "import": result})


@require_http_methods(["POST"])
def data_browser_import_start_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    payload = _request_payload(request)
    token = str(payload.get("token") or "").strip()
    if not token:
        return _json_error("Import token is required.")
    try:
        mapping_raw = payload.get("mapping", {})
        mapping = json.loads(mapping_raw) if isinstance(mapping_raw, str) else (mapping_raw if isinstance(mapping_raw, dict) else {})
        result = start_import_job(browser, token, mapping=mapping)
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "import": result})


@require_http_methods(["GET"])
def data_browser_import_status_api(request, job_token):
    try:
        result = get_import_job_status(job_token)
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "status": result})


@require_http_methods(["GET"])
def data_browser_data_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    try:
        result = preview_browser_data(
            browser,
            limit=request.GET.get("limit", "100"),
            filters=request.GET.get("filters", "[]"),
        )
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "data": result})


@require_http_methods(["GET"])
def data_browser_export_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    try:
        payload = preview_browser_data(
            browser,
            limit=request.GET.get("limit", "1000"),
            filters=request.GET.get("filters", "[]"),
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    try:
        from io import BytesIO
        from openpyxl import Workbook
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Excel export unavailable: {exc}"}, status=500)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (browser.name or "Browser")[:31]
    columns = list(payload.get("columns") or [])
    rows = list(payload.get("rows") or [])
    if columns:
        sheet.append(columns)
        for record in rows:
            sheet.append([_json_safe(record.get(column)) for column in columns])
        if not rows:
            sheet.append(["No rows returned"])
    else:
        sheet.append(["No rows returned"])

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = f"{browser.table_name or browser.name or 'browser'}_export.xlsx".replace(" ", "_")
    response = FileResponse(buffer, as_attachment=True, filename=filename)
    response["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response


@require_http_methods(["POST"])
def data_browser_records_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    try:
        result = insert_browser_record(browser, _request_payload(request))
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "record": result}, status=201)


@require_http_methods(["PUT", "DELETE"])
def data_browser_record_api(request, browser_id, record_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    try:
        if request.method == "PUT":
            result = update_browser_record(browser, record_id, _request_payload(request))
        else:
            result = delete_browser_records(browser, [record_id])
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "record": result})


@require_http_methods(["DELETE", "POST"])
def data_browser_records_bulk_delete_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    payload = _request_payload(request)
    try:
        result = delete_browser_records(browser, payload.get("record_ids") or payload.get("ids") or [])
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "result": result})


@require_http_methods(["POST"])
def data_browser_import_api(request, browser_id):
    browser = get_object_or_404(DataBrowser.objects.prefetch_related("columns"), id=browser_id)
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return _json_error("Import file is required.")
    try:
        mapping_raw = request.POST.get("mapping", "{}")
        try:
            mapping = json.loads(mapping_raw) if mapping_raw else {}
        except Exception:
            mapping = {}
        result = import_browser_records(browser, uploaded_file, mapping=mapping)
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "import": result})


@require_http_methods(["GET"])
def data_browser_lookup_options_api(request, browser_id, column_id):
    browser = get_object_or_404(DataBrowser, id=browser_id)
    column = get_object_or_404(DataBrowserColumn, browser=browser, id=column_id)
    try:
        raw_limit = str(request.GET.get("limit", "500") or "500").strip().lower()
        limit = None if raw_limit == "all" else int(raw_limit)
        result = lookup_options(column, limit=limit)
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "lookup": result})


def _latest_data_quality_run(source_key: str | None = None, object_name: str | None = None):
    queryset = DataQualityRun.objects.all()
    if source_key:
        queryset = queryset.filter(source_key=source_key)
    if object_name:
        queryset = queryset.filter(object_name=object_name)
    return queryset.order_by("-created_at").first()


def _data_quality_controls_state(source_key: str | None = None, object_name: str | None = None):
    latest_run = _latest_data_quality_run(source_key, object_name)
    latest_results = latest_run.results if latest_run and isinstance(latest_run.results, list) else []
    results_by_key = {item.get("key"): item for item in latest_results if isinstance(item, dict)}
    controls = []
    for control in available_checks():
        result = results_by_key.get(control.key, {})
        controls.append(
            {
                "key": control.key,
                "name": control.name,
                "category": control.category,
                "description": control.description,
                "status": result.get("status", "Not run"),
                "impacted_records": result.get("impacted_records", 0),
                "error_percentage": result.get("error_percentage", 0),
                "execution_ms": result.get("execution_ms", 0),
                "affected_columns": result.get("affected_columns", []),
                "latest_run_id": latest_run.id if latest_run else None,
                "has_records": bool(result.get("records")),
            }
        )
    history = DataQualityRun.objects.all()
    if source_key:
        history = history.filter(source_key=source_key)
    if object_name:
        history = history.filter(object_name=object_name)
    return latest_run, controls, history[:12]


def reporting_home(request):
    reports = []
    error = None

    try:
        reports = list_workspace_reports_with_refresh()
    except Exception as exc:
        error = str(exc)

    return render(
        request,
        "reports/home.html",
        {
            "reports": reports,
            "report_count": len(reports),
            "error": error,
            "workspace_name": "Efficience Mine Workspace",
            "active_section": "reporting",
            "sidebar_stats": [
                {"label": "Reports", "value": len(reports)},
                {"label": "Embed", "value": "On"},
            ],
        },
    )


@ensure_csrf_cookie
def data_sources(request):
    sources = list_live_sources()
    source_cards = []
    for source in sources:
        source_cards.append(
            {
                "source": source,
                "inventory": _source_inventory(source),
            }
        )

    return render(
        request,
        "reports/data_sources.html",
        {
            "active_section": "sources",
            "source_count": len(sources),
            "source_cards": source_cards,
            "sidebar_stats": [
                {"label": "Sources", "value": len(sources)},
                {"label": "Mode", "value": "Live"},
            ],
        },
    )


def data_quality_center(request):
    source_key = (request.GET.get("source_key") or "").strip()
    object_name = (request.GET.get("object_name") or "").strip()
    preview_url = (request.GET.get("preview_url") or "").strip()
    category = (request.GET.get("category") or "").strip()
    query = (request.GET.get("q") or "").strip().lower()

    latest_run, controls, history = _data_quality_controls_state(source_key or None, object_name or None)
    if not preview_url and latest_run and isinstance(latest_run.request_payload, dict):
        preview_url = str(latest_run.request_payload.get("preview_url") or "").strip()

    if category:
        controls = [item for item in controls if item["category"].lower() == category.lower()]
    if query:
        controls = [
            item
            for item in controls
            if query in item["name"].lower()
            or query in item["description"].lower()
            or query in item["status"].lower()
        ]

    score = float(latest_run.score) if latest_run else 100.0
    run_status = latest_run.status if latest_run else "No run"
    last_run_at = latest_run.created_at if latest_run else None
    source_label = latest_run.source_name if latest_run else (source_key or "All sources")
    object_label = latest_run.object_name if latest_run else (object_name or "No object selected")

    return render(
        request,
        "reports/data_quality_center.html",
        {
            "active_section": "sources",
            "dq_controls": controls,
            "dq_history": history,
            "dq_score": score,
            "dq_last_run": last_run_at,
            "dq_run_status": run_status,
            "dq_source_label": source_label,
            "dq_object_label": object_label,
            "dq_filter_query": query,
            "dq_filter_category": category,
            "dq_source_key": source_key,
            "dq_object_name": object_name,
            "dq_preview_url": preview_url,
            "dq_categories": sorted({item["category"] for item in controls}),
            "sidebar_stats": [
                {"label": "Score", "value": f"{score:.0f}%"},
                {"label": "Controls", "value": len(available_checks())},
            ],
        },
    )


def _extract_connection_details(engine: str, data) -> tuple[dict[str, str], dict[str, object], str | None]:
    normalized_engine = (engine or "SQL Server").strip()
    details: dict[str, str] = {}
    connection_args: dict[str, object] = {}
    error = None

    if normalized_engine == "Snowflake":
        account = data.get("account", "").strip()
        warehouse = data.get("warehouse", "").strip()
        role = data.get("role", "").strip()
        database = data.get("database", "").strip()
        default_schema = data.get("default_schema", "").strip()
        user = data.get("user", "").strip()
        password = data.get("password", "").strip()

        if not account or not warehouse or not user:
            error = "Account, warehouse and user are required for Snowflake."
        else:
            details = {
                "account": _normalize_snowflake_account(account),
                "warehouse": warehouse,
                "role": role,
                "default_schema": default_schema,
            }
            connection_args = {
                "server": _normalize_snowflake_account(account),
                "database": database,
                "user": user,
                "password": password,
                "port": 0,
            }
    else:
        server = data.get("server", "").strip()
        database = data.get("database", "").strip()
        user = data.get("user", "").strip()
        password = data.get("password", "").strip()
        port_raw = data.get("port", "").strip()
        port = int(port_raw) if port_raw else 0

        if not server:
            error = "Instance/server is required for SQL Server."
        else:
            details = {
                "port": str(port or 0),
            }
            connection_args = {
                "server": server,
                "database": database or "master",
                "database_raw": database,
                "user": user,
                "password": password,
                "port": port,
            }

    return details, connection_args, error


@ensure_csrf_cookie
def source_add(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        engine = request.POST.get("engine", "SQL Server").strip() or "SQL Server"
        owner = request.POST.get("owner", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"
        error = None
        connection_details, connection_args, connection_error = _extract_connection_details(engine, request.POST)

        if not name:
            error = "Source name is required."
        elif connection_error:
            error = connection_error
        else:
            source = add_live_source(
                name=name,
                engine=engine,
                server=str(connection_args["server"]),
                database=str(connection_args.get("database_raw", connection_args.get("database", "")) or ""),
                user=str(connection_args["user"]),
                password=str(connection_args["password"]),
                port=int(connection_args["port"]),
                owner=owner,
                description=description,
                connection_details=connection_details,
                status="Active" if is_active else "Unknown",
                status_class="success" if is_active else "neutral",
                verification_message="Created manually. Verify the source to test the connection.",
            )
            return redirect("data-sources")

        return render(
            request,
            "reports/source_add.html",
            {
                "active_section": "sources",
                "error": error,
                "form": request.POST,
                "sidebar_stats": [
                    {"label": "Mode", "value": "Create"},
                    {"label": "Validate", "value": "Live"},
                ],
            },
        )

    return render(
        request,
        "reports/source_add.html",
        {
            "active_section": "sources",
            "sidebar_stats": [
                {"label": "Mode", "value": "Create"},
                {"label": "Validate", "value": "Live"},
            ],
        },
    )


@ensure_csrf_cookie
def source_edit(request, source_key):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    if request.method == "POST":
        password = request.POST.get("password", "").strip()
        connection_details, connection_args, connection_error = _extract_connection_details(source.engine, request.POST)
        if connection_error:
            return render(
                request,
                "reports/source_edit.html",
                {
                    "active_section": "sources",
                    "source": source,
                    "error": connection_error,
                    "sidebar_stats": [
                        {"label": "Views", "value": len(source.views)},
                        {"label": "Engine", "value": source.engine},
                    ],
                },
            )
        updated = update_live_source(
            source.key,
            server=str(connection_args["server"]),
            database=str(connection_args.get("database_raw", connection_args.get("database", "")) or ""),
            user=str(connection_args["user"]),
            password=password or None,
            port=int(connection_args["port"]),
            owner=request.POST.get("owner", source.owner).strip(),
            description=request.POST.get("description", source.description).strip(),
            connection_details=connection_details or source.connection_details,
            is_active=request.POST.get("is_active") == "on",
        )
        return redirect("source-detail", source_key=updated.key)

    return render(
        request,
        "reports/source_edit.html",
        {
            "active_section": "sources",
            "source": source,
            "sidebar_stats": [
                {"label": "Views", "value": len(source.views)},
                {"label": "Engine", "value": source.engine},
            ],
        },
    )


@ensure_csrf_cookie
@require_http_methods(["POST"])
def source_database_update(request, source_key):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    database = request.POST.get("database", "").strip()
    if not database:
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "error": "Database is required."}, status=400)
        messages.error(request, "Database is required.")
        return redirect("source-detail", source_key=source.key)

    updated = update_live_source(source.key, database=database)
    inventory = _source_inventory(updated)
    catalog = _source_catalog(updated)
    if _is_ajax_request(request):
        return JsonResponse(
            {
                "ok": True,
                "source": {
                    "key": updated.key,
                    "engine": updated.engine,
                    "database": updated.database,
                    "status": updated.verification_status,
                    "status_class": updated.status_class,
                    "last_verified": updated.last_verified,
                },
                "inventory": inventory,
                "catalog": catalog,
            }
        )

    messages.success(request, f"Database changed to {updated.database}.")
    return redirect("source-detail", source_key=source.key)


@ensure_csrf_cookie
@require_http_methods(["POST"])
def source_custom_view_add(request, source_key):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    sql = request.POST.get("sql", "").strip()

    if not name or not sql:
        error = "Custom view name and SQL are required."
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "error": error}, status=400)
        messages.error(request, error)
        return redirect("source-detail", source_key=source.key)

    view = add_live_view(source.key, name=name, description=description, sql=sql)
    inventory = _source_inventory(get_live_source(source.key))
    catalog = _source_catalog(get_live_source(source.key))
    if _is_ajax_request(request):
        return JsonResponse(
            {
                "ok": True,
                "view": {
                    "key": view.key,
                    "name": view.name,
                    "description": view.description,
                },
                "source": {
                    "key": source.key,
                    "engine": source.engine,
                    "database": source.database,
                },
                "inventory": inventory,
                "catalog": catalog,
            }
        )

    messages.success(request, f"Custom view '{view.name}' created.")
    return redirect("source-detail", source_key=source.key)


@ensure_csrf_cookie
@require_http_methods(["GET", "POST", "PUT"])
def source_custom_view_edit(request, source_key, view_key):
    try:
        source, view = get_live_view(source_key, view_key)
    except KeyError:
        raise Http404("Custom view not found")

    if request.method == "GET":
        return JsonResponse(
            {
                "ok": True,
                "view": {
                    "key": view.key,
                    "name": view.name,
                    "description": view.description,
                    "sql": view.sql,
                },
            }
        )

    payload = _request_payload(request)
    name = str(payload.get("name", view.name)).strip()
    description = str(payload.get("description", view.description)).strip()
    sql = str(payload.get("sql", view.sql)).strip()
    if not name or not sql:
        error = "Custom view name and SQL are required."
        if _is_ajax_request(request):
            return JsonResponse({"ok": False, "error": error}, status=400)
        messages.error(request, error)
        return redirect("source-detail", source_key=source.key)

    updated_view = update_live_view(source.key, view.key, name=name, description=description, sql=sql)
    updated_source = get_live_source(source.key)
    inventory = _source_inventory(updated_source)
    catalog = _source_catalog(updated_source)
    if _is_ajax_request(request):
        return JsonResponse(
            {
                "ok": True,
                "view": {
                    "key": updated_view.key,
                    "name": updated_view.name,
                    "description": updated_view.description,
                    "sql": updated_view.sql,
                },
                "source": {
                    "key": updated_source.key,
                    "engine": updated_source.engine,
                    "database": updated_source.database,
                },
                "inventory": inventory,
                "catalog": catalog,
            }
        )

    messages.success(request, f"Custom view '{updated_view.name}' updated.")
    return redirect("source-detail", source_key=source.key)


@ensure_csrf_cookie
@require_http_methods(["POST", "DELETE"])
def source_custom_view_delete(request, source_key, view_key):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    deleted = delete_live_view(source.key, view_key)
    if not deleted:
        raise Http404("Custom view not found")

    updated_source = get_live_source(source.key)
    inventory = _source_inventory(updated_source)
    catalog = _source_catalog(updated_source)
    if _is_ajax_request(request):
        return JsonResponse(
            {
                "ok": True,
                "deleted": True,
                "source": {
                    "key": updated_source.key,
                    "engine": updated_source.engine,
                    "database": updated_source.database,
                },
                "inventory": inventory,
                "catalog": catalog,
            }
        )

    messages.success(request, "Custom view deleted.")
    return redirect("source-detail", source_key=source.key)


def source_verify(request, source_key):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )

    if source.engine.lower() != "sql server":
        if snowflake_connector is None:
            updated = set_live_source_verification(
                source.key,
                False,
                "Snowflake connector is not installed.",
            )
        else:
            try:
                connect_kwargs = {
                    "account": _normalize_snowflake_account(source.connection_details.get("account") or source.server),
                    "user": source.user,
                    "password": source.password or None,
                    "warehouse": source.connection_details.get("warehouse"),
                    "role": source.connection_details.get("role") or None,
                }
                database = source.database or source.connection_details.get("database") or None
                if database:
                    connect_kwargs["database"] = database
                connection = snowflake_connector.connect(**connect_kwargs)
                try:
                    connection.cursor().execute("SELECT 1").fetchone()
                finally:
                    connection.close()
                updated = set_live_source_verification(source.key, True, "Connection OK")
            except Exception as exc:
                updated = set_live_source_verification(source.key, False, str(exc))
        if is_ajax:
            return JsonResponse(
                {
                    "ok": updated.verification_status.lower() == "active",
                    "source": {
                        "key": updated.key,
                        "status": updated.verification_status,
                        "status_class": updated.status_class,
                        "last_verified": updated.last_verified,
                        "message": updated.verification_message,
                    },
                },
                status=200 if updated.verification_status.lower() == "active" else 400,
            )
        return redirect("source-detail", source_key=source.key)

    try:
        with connect(
            server=source.server,
            database=source.database or "master",
            user=source.user or None,
            password=source.password or None,
            port=source.port or None,
        ) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        updated = set_live_source_verification(source.key, True, "Connection OK")
        if is_ajax:
            return JsonResponse(
                {
                    "ok": True,
                    "source": {
                        "key": updated.key,
                        "status": updated.verification_status,
                        "status_class": updated.status_class,
                        "last_verified": updated.last_verified,
                        "message": updated.verification_message,
                    },
                }
            )
    except Exception as exc:
        updated = set_live_source_verification(source.key, False, str(exc))
        if is_ajax:
            return JsonResponse(
                {
                    "ok": False,
                    "source": {
                        "key": updated.key,
                        "status": updated.verification_status,
                        "status_class": updated.status_class,
                        "last_verified": updated.last_verified,
                        "message": updated.verification_message,
                    },
                },
                status=400,
            )

    return redirect("source-detail", source_key=source.key)


@ensure_csrf_cookie
def source_detail(request, source_key):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    inventory = _source_inventory(source)
    catalog = _source_catalog(source)
    available_databases = _source_databases(source)
    dq_available_controls = [
        {
            "key": control.key,
            "name": control.name,
            "category": control.category,
            "description": control.description,
        }
        for control in available_checks()
    ]

    return render(
        request,
        "reports/source_detail.html",
        {
            "active_section": "sources",
            "source": source,
            "inventory": inventory,
            "catalog": catalog,
            "available_databases": available_databases,
            "dq_available_controls": dq_available_controls,
            "table_preview": None,
            "selected_table": "",
            "sidebar_stats": [
                {"label": "Views", "value": len(source.views)},
                {"label": "Engine", "value": source.engine},
            ],
        },
    )


def source_table_preview(request, source_key, table_name):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    if source.engine.lower() != "sql server":
        return JsonResponse({"ok": False, "error": "Table preview is only available for SQL Server sources."}, status=400)

    if not _is_ajax_request(request):
        raise Http404("Not found")

    filters = _parse_preview_filters(request.GET.get("filters", ""))

    try:
        table_name = _normalize_object_identifier(table_name)
        schema, table = [part.strip("[] ") for part in table_name.split(".", 1)]
        object_sql = f"{_escape_sql_identifier(schema)}.{_escape_sql_identifier(table)}"
        preview = _fetch_query_preview(
            source,
            _build_preview_sql(object_sql, filters, request.GET.get("limit", "1000")),
            table_name,
        )
        return JsonResponse({"ok": True, "preview": preview})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def source_object_preview(request, source_key, kind, identifier):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    if not _is_ajax_request(request):
        raise Http404("Not found")

    kind = (kind or "").strip().lower()
    limit = request.GET.get("limit", "1000")
    filters = _parse_preview_filters(request.GET.get("filters", ""))

    try:
        identifier = _normalize_object_identifier(identifier)
        if kind in {"table", "tables", "view", "views"}:
            object_sql = ".".join(_escape_sql_identifier(part.strip("[] ")) for part in identifier.split(".", 1))
            preview = _fetch_query_preview(source, _build_preview_sql(object_sql, filters, limit), identifier)
        elif kind in {"custom", "custom-view", "custom_view"}:
            view_source, view = get_live_view(source.key, identifier)
            object_sql = f"(\n{view.sql}\n) AS preview_view"
            preview = _fetch_query_preview(view_source, _build_preview_sql(object_sql, filters, limit), view.name)
        else:
            raise ValueError("Unknown object type.")
        return JsonResponse({"ok": True, "preview": preview})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def source_preview_export(request, source_key):
    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    preview_url = (request.GET.get("preview_url") or "").strip()
    if not preview_url:
        raise Http404("Preview target not found")

    filters = _parse_preview_filters(request.GET.get("filters", ""))

    try:
        payload = _preview_export_rows(source, preview_url, filters)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    try:
        from io import BytesIO
        from openpyxl import Workbook
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Excel export unavailable: {exc}"}, status=500)

    workbook = Workbook()
    sheet = workbook.active
    title = (payload.get("object_name") or "Preview")[:31]
    sheet.title = title or "Preview"

    preview = payload.get("preview") or {}
    columns = list(preview.get("columns") or [])
    rows = list(preview.get("rows") or [])
    if columns:
        sheet.append(columns)
        if rows:
            for record in rows:
                sheet.append([_json_safe(record.get(column)) for column in columns])
        else:
            sheet.append(["No rows returned"])
    else:
        sheet.append(["No rows returned"])

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = f"{source.key}_{title or 'preview'}.xlsx".replace(" ", "_")
    response = FileResponse(buffer, as_attachment=True, filename=filename)
    response["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response


def source_delete(request, source_key):
    if request.method != "POST":
        raise Http404("Source not found")

    try:
        source = get_live_source(source_key)
    except KeyError:
        raise Http404("Source not found")

    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )

    deleted = delete_live_source(source.key)
    if is_ajax:
        return JsonResponse(
            {
                "ok": bool(deleted),
                "deleted": bool(deleted),
                "source": {"key": source.key, "name": source.name},
            },
            status=200 if deleted else 404,
        )

    return redirect("data-sources")


def source_view(request, source_key, view_key):
    try:
        source, view = get_live_view(source_key, view_key)
    except KeyError:
        raise Http404("View not found")

    limit = request.GET.get("limit", "200")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    quick_range = request.GET.get("quick_range", "")
    error = None
    result = None

    def _valid_date(value: str) -> str:
        if not value:
            return ""
        return date.fromisoformat(value).isoformat()

    try:
        normalized_from = _valid_date(date_from)
        normalized_to = _valid_date(date_to)
    except ValueError:
        error = "Invalid date filter format. Use YYYY-MM-DD."
        normalized_from = ""
        normalized_to = ""

    today = date.today()

    if quick_range and not error:
        if quick_range == "mtd":
            normalized_from = date(today.year, today.month, 1).isoformat()
            normalized_to = today.isoformat()
        elif quick_range == "ytd":
            normalized_from = date(today.year, 1, 1).isoformat()
            normalized_to = today.isoformat()
        elif quick_range == "last-12-months":
            month = today.month - 11
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            normalized_from = date(year, month, 1).isoformat()
            normalized_to = today.isoformat()
        elif quick_range == "last-year":
            normalized_from = date(today.year - 1, 1, 1).isoformat()
            normalized_to = date(today.year - 1, 12, 31).isoformat()
        else:
            error = "Unknown quick range selected."

    if not error:
        try:
            result = execute_live_view(
                source.key,
                view.key,
                int(limit),
                date_from=normalized_from or None,
                date_to=normalized_to or None,
            )
        except Exception as exc:
            error = str(exc)

    return render(
        request,
        "reports/source_view.html",
        {
            "active_section": "sources",
            "source": source,
            "view": view,
            "limit": limit,
            "date_from": date_from,
            "date_to": date_to,
            "quick_range": quick_range,
            "result": result,
            "error": error,
            "sidebar_stats": [
                {"label": "Rows", "value": result["row_count"] if result else 0},
                {"label": "Engine", "value": source.engine},
            ],
        },
    )


MONTH_ALIASES = {
    "janvier": 1,
    "january": 1,
    "fevrier": 2,
    "février": 2,
    "february": 2,
    "mars": 3,
    "march": 3,
    "avril": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "june": 6,
    "juillet": 7,
    "july": 7,
    "aout": 8,
    "août": 8,
    "august": 8,
    "septembre": 9,
    "september": 9,
    "octobre": 10,
    "october": 10,
    "novembre": 11,
    "november": 11,
    "decembre": 12,
    "décembre": 12,
    "december": 12,
}


def _extract_flow_rows(flow_result: dict) -> list[dict]:
    rows = flow_result.get("firstTableRows")
    if isinstance(rows, list):
        return rows
    try:
        return flow_result["results"][0]["tables"][0]["rows"]
    except Exception:
        return []


def _format_pct(value) -> str:
    if value is None or value == "":
        return "BLANK"
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return str(value)


def _parse_semantic_question(question: str) -> dict:
    text = (question or "").strip()
    lowered = text.lower()
    parsed = {
        "dataset": "FPR Global DB + RLS",
        "site": "",
        "model": "",
        "year": 2026,
        "month": 5,
        "mode": "single",
        "months": 12,
    }
    site_match = re.search(r"(?:minesite|mine ?site|site)\s*[:=]\s*([a-z0-9 /_-]+)", lowered, re.I)
    if not site_match:
        site_match = re.search(r"\b(?:a|à|at|pour|sur)\s+([a-z][a-z0-9 /_-]+?)\s*(?:,| en | au | sur | pour |$)", lowered, re.I)
    if site_match:
        parsed["site"] = site_match.group(1).strip().title()

    model_match = re.search(r"(?:model|mod[eè]le)\s*[:=]?\s*([a-z0-9. -]+)", lowered, re.I)
    if not model_match:
        model_match = re.search(r"\b(6015|6020|6030|6040|6050|777 wt|777|785|789|d10|d9|992|390|395|980|988|844)\b", lowered, re.I)
    if model_match:
        parsed["model"] = model_match.group(1).strip().upper()

    if "tous les model" in lowered or "all model" in lowered or "tous les modèles" in lowered:
        parsed["mode"] = "matrix"
        parsed["model"] = ""
    if "12 derniers mois" in lowered or "douze derniers mois" in lowered or "last 12" in lowered:
        parsed["mode"] = "matrix"
        parsed["months"] = 12

    for name, number in MONTH_ALIASES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            parsed["month"] = number
            break
    year_match = re.search(r"\b(20\d{2})\b", lowered)
    if year_match:
        parsed["year"] = int(year_match.group(1))

    if not parsed["site"]:
        parsed["site"] = "Fekola"
    return parsed


def _resolve_semantic_rls_role(dataset_name: str, site: str) -> str:
    candidate = str(site or "").strip()
    if not candidate:
        return ""
    resolved_roles = resolve_dataset_roles(dataset_name, [candidate])
    if resolved_roles:
        return resolved_roles[0]
    return candidate


def _sanitize_conversation(payload) -> list[dict]:
    if not isinstance(payload, list):
        return []
    cleaned = []
    for item in payload[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            cleaned.append({"role": role, "content": content})
    return cleaned


def _build_single_answer(semantic_request: dict, rows: list[dict]) -> dict:
    row = rows[0] if rows else {}
    value = row.get("[Value]")
    answer = f"{semantic_request['measure']} = {_format_pct(value)}"
    if value is None:
        interpretation = "Aucune valeur n'est retournée pour ce contexte dans le modèle sémantique."
    else:
        pct = float(value) * 100
        if pct >= 90:
            interpretation = "La disponibilité est élevée sur ce contexte."
        elif pct >= 80:
            interpretation = "La disponibilité est correcte, mais mérite un suivi opérationnel."
        elif pct >= 70:
            interpretation = "La disponibilité est faible et doit être analysée."
        else:
            interpretation = "La disponibilité est critique; il faut investiguer les downtimes et les événements majeurs."
    return {
        "answer": answer,
        "interpretation": interpretation,
        "rows": rows,
    }


def _build_matrix_answer(semantic_request: dict, rows: list[dict]) -> dict:
    grouped = {}
    for row in rows:
        model = row.get("EquipmentList_MiningProd[Model]", "")
        value = row.get("[Availability]")
        if not model or value in (None, ""):
            continue
        grouped.setdefault(model, []).append(
            {
                "month": row.get("Date[Year Month]", ""),
                "month_number": row.get("Date[Year Month Number]", ""),
                "availability": float(value),
            }
        )
    summary = []
    for model, values in grouped.items():
        avg = sum(item["availability"] for item in values) / len(values)
        worst = min(values, key=lambda item: item["availability"])
        best = max(values, key=lambda item: item["availability"])
        summary.append(
            {
                "model": model,
                "months": len(values),
                "average": avg,
                "average_display": _format_pct(avg),
                "worst_month": worst["month"],
                "worst_value": worst["availability"],
                "worst_display": _format_pct(worst["availability"]),
                "best_month": best["month"],
                "best_value": best["availability"],
                "best_display": _format_pct(best["availability"]),
            }
        )
    summary.sort(key=lambda item: item["average"])
    weak_models = [item for item in summary if item["average"] < 0.8]
    interpretation = (
        f"{len(summary)} modèles ont des valeurs sur la période. "
        f"{len(weak_models)} modèles ont une moyenne sous 80%. "
    )
    if weak_models:
        interpretation += "Les priorités d'analyse sont: " + ", ".join(item["model"] for item in weak_models[:6]) + "."
    else:
        interpretation += "La disponibilité moyenne est globalement maîtrisée."
    return {
        "answer": f"{semantic_request['measure']} par modèle pour {semantic_request['filters'].get('MineSiteList_MiningProd[MineSite]', '')}",
        "interpretation": interpretation,
        "summary": summary,
        "rows": rows,
    }


@ensure_csrf_cookie
def ai_home(request):
    openai_enabled = is_openai_configured()
    return render(
        request,
        "reports/ai.html",
        {
            "active_section": "ai",
            "openai_enabled": openai_enabled,
            "sidebar_stats": [
                {"label": "Mode", "value": "AI" if openai_enabled else "Rules"},
                {"label": "Model", "value": "OpenAI" if openai_enabled else "Semantic"},
            ],
        },
    )


def ai_semantic_test(request):
    dataset_name = request.GET.get("dataset", "FPR Global DB + RLS")
    year = int(request.GET.get("year", "2026"))
    month = int(request.GET.get("month", "5"))
    model = request.GET.get("model", "777")
    site = request.GET.get("site", "Fekola")

    semantic_request = build_availability_question(dataset_name, year, month, model, site)
    dataset_id = semantic_request["dataset_id"] or resolve_workspace_dataset_id(dataset_name)
    semantic_request["dataset_id"] = dataset_id
    semantic_request["rls_role"] = _resolve_semantic_rls_role(dataset_name, site)
    dax_query = semantic_request["dax"]

    flow_payload = {
        "datasetId": dataset_id,
        "datasetName": dataset_name,
        "query": dax_query,
        "question": semantic_request["question"],
        "metric": semantic_request["metric"],
        "measure": semantic_request["measure"],
        "filters": semantic_request["filters"],
        "period": semantic_request["period"],
        "rlsRole": semantic_request["rls_role"],
        "roles": [semantic_request["rls_role"]] if semantic_request["rls_role"] else [],
    }
    try:
        flow_result = execute_dax_via_flow(flow_payload)
        return JsonResponse(
            {
                "ok": True,
                "execution": "power_automate",
                "semantic_request": semantic_request,
                "flow_result": flow_result,
            }
        )
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc),
                "execution": "power_automate",
                "semantic_request": semantic_request,
                "flow_payload": flow_payload,
            },
            status=500,
        )


def ai_ask(request):
    started_at = time.monotonic()
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

    question = (payload.get("question") or "").strip()
    section_code = (payload.get("section_code") or payload.get("section") or "").strip() or None
    conversation = _sanitize_conversation(payload.get("conversation"))
    if not question:
        return JsonResponse({"ok": False, "error": "Question is required."}, status=400)

    if PowerBIReport.objects.filter(is_active=True, validation_status="Validated").exists():
        try:
            orchestrated = process_user_question(
                question,
                user_context={
                    "user": request.user,
                    "section_code": section_code,
                    "dataset_name": (payload.get("dataset_name") or "FPR Global DB + RLS").strip(),
                    "open_report": True,
                    "debug_mode": _user_is_platform_admin(request.user),
                },
                conversation_context={
                    "conversation_id": str(payload.get("conversation_id") or "").strip(),
                    "messages": conversation,
                },
            )
            if not orchestrated.get("ok"):
                return JsonResponse(orchestrated, status=400)
            return JsonResponse({
                **orchestrated,
                "chat_message": orchestrated.get("answer"),
                "answer": {
                    "answer": orchestrated.get("answer"),
                    "interpretation": orchestrated.get("answer"),
                    "rows": orchestrated.get("rows") or [],
                    "summary": orchestrated.get("rows") or [],
                },
            })
        except Exception:
            # Preserve the existing semantic path while interaction metadata is
            # under review or a report mapping is temporarily stale.
            pass

    intent = extract_intent(question, section_code)
    valid, validation_errors = validate_intent(intent)
    if not valid:
        return JsonResponse(
            {
                "ok": False,
                "error": "Intent validation failed.",
                "validation": {"valid": False, "errors": validation_errors},
                "intent": intent,
            },
            status=400,
        )

    try:
        dax_payload = generate_dax_from_intent(intent)
    except IntentValidationError as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc),
                "validation": {"valid": False, "errors": [str(exc)]},
                "intent": intent,
            },
            status=400,
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc), "intent": intent}, status=500)

    dataset_name = (payload.get("dataset_name") or "FPR Global DB + RLS").strip()
    dataset_id = resolve_workspace_dataset_id(dataset_name)
    section = get_section_by_code(dax_payload["section"])
    rls_role = _resolve_semantic_rls_role(dataset_name, intent.get("filters", {}).get("minesite") or intent.get("filters", {}).get("site") or "")
    flow_payload = {
        "datasetId": dataset_id,
        "datasetName": dataset_name,
        "query": dax_payload["dax"],
        "question": question,
        "metric": dax_payload["metric"],
        "measure": dax_payload["measure"],
        "filters": dax_payload["filters"],
        "section": dax_payload["section"],
        "intent": intent,
        "rlsRole": rls_role,
        "roles": [rls_role] if rls_role else [],
    }

    try:
        flow_result = execute_dax_via_flow(flow_payload)
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc),
                "intent": intent,
                "dax": dax_payload["dax"],
                "flow_payload": flow_payload,
            },
            status=500,
        )

    rows = _extract_flow_rows(flow_result)
    answer = {
        "answer": "",
        "interpretation": "",
        "rows": rows,
        "summary": rows,
    }
    if rows:
        measure_key_names = {dax_payload["metric_label"].lower(), dax_payload["measure"].strip("[]").lower(), "value"}
        measured_rows = []
        for row in rows:
            for key, value in row.items():
                key_norm = str(key).strip("[]").lower()
                if key_norm in measure_key_names:
                    try:
                        numeric_value = float(value)
                    except Exception:
                        numeric_value = None
                    measured_rows.append({"row": row, "value": value, "numeric_value": numeric_value})
                    break

        numeric_rows = [item for item in measured_rows if item["numeric_value"] is not None]
        if len(numeric_rows) > 1:
            avg = sum(item["numeric_value"] for item in numeric_rows) / len(numeric_rows)
            worst = min(numeric_rows, key=lambda item: item["numeric_value"])
            best = max(numeric_rows, key=lambda item: item["numeric_value"])
            answer["answer"] = f"{dax_payload['metric_label']} average = {_format_pct(avg)}"
            answer["interpretation"] = (
                f"{len(numeric_rows)} points retournés. "
                f"Moyenne: {_format_pct(avg)}. "
                f"Plus faible: {_format_pct(worst['numeric_value'])}. "
                f"Meilleur: {_format_pct(best['numeric_value'])}."
            )
            answer["summary"] = {
                "row_count": len(rows),
                "measured_points": len(numeric_rows),
                "average": avg,
                "average_display": _format_pct(avg),
                "worst": worst["row"],
                "best": best["row"],
            }
        elif measured_rows:
            measure_value = measured_rows[0]["value"]
            answer["answer"] = f"{dax_payload['metric_label']} = {_format_pct(measure_value)}"
            try:
                pct = float(measure_value) * 100
            except Exception:
                pct = None
            if pct is None:
                answer["interpretation"] = "Résultat retourné avec succès."
            elif pct >= 90:
                answer["interpretation"] = "La valeur est élevée sur ce contexte."
            elif pct >= 80:
                answer["interpretation"] = "La valeur est correcte, mais mérite un suivi."
            elif pct >= 70:
                answer["interpretation"] = "La valeur est faible et doit être analysée."
            else:
                answer["interpretation"] = "La valeur est critique et nécessite une investigation."
        else:
            answer["interpretation"] = "Le modèle n'a pas retourné de valeur exploitable pour ce contexte."
    else:
        answer["interpretation"] = "Aucune donnée n'a été retournée par le modèle."

    try:
        metric_code_for_target = dax_payload["metric"]
        target = AIKPITarget.objects.filter(section__code=dax_payload["section"], metric_code=metric_code_for_target, is_active=True).first()
        numeric_value = None
        if isinstance(answer.get("summary"), dict) and answer["summary"].get("average") is not None:
            numeric_value = float(answer["summary"]["average"])
        elif rows:
            for row in rows:
                for value in row.values():
                    try:
                        numeric_value = float(value)
                        break
                    except Exception:
                        continue
                if numeric_value is not None:
                    break
        if target and numeric_value is not None:
            target_payload = {
                "target": float(target.target),
                "warning_threshold": float(target.warning_threshold),
                "critical_threshold": float(target.critical_threshold),
                "unit": target.unit,
            }
            if numeric_value < float(target.critical_threshold):
                target_status = "Critical"
            elif numeric_value < float(target.warning_threshold):
                target_status = "Warning"
            elif numeric_value >= float(target.target):
                target_status = "OK"
            else:
                target_status = "Watch"
            actions = [
                item.recommendations
                for item in AIRecommendedAction.objects.filter(
                    section__code=dax_payload["section"],
                    metric_code=metric_code_for_target,
                    is_active=True,
                ).order_by("priority")
            ]
            answer["kpi_target"] = target_payload
            answer["kpi_status"] = target_status
            answer["recommended_actions"] = actions
            answer["interpretation"] = f"{answer['interpretation']} Statut KPI: {target_status}."
    except Exception:
        pass

    final_response = answer["interpretation"]
    try:
        final_response = generate_chat_response(question, intent, answer, conversation)
    except Exception:
        final_response = answer["interpretation"]

    execution_time_ms = int((time.monotonic() - started_at) * 1000)
    try:
        intent_prompt = get_prompt_template(dax_payload["section"], "intent_extraction") or {}
        response_prompt = get_prompt_template(dax_payload["section"], "response_generation") or {}
        prompt_sent = (
            "Intent Extraction Template:\n"
            f"{intent_prompt.get('prompt_template', '')}\n\n"
            "Response Generation Template:\n"
            f"{response_prompt.get('prompt_template', '')}"
        ).strip()
        AIDebugRun.objects.create(
            question_text=question,
            detected_section=str(intent.get("section") or ""),
            extracted_intent=intent,
            prompt_sent=prompt_sent,
            generated_json=intent,
            generated_dax=dax_payload["dax"],
            powerbi_response=flow_result if isinstance(flow_result, dict) else {"raw": str(flow_result)},
            formatted_response=final_response,
            execution_time_ms=execution_time_ms,
            token_usage={},
            errors="",
        )
        KnowledgeAILog.objects.create(
            user_question=question,
            detected_section=str(intent.get("section") or ""),
            extracted_intent=intent,
            generated_dax=dax_payload["dax"],
            powerbi_result=flow_result if isinstance(flow_result, dict) else {"raw": str(flow_result)},
            final_answer=final_response,
            status="Completed",
            execution_time_ms=execution_time_ms,
            token_usage={},
            user=request.user if request.user.is_authenticated else None,
        )
    except Exception:
        pass

    return JsonResponse(
        {
            "ok": True,
            "intent": intent,
            "validation": {"valid": True, "errors": []},
            "dax": dax_payload["dax"],
            "metric": dax_payload["metric"],
            "measure": dax_payload["measure"],
            "flow_payload": flow_payload,
            "raw_result": flow_result,
            "answer": answer,
            "chat_message": final_response,
            "debug": {
                "question": question,
                "json_intent": intent,
                "dax": dax_payload["dax"],
                "raw_powerbi": flow_result,
                "final_response": final_response,
                "execution_time_ms": execution_time_ms,
            },
        }
    )


IA_RESOURCE_TYPES = {
    "question-examples": {
        "model": AIQuestionExample,
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "question_text": item.question_text,
            "language": item.language,
            "expected_json_intent": item.expected_json_intent,
            "is_active": item.is_active,
        },
    },
    "synonyms": {
        "model": AISynonym,
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "entity_type": item.entity_type,
            "canonical_value": item.canonical_value,
            "synonym_value": item.synonym_value,
            "language": item.language,
            "is_active": item.is_active,
        },
    },
    "metrics": {
        "model": AIMetricMapping,
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "metric_code": item.metric_code,
            "metric_label": item.metric_label,
            "powerbi_measure_name": item.powerbi_measure_name,
            "description": item.description,
            "is_active": item.is_active,
        },
    },
    "filters": {
        "model": AIFilterMapping,
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "filter_code": item.filter_code,
            "filter_label": item.filter_label,
            "powerbi_table_name": item.powerbi_table_name,
            "powerbi_column_name": item.powerbi_column_name,
            "data_type": item.data_type,
            "is_required": item.is_required,
            "is_active": item.is_active,
        },
    },
    "dax-templates": {
        "model": AIDaxTemplate,
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "template_name": item.template_name,
            "template_code": item.template_code,
            "dax_template": item.dax_template,
            "description": item.description,
            "is_active": item.is_active,
        },
    },
    "semantic-tables": {
        "model": AISemanticTable,
        "search_fields": ["table_name", "display_name", "description"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "table_name": item.table_name,
            "display_name": item.display_name,
            "description": item.description,
            "is_active": item.is_active,
        },
    },
    "semantic-columns": {
        "model": AISemanticColumn,
        "search_fields": ["table_name", "column_name", "display_name", "data_type", "description"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "table_name": item.table_name,
            "column_name": item.column_name,
            "display_name": item.display_name,
            "data_type": item.data_type,
            "description": item.description,
            "is_filter": item.is_filter,
            "is_active": item.is_active,
        },
    },
    "semantic-measures": {
        "model": AISemanticMeasure,
        "search_fields": ["measure_name", "display_name", "description", "dax_name", "unit", "category"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "measure_name": item.measure_name,
            "display_name": item.display_name,
            "description": item.description,
            "dax_name": item.dax_name,
            "unit": item.unit,
            "category": item.category,
            "is_active": item.is_active,
        },
    },
    "semantic-relationships": {
        "model": AISemanticRelationship,
        "search_fields": ["parent_table", "parent_column", "child_table", "child_column", "relationship_type"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "parent_table": item.parent_table,
            "parent_column": item.parent_column,
            "child_table": item.child_table,
            "child_column": item.child_column,
            "relationship_type": item.relationship_type,
            "is_active": item.is_active,
        },
    },
    "business-vocabulary": {
        "model": AIBusinessVocabulary,
        "search_fields": ["business_term", "business_definition", "category"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "business_term": item.business_term,
            "business_definition": item.business_definition,
            "category": item.category,
            "is_active": item.is_active,
        },
    },
    "few-shot-examples": {
        "model": AIFewShotExample,
        "search_fields": ["question", "expected_dax", "expected_response", "explanation"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "question": item.question,
            "expected_json_intent": item.expected_json_intent,
            "expected_dax": item.expected_dax,
            "expected_response": item.expected_response,
            "explanation": item.explanation,
            "is_active": item.is_active,
        },
    },
    "prompt-templates": {
        "model": AIPromptTemplate,
        "search_fields": ["prompt_type", "template_name", "prompt_template", "description"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "prompt_type": item.prompt_type,
            "template_name": item.template_name,
            "prompt_template": item.prompt_template,
            "description": item.description,
            "is_active": item.is_active,
        },
    },
    "business-rules": {
        "model": AIBusinessRule,
        "search_fields": ["metric_code", "rule_name", "condition", "action", "default_value"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "metric_code": item.metric_code,
            "rule_name": item.rule_name,
            "condition": item.condition,
            "action": item.action,
            "default_value": item.default_value,
            "priority": item.priority,
            "is_active": item.is_active,
        },
    },
    "powerbi-pages": {
        "model": AIPowerBIPage,
        "search_fields": ["page_name", "report_name", "report_id", "page_display_name", "description"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "page_name": item.page_name,
            "report_name": item.report_name,
            "report_id": item.report_id,
            "page_display_name": item.page_display_name,
            "description": item.description,
            "is_default_page": item.is_default_page,
            "is_active": item.is_active,
        },
    },
    "visual-mapping": {
        "model": AIVisualMapping,
        "search_fields": ["metric_code", "recommended_visual", "description"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "metric_code": item.metric_code,
            "recommended_visual": item.recommended_visual,
            "description": item.description,
            "priority": item.priority,
            "is_active": item.is_active,
        },
    },
    "kpi-targets": {
        "model": AIKPITarget,
        "search_fields": ["metric_code", "unit"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "metric_code": item.metric_code,
            "target": str(item.target),
            "warning_threshold": str(item.warning_threshold),
            "critical_threshold": str(item.critical_threshold),
            "unit": item.unit,
            "is_active": item.is_active,
        },
    },
    "recommended-actions": {
        "model": AIRecommendedAction,
        "search_fields": ["metric_code", "condition", "recommendations"],
        "serializer": lambda item: {
            "id": item.id,
            "section": item.section.code,
            "metric_code": item.metric_code,
            "condition": item.condition,
            "recommendations": item.recommendations,
            "priority": item.priority,
            "is_active": item.is_active,
        },
    },
    "debug-runs": {
        "model": AIDebugRun,
        "admin_only": True,
        "search_fields": ["question_text", "detected_section", "generated_dax", "formatted_response", "errors"],
        "serializer": lambda item: {
            "id": item.id,
            "created_at": item.created_at.isoformat() if item.created_at else "",
            "question_text": item.question_text,
            "detected_section": item.detected_section,
            "extracted_intent": item.extracted_intent,
            "prompt_sent": item.prompt_sent,
            "generated_json": item.generated_json,
            "generated_dax": item.generated_dax,
            "powerbi_response": item.powerbi_response,
            "formatted_response": item.formatted_response,
            "execution_time_ms": item.execution_time_ms,
            "token_usage": item.token_usage,
            "errors": item.errors,
        },
    },
}


def _ia_section_payload(section: AIConfigSection) -> dict:
    return {
        "id": section.id,
        "name": section.name,
        "code": section.code,
        "description": section.description,
        "is_active": section.is_active,
    }


def _ia_get_section_or_404(section_code: str) -> AIConfigSection:
    section = get_object_or_404(AIConfigSection, code=section_code)
    return section


def _ia_resource_queryset(section: AIConfigSection | None, resource_type: str):
    model = IA_RESOURCE_TYPES[resource_type]["model"]
    if IA_RESOURCE_TYPES[resource_type].get("admin_only"):
        return model.objects.all()
    return model.objects.filter(section=section)


def _ia_normalize_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _ia_payload(request) -> dict:
    return _request_payload(request)


def _ia_text(payload: dict, item, field: str, default: str = "") -> str:
    return str(payload.get(field, getattr(item, field, default) or default)).strip()


def _ia_int(payload: dict, item, field: str, default: int = 100) -> int:
    value = payload.get(field, getattr(item, field, default))
    try:
        return int(value)
    except Exception:
        return default


def _ia_decimal_text(payload: dict, item, field: str, default: str = "0"):
    value = str(payload.get(field, getattr(item, field, default) or default)).strip()
    return value or default


def _ia_json_object(payload: dict, item, field: str) -> dict:
    value = payload.get(field, getattr(item, field, {}) or {})
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except Exception as exc:
            raise ValueError(f"{field} must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object.")
    return value


def _ia_apply_resource_payload(resource_type: str, item, payload: dict, section: AIConfigSection):
    if resource_type == "question-examples":
        item.question_text = str(payload.get("question_text", item.question_text or "")).strip()
        item.language = str(payload.get("language", item.language or "fr")).strip() or "fr"
        raw_json = payload.get("expected_json_intent", item.expected_json_intent or {})
        if isinstance(raw_json, str):
            try:
                raw_json = json.loads(raw_json) if raw_json.strip() else {}
            except Exception as exc:
                raise ValueError("Expected JSON Intent must be valid JSON.") from exc
        if not isinstance(raw_json, dict):
            raise ValueError("Expected JSON Intent must be a JSON object.")
        item.expected_json_intent = raw_json
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        item.section = section
        if not item.question_text:
            raise ValueError("Question text is required.")
        return item

    if resource_type == "synonyms":
        item.entity_type = str(payload.get("entity_type", item.entity_type or "")).strip()
        item.canonical_value = str(payload.get("canonical_value", item.canonical_value or "")).strip()
        item.synonym_value = str(payload.get("synonym_value", item.synonym_value or "")).strip()
        item.language = str(payload.get("language", item.language or "fr")).strip() or "fr"
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        item.section = section
        if not item.entity_type or not item.canonical_value or not item.synonym_value:
            raise ValueError("Entity type, canonical value and synonym value are required.")
        return item

    if resource_type == "metrics":
        item.metric_code = str(payload.get("metric_code", item.metric_code or "")).strip()
        item.metric_label = str(payload.get("metric_label", item.metric_label or "")).strip()
        item.powerbi_measure_name = str(payload.get("powerbi_measure_name", item.powerbi_measure_name or "")).strip()
        item.description = str(payload.get("description", item.description or "")).strip()
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        item.section = section
        if not item.metric_code or not item.metric_label or not item.powerbi_measure_name:
            raise ValueError("Metric code, label and Power BI measure name are required.")
        return item

    if resource_type == "filters":
        item.filter_code = str(payload.get("filter_code", item.filter_code or "")).strip()
        item.filter_label = str(payload.get("filter_label", item.filter_label or "")).strip()
        item.powerbi_table_name = str(payload.get("powerbi_table_name", item.powerbi_table_name or "")).strip()
        item.powerbi_column_name = str(payload.get("powerbi_column_name", item.powerbi_column_name or "")).strip()
        item.data_type = str(payload.get("data_type", item.data_type or "Text")).strip() or "Text"
        item.is_required = _ia_normalize_bool(payload.get("is_required"), item.is_required)
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        item.section = section
        if not item.filter_code or not item.filter_label or not item.powerbi_table_name or not item.powerbi_column_name:
            raise ValueError("Filter code, label, table name and column name are required.")
        return item

    if resource_type == "dax-templates":
        item.template_name = str(payload.get("template_name", item.template_name or "")).strip()
        item.template_code = str(payload.get("template_code", item.template_code or "")).strip()
        item.dax_template = str(payload.get("dax_template", item.dax_template or "")).strip()
        item.description = str(payload.get("description", item.description or "")).strip()
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        item.section = section
        if not item.template_name or not item.template_code or not item.dax_template:
            raise ValueError("Template name, template code and DAX template are required.")
        return item

    if resource_type == "semantic-tables":
        item.section = section
        item.table_name = _ia_text(payload, item, "table_name")
        item.display_name = _ia_text(payload, item, "display_name", item.table_name)
        item.description = _ia_text(payload, item, "description")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.table_name or not item.display_name:
            raise ValueError("Table name and display name are required.")
        return item

    if resource_type == "semantic-columns":
        item.section = section
        item.table_name = _ia_text(payload, item, "table_name")
        item.column_name = _ia_text(payload, item, "column_name")
        item.display_name = _ia_text(payload, item, "display_name", item.column_name)
        item.data_type = _ia_text(payload, item, "data_type")
        item.description = _ia_text(payload, item, "description")
        item.is_filter = _ia_normalize_bool(payload.get("is_filter"), item.is_filter)
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.table_name or not item.column_name or not item.display_name:
            raise ValueError("Table, column name and display name are required.")
        return item

    if resource_type == "semantic-measures":
        item.section = section
        item.measure_name = _ia_text(payload, item, "measure_name")
        item.display_name = _ia_text(payload, item, "display_name", item.measure_name)
        item.description = _ia_text(payload, item, "description")
        item.dax_name = _ia_text(payload, item, "dax_name", f"[{item.measure_name}]")
        item.unit = _ia_text(payload, item, "unit")
        item.category = _ia_text(payload, item, "category")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.measure_name or not item.display_name or not item.dax_name:
            raise ValueError("Measure name, display name and DAX name are required.")
        return item

    if resource_type == "semantic-relationships":
        item.section = section
        item.parent_table = _ia_text(payload, item, "parent_table")
        item.parent_column = _ia_text(payload, item, "parent_column")
        item.child_table = _ia_text(payload, item, "child_table")
        item.child_column = _ia_text(payload, item, "child_column")
        item.relationship_type = _ia_text(payload, item, "relationship_type")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.parent_table or not item.parent_column or not item.child_table or not item.child_column:
            raise ValueError("Parent table/column and child table/column are required.")
        return item

    if resource_type == "business-vocabulary":
        item.section = section
        item.business_term = _ia_text(payload, item, "business_term")
        item.business_definition = _ia_text(payload, item, "business_definition")
        item.category = _ia_text(payload, item, "category")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.business_term or not item.business_definition:
            raise ValueError("Business term and definition are required.")
        return item

    if resource_type == "few-shot-examples":
        item.section = section
        item.question = _ia_text(payload, item, "question")
        item.expected_json_intent = _ia_json_object(payload, item, "expected_json_intent")
        item.expected_dax = _ia_text(payload, item, "expected_dax")
        item.expected_response = _ia_text(payload, item, "expected_response")
        item.explanation = _ia_text(payload, item, "explanation")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.question:
            raise ValueError("Question is required.")
        return item

    if resource_type == "prompt-templates":
        item.section = section
        item.prompt_type = _ia_text(payload, item, "prompt_type")
        item.template_name = _ia_text(payload, item, "template_name")
        item.prompt_template = _ia_text(payload, item, "prompt_template")
        item.description = _ia_text(payload, item, "description")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.prompt_type or not item.template_name or not item.prompt_template:
            raise ValueError("Prompt type, template name and prompt template are required.")
        return item

    if resource_type == "business-rules":
        item.section = section
        item.metric_code = _ia_text(payload, item, "metric_code")
        item.rule_name = _ia_text(payload, item, "rule_name")
        item.condition = _ia_text(payload, item, "condition")
        item.action = _ia_text(payload, item, "action")
        item.default_value = _ia_text(payload, item, "default_value")
        item.priority = _ia_int(payload, item, "priority")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.metric_code or not item.rule_name or not item.condition or not item.action:
            raise ValueError("Metric, rule name, condition and action are required.")
        return item

    if resource_type == "powerbi-pages":
        item.section = section
        item.page_name = _ia_text(payload, item, "page_name")
        item.report_name = _ia_text(payload, item, "report_name")
        item.report_id = _ia_text(payload, item, "report_id")
        item.page_display_name = _ia_text(payload, item, "page_display_name", item.page_name)
        item.description = _ia_text(payload, item, "description")
        item.is_default_page = _ia_normalize_bool(payload.get("is_default_page"), item.is_default_page)
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.page_name or not item.report_name or not item.page_display_name:
            raise ValueError("Page name, report name and page display name are required.")
        return item

    if resource_type == "visual-mapping":
        item.section = section
        item.metric_code = _ia_text(payload, item, "metric_code")
        item.recommended_visual = _ia_text(payload, item, "recommended_visual")
        item.description = _ia_text(payload, item, "description")
        item.priority = _ia_int(payload, item, "priority")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.metric_code or not item.recommended_visual:
            raise ValueError("Metric and recommended visual are required.")
        return item

    if resource_type == "kpi-targets":
        item.section = section
        item.metric_code = _ia_text(payload, item, "metric_code")
        item.target = _ia_decimal_text(payload, item, "target")
        item.warning_threshold = _ia_decimal_text(payload, item, "warning_threshold")
        item.critical_threshold = _ia_decimal_text(payload, item, "critical_threshold")
        item.unit = _ia_text(payload, item, "unit")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.metric_code:
            raise ValueError("Metric is required.")
        return item

    if resource_type == "recommended-actions":
        item.section = section
        item.metric_code = _ia_text(payload, item, "metric_code")
        item.condition = _ia_text(payload, item, "condition")
        item.recommendations = _ia_text(payload, item, "recommendations")
        item.priority = _ia_int(payload, item, "priority")
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.metric_code or not item.condition or not item.recommendations:
            raise ValueError("Metric, condition and recommendations are required.")
        return item

    raise ValueError("Unsupported IA Config resource type.")


@require_http_methods(["GET"])
def ia_config_home(request):
    sections = get_active_sections()
    return render(
        request,
        "reports/ia_config.html",
        {
            "active_section": "ia-config",
            "sections": sections,
            "is_ia_admin": request.user.is_staff or request.user.is_superuser,
            "sidebar_stats": [
                {"label": "Sections", "value": len(sections)},
                {"label": "Mode", "value": "AI Config"},
            ],
        },
    )


@require_http_methods(["GET"])
def ia_config_sections_api(request):
    return JsonResponse({"ok": True, "sections": get_active_sections()})


@require_http_methods(["GET", "POST"])
def ia_config_collection_api(request, section_code, resource_type):
    if resource_type not in IA_RESOURCE_TYPES:
        return _json_error("Unsupported IA Config resource type.", status=404)
    config = IA_RESOURCE_TYPES[resource_type]
    if config.get("admin_only") and not (request.user.is_staff or request.user.is_superuser):
        return _json_error("Administrator access required.", status=403)
    section = None if config.get("admin_only") else _ia_get_section_or_404(section_code)
    model = IA_RESOURCE_TYPES[resource_type]["model"]
    serializer = IA_RESOURCE_TYPES[resource_type]["serializer"]
    queryset = _ia_resource_queryset(section, resource_type)

    if request.method == "GET":
        query = request.GET.get("q", "").strip().lower()
        active = request.GET.get("active", "").strip().lower()
        if active in {"1", "true", "yes"} and hasattr(model, "is_active"):
            queryset = queryset.filter(is_active=True)
        elif active in {"0", "false", "no"} and hasattr(model, "is_active"):
            queryset = queryset.filter(is_active=False)
        if query:
            if resource_type == "question-examples":
                queryset = queryset.filter(question_text__icontains=query)
            elif resource_type == "synonyms":
                queryset = queryset.filter(
                    models.Q(entity_type__icontains=query)
                    | models.Q(canonical_value__icontains=query)
                    | models.Q(synonym_value__icontains=query)
                )
            elif resource_type == "metrics":
                queryset = queryset.filter(
                    models.Q(metric_code__icontains=query)
                    | models.Q(metric_label__icontains=query)
                    | models.Q(powerbi_measure_name__icontains=query)
                )
            elif resource_type == "filters":
                queryset = queryset.filter(
                    models.Q(filter_code__icontains=query)
                    | models.Q(filter_label__icontains=query)
                    | models.Q(powerbi_table_name__icontains=query)
                    | models.Q(powerbi_column_name__icontains=query)
                )
            elif resource_type == "dax-templates":
                queryset = queryset.filter(
                    models.Q(template_name__icontains=query)
                    | models.Q(template_code__icontains=query)
                    | models.Q(description__icontains=query)
                )
            else:
                search_fields = IA_RESOURCE_TYPES[resource_type].get("search_fields", [])
                if search_fields:
                    q_filter = models.Q()
                    for field in search_fields:
                        q_filter |= models.Q(**{f"{field}__icontains": query})
                    queryset = queryset.filter(q_filter)
        order_field = "-created_at" if resource_type == "debug-runs" else "-updated_at"
        items = [serializer(item) for item in queryset.order_by(order_field)]
        section_payload = _ia_section_payload(section) if section else {"code": section_code}
        return JsonResponse({"ok": True, "section": section_payload, "items": items})

    if config.get("admin_only"):
        return _json_error("This resource is read-only.", status=405)
    payload = _ia_payload(request)
    try:
        item = model(section=section)
        item = _ia_apply_resource_payload(resource_type, item, payload, section)
        item.save()
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "item": serializer(item)}, status=201)


@require_http_methods(["PUT", "DELETE"])
def ia_config_item_api(request, section_code, resource_type, item_id):
    if resource_type not in IA_RESOURCE_TYPES:
        return _json_error("Unsupported IA Config resource type.", status=404)
    config = IA_RESOURCE_TYPES[resource_type]
    if config.get("admin_only") and not (request.user.is_staff or request.user.is_superuser):
        return _json_error("Administrator access required.", status=403)
    section = None if config.get("admin_only") else _ia_get_section_or_404(section_code)
    model = config["model"]
    serializer = config["serializer"]
    item = get_object_or_404(model, id=item_id) if config.get("admin_only") else get_object_or_404(model, section=section, id=item_id)

    if request.method == "DELETE":
        if config.get("admin_only"):
            return _json_error("This resource is read-only.", status=405)
        item.delete()
        return JsonResponse({"ok": True, "deleted": True})

    if config.get("admin_only"):
        return _json_error("This resource is read-only.", status=405)
    payload = _ia_payload(request)
    try:
        item = _ia_apply_resource_payload(resource_type, item, payload, section)
        item.save()
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "item": serializer(item)})


@require_http_methods(["POST"])
def ia_config_test_intent_api(request):
    payload = _ia_payload(request)
    question_text = str(payload.get("question_text", "")).strip()
    section_code = str(payload.get("section_code", "")).strip() or None
    if not question_text:
        return _json_error("Question text is required.")
    intent = extract_intent(question_text, section_code)
    valid, validation_errors = validate_intent(intent)
    response = {
        "ok": True,
        "question_text": question_text,
        "intent": intent,
        "validation": {
            "valid": valid,
            "errors": validation_errors,
        },
    }
    if valid:
        try:
            dax_payload = generate_dax_from_intent(intent)
            response["dax"] = dax_payload["dax"]
            response["metric"] = dax_payload["metric"]
            response["measure"] = dax_payload["measure"]
            response["template_code"] = dax_payload["template_code"]
        except IntentValidationError as exc:
            response["validation"] = {"valid": False, "errors": [str(exc)]}
            return JsonResponse(response, status=400)
        except Exception as exc:
            return _json_error(str(exc))
    return JsonResponse(response)


def _ai_row_value(row: dict, *names: str):
    normalized = {
        re.sub(r"[^a-z0-9]+", "", str(key).lower()): value
        for key, value in row.items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", str(name).lower())
        if key in normalized:
            return normalized[key]
    return ""


def _execute_powerbi_info_query(dataset_id: str, info_name: str) -> tuple[list[dict], str]:
    query = f"EVALUATE INFO.{info_name}()"
    try:
        return execute_dataset_dax(dataset_id, query), ""
    except Exception as exc:
        return [], str(exc)


@require_http_methods(["POST"])
def ia_config_import_semantic_model_api(request, section_code):
    section = _ia_get_section_or_404(section_code)
    payload = _ia_payload(request)
    dataset_name = str(payload.get("dataset_name") or "FPR Global DB + RLS").strip()
    try:
        dataset_id = str(payload.get("dataset_id") or "").strip() or resolve_workspace_dataset_id(dataset_name)
    except Exception as exc:
        return _json_error(str(exc), status=400)
    workspace_id = env_value("POWERBI_WORKSPACE_ID", "a378c518-bfc4-4cd7-a49d-ba40394db80f")
    imported_at = timezone.now()

    imported = {"tables": 0, "columns": 0, "measures": 0, "relationships": 0}
    errors = {}

    tables, error = _execute_powerbi_info_query(dataset_id, "TABLES")
    if error:
        errors["tables"] = error
    for row in tables:
        table_name = str(_ai_row_value(row, "Name", "Table", "TableName") or "").strip()
        if not table_name:
            continue
        AISemanticTable.objects.update_or_create(
            section=section,
            table_name=table_name,
            defaults={
                "display_name": table_name,
                "description": str(_ai_row_value(row, "Description") or ""),
                "source_report": dataset_name,
                "dataset_id": dataset_id,
                "workspace_id": workspace_id,
                "imported_at": imported_at,
                "business_description": str(_ai_row_value(row, "Description") or ""),
                "validation_status": "Imported",
                "is_active": True,
            },
        )
        imported["tables"] += 1

    columns, error = _execute_powerbi_info_query(dataset_id, "COLUMNS")
    if error:
        errors["columns"] = error
    for row in columns:
        table_name = str(_ai_row_value(row, "Table", "TableName", "ExplicitDataTypeTable", "SourceTable") or "").strip()
        column_name = str(_ai_row_value(row, "Name", "Column", "ColumnName") or "").strip()
        if not table_name or not column_name:
            continue
        AISemanticColumn.objects.update_or_create(
            section=section,
            table_name=table_name,
            column_name=column_name,
            defaults={
                "display_name": column_name,
                "data_type": str(_ai_row_value(row, "DataType", "Type", "ExplicitDataType") or ""),
                "description": str(_ai_row_value(row, "Description") or ""),
                "source_report": dataset_name,
                "dataset_id": dataset_id,
                "workspace_id": workspace_id,
                "imported_at": imported_at,
                "business_description": str(_ai_row_value(row, "Description") or ""),
                "validation_status": "Imported",
                "is_filter": False,
                "is_active": True,
            },
        )
        imported["columns"] += 1

    measures, error = _execute_powerbi_info_query(dataset_id, "MEASURES")
    if error:
        try:
            measures = discover_dataset_measures_rest(dataset_id)
            error = ""
        except Exception as exc:
            measures = []
            error = str(exc)
    if error:
        errors["measures"] = error
    for row in measures:
        measure_name = str(_ai_row_value(row, "Name", "Measure", "MeasureName") or "").strip()
        if not measure_name:
            continue
        AISemanticMeasure.objects.update_or_create(
            section=section,
            measure_name=measure_name,
            defaults={
                "display_name": measure_name,
                "description": str(_ai_row_value(row, "Description") or ""),
                "dax_name": f"[{measure_name}]",
                "unit": "",
                "category": str(_ai_row_value(row, "Display Folder", "DisplayFolder", "Category") or ""),
                "source_report": dataset_name,
                "dataset_id": dataset_id,
                "workspace_id": workspace_id,
                "imported_at": imported_at,
                "business_description": str(_ai_row_value(row, "Description") or ""),
                "validation_status": "Imported",
                "is_active": True,
            },
        )
        imported["measures"] += 1

    relationships, error = _execute_powerbi_info_query(dataset_id, "RELATIONSHIPS")
    if error:
        errors["relationships"] = error
    for row in relationships:
        parent_table = str(_ai_row_value(row, "FromTable", "ParentTable", "From Table") or "").strip()
        parent_column = str(_ai_row_value(row, "FromColumn", "ParentColumn", "From Column") or "").strip()
        child_table = str(_ai_row_value(row, "ToTable", "ChildTable", "To Table") or "").strip()
        child_column = str(_ai_row_value(row, "ToColumn", "ChildColumn", "To Column") or "").strip()
        if not parent_table or not parent_column or not child_table or not child_column:
            continue
        AISemanticRelationship.objects.update_or_create(
            section=section,
            parent_table=parent_table,
            parent_column=parent_column,
            child_table=child_table,
            child_column=child_column,
            defaults={
                "relationship_type": str(_ai_row_value(row, "Cardinality", "Relationship Type", "CrossFilteringBehavior") or ""),
                "source_report": dataset_name,
                "dataset_id": dataset_id,
                "workspace_id": workspace_id,
                "imported_at": imported_at,
                "validation_status": "Imported",
                "is_active": True,
            },
        )
        imported["relationships"] += 1

    return JsonResponse(
        {
            "ok": True,
            "dataset_name": dataset_name,
            "dataset_id": dataset_id,
            "imported": imported,
            "errors": errors,
        }
    )


KB_RESOURCE_TYPES = {
    "business-glossary": {
        "model": KnowledgeBusinessGlossary,
        "columns": ["term", "category", "related_kpi", "validation_status", "is_active"],
        "search_fields": ["term", "business_definition", "category", "related_kpi", "related_powerbi_measure"],
        "fields": ["term", "business_definition", "category", "related_kpi", "related_powerbi_measure", "related_table", "related_column", "example_usage", "owner", "validation_status", "is_active"],
    },
    "kpi-dictionary": {
        "model": KnowledgeKPIDictionary,
        "columns": ["kpi_code", "kpi_name", "powerbi_measure_name", "unit", "validation_status", "is_active"],
        "search_fields": ["kpi_code", "kpi_name", "business_definition", "powerbi_measure_name"],
        "fields": ["kpi_code", "kpi_name", "business_definition", "formula_description", "powerbi_measure_name", "unit", "target", "warning_threshold", "critical_threshold", "aggregation_rule", "default_time_grain", "owner", "validation_status", "is_active"],
    },
    "mining-terminology": {
        "model": KnowledgeMiningTerminology,
        "columns": ["term", "category", "related_process", "validation_status", "is_active"],
        "search_fields": ["term", "definition", "category", "related_process"],
        "fields": ["term", "definition", "category", "related_process", "example", "owner", "validation_status", "is_active"],
    },
    "question-library": {
        "model": KnowledgeQuestion,
        "columns": ["question_text", "intent_type", "language", "difficulty_level", "validation_status", "is_active"],
        "search_fields": ["question_text", "intent_type", "expected_answer_style"],
        "fields": ["question_text", "intent_type", "expected_json_intent", "expected_dax", "expected_answer_style", "language", "difficulty_level", "owner", "validation_status", "is_active"],
    },
    "synonym-library": {
        "model": KnowledgeSynonym,
        "columns": ["canonical_term", "synonym", "entity_type", "language", "confidence", "validation_status", "is_active"],
        "search_fields": ["canonical_term", "synonym", "entity_type"],
        "fields": ["canonical_term", "synonym", "entity_type", "language", "confidence", "owner", "validation_status", "is_active"],
    },
    "business-rules": {
        "model": KnowledgeBusinessRule,
        "columns": ["rule_name", "kpi", "condition", "validation_status", "is_active"],
        "search_fields": ["rule_name", "kpi", "condition", "rule_description", "default_behavior"],
        "fields": ["rule_name", "kpi", "condition", "rule_description", "default_behavior", "required_filters", "missing_filter_behavior", "owner", "validation_status", "is_active"],
    },
    "prompt-library": {
        "model": KnowledgePrompt,
        "columns": ["prompt_name", "prompt_type", "version", "validation_status", "is_active"],
        "search_fields": ["prompt_name", "prompt_type", "prompt_content", "version"],
        "fields": ["prompt_name", "prompt_type", "prompt_content", "version", "created_by", "owner", "validation_status", "is_active"],
    },
    "recommended-actions": {
        "model": KnowledgeRecommendedAction,
        "columns": ["kpi", "condition", "priority", "validation_status", "is_active"],
        "search_fields": ["kpi", "condition", "business_context", "recommended_action"],
        "fields": ["kpi", "condition", "business_context", "recommended_action", "priority", "owner", "validation_status", "is_active"],
    },
    "ai-logs": {
        "model": KnowledgeAILog,
        "readonly": True,
        "columns": ["created_at", "user_question", "detected_section", "status", "execution_time_ms", "error_message"],
        "search_fields": ["user_question", "detected_section", "generated_dax", "final_answer", "error_message"],
        "fields": ["user_question", "detected_section", "extracted_intent", "generated_dax", "powerbi_result", "final_answer", "status", "error_message", "execution_time_ms", "token_usage"],
    },
    "user-feedback": {
        "model": KnowledgeUserFeedback,
        "columns": ["created_at", "rating", "was_answer_useful", "feedback_comment"],
        "search_fields": ["feedback_comment", "corrected_answer"],
        "fields": ["rating", "feedback_comment", "was_answer_useful", "corrected_intent", "corrected_answer"],
    },
}


def _kb_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "quantize"):
        return str(value)
    return value


def _kb_item_payload(item, fields: list[str] | None = None) -> dict:
    fields = fields or [field.name for field in item._meta.fields]
    payload = {"id": item.id}
    for field in fields:
        if hasattr(item, field):
            payload[field] = _kb_value(getattr(item, field))
    if hasattr(item, "section_id"):
        payload["section"] = item.section.code if item.section_id else ""
        payload["section_name"] = item.section.name if item.section_id else ""
    if hasattr(item, "user_id"):
        payload["user"] = item.user.username if item.user_id else ""
    return payload


def _kb_filter_queryset(queryset, model, request, search_fields):
    section_code = request.GET.get("section", "").strip()
    validation_status = request.GET.get("status", "").strip()
    active = request.GET.get("active", "").strip().lower()
    query = request.GET.get("q", "").strip()

    if section_code and hasattr(model, "section"):
        queryset = queryset.filter(section__code=section_code)
    if validation_status and hasattr(model, "validation_status"):
        queryset = queryset.filter(validation_status=validation_status)
    if active in {"1", "true", "yes"} and hasattr(model, "is_active"):
        queryset = queryset.filter(is_active=True)
    elif active in {"0", "false", "no"} and hasattr(model, "is_active"):
        queryset = queryset.filter(is_active=False)
    if query and search_fields:
        q_filter = models.Q()
        for field in search_fields:
            q_filter |= models.Q(**{f"{field}__icontains": query})
        queryset = queryset.filter(q_filter)
    return queryset


def _kb_apply_payload(item, payload: dict, fields: list[str], section=None):
    if section is not None and hasattr(item, "section"):
        item.section = section
    for field in fields:
        if field in {"created_at", "updated_at"}:
            continue
        if field == "is_active":
            setattr(item, field, _ia_normalize_bool(payload.get(field), getattr(item, field, True)))
            continue
        if field in {"expected_json_intent", "corrected_intent", "extracted_intent", "powerbi_result", "token_usage"}:
            setattr(item, field, _ia_json_object(payload, item, field))
            continue
        value = payload.get(field, getattr(item, field, ""))
        if field in {"target", "warning_threshold", "critical_threshold", "confidence"}:
            value = None if value in ("", None) else value
        if field in {"priority", "rating", "execution_time_ms"}:
            value = _ia_int(payload, item, field, 0)
        if field == "was_answer_useful":
            value = _ia_normalize_bool(payload.get(field), getattr(item, field, False))
        setattr(item, field, value)
    return item


def _kb_powerbi_metadata_items(request) -> list[dict]:
    rows = []
    metadata_models = [
        ("Table", AISemanticTable, ["table_name", "display_name", "description", "business_description", "source_report", "dataset_id", "workspace_id", "validation_status", "is_active"]),
        ("Column", AISemanticColumn, ["table_name", "column_name", "display_name", "data_type", "business_description", "source_report", "dataset_id", "workspace_id", "validation_status", "is_active"]),
        ("Measure", AISemanticMeasure, ["measure_name", "display_name", "dax_name", "unit", "category", "business_description", "source_report", "dataset_id", "workspace_id", "validation_status", "is_active"]),
        ("Relationship", AISemanticRelationship, ["parent_table", "parent_column", "child_table", "child_column", "relationship_type", "business_description", "source_report", "dataset_id", "workspace_id", "validation_status", "is_active"]),
        ("Page", AIPowerBIPage, ["page_name", "report_name", "report_id", "page_display_name", "description", "is_default_page", "is_active"]),
    ]
    for item_type, model, fields in metadata_models:
        queryset = _kb_filter_queryset(model.objects.all(), model, request, ["display_name", "description", "business_description"] if hasattr(model, "business_description") else ["page_name", "report_name", "page_display_name"])
        for item in queryset.order_by("-updated_at")[:500]:
            payload = _kb_item_payload(item, fields)
            payload["item_type"] = item_type
            rows.append(payload)
    return rows


def _kb_overview_payload() -> dict:
    sections = get_active_section_objects()
    total_items = (
        AISemanticTable.objects.count()
        + AISemanticColumn.objects.count()
        + AISemanticMeasure.objects.count()
        + AISemanticRelationship.objects.count()
        + KnowledgeBusinessGlossary.objects.count()
        + KnowledgeKPIDictionary.objects.count()
        + KnowledgeMiningTerminology.objects.count()
        + KnowledgeQuestion.objects.count()
        + KnowledgeSynonym.objects.count()
        + KnowledgeBusinessRule.objects.count()
        + KnowledgePrompt.objects.count()
        + KnowledgeRecommendedAction.objects.count()
    )
    semantic_import_dates = [
        value
        for value in [
            AISemanticTable.objects.order_by("-imported_at").values_list("imported_at", flat=True).first(),
            AISemanticColumn.objects.order_by("-imported_at").values_list("imported_at", flat=True).first(),
            AISemanticMeasure.objects.order_by("-imported_at").values_list("imported_at", flat=True).first(),
        ]
        if value
    ]
    coverage = []
    coverage_scores = []
    for section in sections:
        metrics = AIMetricMapping.objects.filter(section=section, is_active=True).count()
        semantic = AISemanticMeasure.objects.filter(section=section, is_active=True).count() + AISemanticTable.objects.filter(section=section, is_active=True).count()
        synonyms = KnowledgeSynonym.objects.filter(section=section, is_active=True).count() + AISynonym.objects.filter(section=section, is_active=True).count()
        questions = KnowledgeQuestion.objects.filter(section=section, is_active=True).count() + AIQuestionExample.objects.filter(section=section, is_active=True).count()
        kpis = KnowledgeKPIDictionary.objects.filter(section=section, is_active=True).count() + AIKPITarget.objects.filter(section=section, is_active=True).count()
        rules = KnowledgeBusinessRule.objects.filter(section=section, is_active=True).count() + AIBusinessRule.objects.filter(section=section, is_active=True).count()
        score = round(sum(1 for value in [semantic, synonyms, questions, kpis, rules] if value > 0) / 5 * 100)
        coverage_scores.append(score)
        coverage.append(
            {
                "section": section.name,
                "code": section.code,
                "metadata": semantic,
                "synonyms": synonyms,
                "questions": questions,
                "kpis": kpis,
                "rules": rules,
                "score": score,
                "metrics": metrics,
            }
        )
    return {
        "total_items": total_items,
        "semantic_tables": AISemanticTable.objects.count(),
        "semantic_measures": AISemanticMeasure.objects.count(),
        "synonyms": KnowledgeSynonym.objects.count() + AISynonym.objects.count(),
        "question_examples": KnowledgeQuestion.objects.count() + AIQuestionExample.objects.count() + AIFewShotExample.objects.count(),
        "business_rules": KnowledgeBusinessRule.objects.count() + AIBusinessRule.objects.count(),
        "prompts": KnowledgePrompt.objects.count() + AIPromptTemplate.objects.count(),
        "recommended_actions": KnowledgeRecommendedAction.objects.count() + AIRecommendedAction.objects.count(),
        "last_imported_at": max(semantic_import_dates).isoformat() if semantic_import_dates else "",
        "coverage_score": round(sum(coverage_scores) / len(coverage_scores)) if coverage_scores else 0,
        "coverage": coverage,
    }


@require_http_methods(["GET"])
def knowledge_base_home(request):
    sections = [_ia_section_payload(section) for section in get_active_section_objects()]
    return render(
        request,
        "reports/knowledge_base.html",
        {
            "active_section": "knowledge-base",
            "sections": sections,
            "sidebar_stats": [
                {"label": "Knowledge", "value": "Base"},
                {"label": "Sections", "value": len(sections)},
            ],
        },
    )


@require_http_methods(["GET"])
def knowledge_base_overview_api(request):
    return JsonResponse({"ok": True, "overview": _kb_overview_payload()})


@require_http_methods(["GET", "POST"])
def knowledge_base_collection_api(request, resource_type):
    if resource_type == "powerbi-metadata":
        return JsonResponse({"ok": True, "items": _kb_powerbi_metadata_items(request)})
    if resource_type not in KB_RESOURCE_TYPES:
        return _json_error("Unsupported Knowledge Base resource type.", status=404)
    config = KB_RESOURCE_TYPES[resource_type]
    model = config["model"]
    if request.method == "GET":
        queryset = _kb_filter_queryset(model.objects.all(), model, request, config.get("search_fields", []))
        order_field = "-created_at" if resource_type in {"ai-logs", "user-feedback"} else "-updated_at"
        items = [_kb_item_payload(item) for item in queryset.order_by(order_field)[:500]]
        return JsonResponse({"ok": True, "items": items})

    if config.get("readonly"):
        return _json_error("This Knowledge Base resource is read-only.", status=405)
    payload = _ia_payload(request)
    section = _ia_get_section_or_404(str(payload.get("section") or request.GET.get("section") or "performance"))
    try:
        item = _kb_apply_payload(model(), payload, config["fields"], section=section)
        item.save()
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "item": _kb_item_payload(item)}, status=201)


@require_http_methods(["PUT", "DELETE"])
def knowledge_base_item_api(request, resource_type, item_id):
    if resource_type not in KB_RESOURCE_TYPES:
        return _json_error("Unsupported Knowledge Base resource type.", status=404)
    config = KB_RESOURCE_TYPES[resource_type]
    if config.get("readonly"):
        return _json_error("This Knowledge Base resource is read-only.", status=405)
    model = config["model"]
    item = get_object_or_404(model, id=item_id)
    if request.method == "DELETE":
        if hasattr(item, "is_active"):
            item.is_active = False
            item.save(update_fields=["is_active", "updated_at"] if hasattr(item, "updated_at") else ["is_active"])
            return JsonResponse({"ok": True, "deactivated": True})
        item.delete()
        return JsonResponse({"ok": True, "deleted": True})
    payload = _ia_payload(request)
    section = _ia_get_section_or_404(str(payload.get("section") or item.section.code)) if hasattr(item, "section") else None
    try:
        item = _kb_apply_payload(item, payload, config["fields"], section=section)
        item.save()
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "item": _kb_item_payload(item)})


@require_http_methods(["POST"])
def knowledge_base_generate_api(request):
    payload = _ia_payload(request)
    section_code = str(payload.get("section") or "").strip()
    sections = AIConfigSection.objects.filter(is_active=True)
    if section_code:
        sections = sections.filter(code=section_code)
    created = {
        "kpis": 0,
        "glossary": 0,
        "terminology": 0,
        "questions": 0,
        "synonyms": 0,
        "rules": 0,
        "prompts": 0,
        "actions": 0,
        "metadata_marked": 0,
    }
    for section in sections:
        for metric in AIMetricMapping.objects.filter(section=section, is_active=True):
            item, was_created = KnowledgeKPIDictionary.objects.update_or_create(
                section=section,
                kpi_code=metric.metric_code,
                defaults={
                    "kpi_name": metric.metric_label,
                    "business_definition": metric.description or f"Business KPI for {metric.metric_label}.",
                    "powerbi_measure_name": metric.powerbi_measure_name,
                    "unit": "",
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )
            created["kpis"] += int(was_created)
            _, glossary_created = KnowledgeBusinessGlossary.objects.update_or_create(
                section=section,
                term=metric.metric_label,
                defaults={
                    "business_definition": metric.description or f"Mining 360 KPI mapped to {metric.powerbi_measure_name}.",
                    "category": "KPI",
                    "related_kpi": metric.metric_code,
                    "related_powerbi_measure": metric.powerbi_measure_name,
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )
            created["glossary"] += int(glossary_created)
        for synonym in AISynonym.objects.filter(section=section, is_active=True):
            _, was_created = KnowledgeSynonym.objects.update_or_create(
                section=section,
                canonical_term=synonym.canonical_value,
                synonym=synonym.synonym_value,
                entity_type="KPI" if synonym.entity_type in {"metric", "measure"} else "Business Term",
                defaults={
                    "language": synonym.language,
                    "confidence": 1,
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )
            created["synonyms"] += int(was_created)
        for question in AIQuestionExample.objects.filter(section=section, is_active=True):
            _, was_created = KnowledgeQuestion.objects.update_or_create(
                section=section,
                question_text=question.question_text,
                defaults={
                    "intent_type": "Single KPI",
                    "expected_json_intent": question.expected_json_intent,
                    "language": question.language,
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )
            created["questions"] += int(was_created)
        for rule in AIBusinessRule.objects.filter(section=section, is_active=True):
            _, was_created = KnowledgeBusinessRule.objects.update_or_create(
                section=section,
                rule_name=rule.rule_name,
                defaults={
                    "kpi": rule.metric_code,
                    "condition": rule.condition,
                    "rule_description": rule.action,
                    "default_behavior": rule.default_value,
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )
            created["rules"] += int(was_created)
        for prompt in AIPromptTemplate.objects.filter(section=section, is_active=True):
            _, was_created = KnowledgePrompt.objects.update_or_create(
                section=section,
                prompt_name=prompt.template_name,
                prompt_type=prompt.get_prompt_type_display(),
                defaults={
                    "prompt_content": prompt.prompt_template,
                    "version": "1.0",
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )
            created["prompts"] += int(was_created)
        for action in AIRecommendedAction.objects.filter(section=section, is_active=True):
            _, was_created = KnowledgeRecommendedAction.objects.update_or_create(
                section=section,
                kpi=action.metric_code,
                condition=action.condition,
                defaults={
                    "recommended_action": action.recommendations,
                    "priority": action.priority,
                    "validation_status": "To Review",
                    "is_active": True,
                },
            )
            created["actions"] += int(was_created)
        metadata_updates = (
            AISemanticTable.objects.filter(section=section, validation_status="Imported").update(validation_status="To Review")
            + AISemanticColumn.objects.filter(section=section, validation_status="Imported").update(validation_status="To Review")
            + AISemanticMeasure.objects.filter(section=section, validation_status="Imported").update(validation_status="To Review")
            + AISemanticRelationship.objects.filter(section=section, validation_status="Imported").update(validation_status="To Review")
        )
        created["metadata_marked"] += metadata_updates
    return JsonResponse({"ok": True, "generated": created, "overview": _kb_overview_payload()})


@require_http_methods(["POST"])
def knowledge_base_coverage_test_api(request):
    payload = _ia_payload(request)
    section_code = str(payload.get("section") or "").strip() or "performance"
    kpi = str(payload.get("kpi") or "").strip()
    question = str(payload.get("question") or "").strip()
    intent = {}
    if question:
        try:
            intent = extract_intent(question, section_code)
            kpi = kpi or str(intent.get("metric") or "")
        except Exception:
            intent = {}
    section = get_section_by_code(section_code) or _ia_get_section_or_404(section_code)
    checks = {
        "kpi_defined": bool(kpi and (KnowledgeKPIDictionary.objects.filter(section=section, kpi_code=kpi, validation_status="Validated", is_active=True).exists() or AIMetricMapping.objects.filter(section=section, metric_code=kpi, is_active=True).exists())),
        "measure_mapped": bool(kpi and AIMetricMapping.objects.filter(section=section, metric_code=kpi, is_active=True).exists()),
        "filters_mapped": AIFilterMapping.objects.filter(section=section, is_active=True).exists(),
        "synonyms_available": KnowledgeSynonym.objects.filter(section=section, is_active=True).exists() or AISynonym.objects.filter(section=section, is_active=True).exists(),
        "dax_template": AIDaxTemplate.objects.filter(section=section, is_active=True).exists(),
        "business_rules": KnowledgeBusinessRule.objects.filter(section=section, is_active=True).exists() or AIBusinessRule.objects.filter(section=section, is_active=True).exists(),
        "recommended_actions": KnowledgeRecommendedAction.objects.filter(section=section, is_active=True).exists() or AIRecommendedAction.objects.filter(section=section, is_active=True).exists(),
    }
    score = round(sum(1 for value in checks.values() if value) / len(checks) * 100)
    return JsonResponse({"ok": True, "intent": intent, "checks": checks, "coverage_score": score})


def _mask_secret(value: str) -> str:
    return "********" if value else ""


def _system_db_payload(item: SystemDatabaseConfig, reveal: bool = False) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "engine": item.engine,
        "purpose": item.purpose,
        "host": item.host,
        "port": item.port or "",
        "database_name": item.database_name,
        "schema_name": item.schema_name,
        "username": item.username,
        "password": item.password if reveal else _mask_secret(item.password),
        "driver": item.driver,
        "connection_options": item.connection_options,
        "is_default": item.is_default,
        "is_active": item.is_active,
        "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else "",
        "last_status": item.last_status,
        "last_message": item.last_message,
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }


def _system_table_payload(item: SystemManagedTable) -> dict:
    return {
        "id": item.id,
        "database_config": item.database_config_id,
        "database_config_name": item.database_config.name if item.database_config_id else "",
        "schema_name": item.schema_name,
        "table_name": item.table_name,
        "category": item.category,
        "model_name": item.model_name,
        "description": item.description,
        "row_count": item.row_count,
        "last_synced_at": item.last_synced_at.isoformat() if item.last_synced_at else "",
        "is_active": item.is_active,
    }


def _ensure_default_system_config() -> SystemDatabaseConfig:
    config, _ = SystemDatabaseConfig.objects.update_or_create(
        name="Mining360 SQL Server",
        defaults={
            "engine": "SQL Server",
            "purpose": "Primary Mining360 configuration database",
            "host": "172.17.0.111",
            "port": 1433,
            "database_name": "Mining360",
            "schema_name": "dbo",
            "username": "djibril",
            "password": "Djimen.12345",
            "driver": "pytds / ODBC Driver 18 for SQL Server",
            "connection_options": {"validate_host": False, "enc_login_only": True},
            "is_default": True,
            "is_active": True,
        },
    )
    return config


def _system_config_table_category(model_name: str, table_name: str) -> str:
    if table_name.startswith("bp_"):
        return "Business Performance"
    if table_name.startswith("ai_"):
        return "IA Config"
    if table_name.startswith("kb_"):
        return "Knowledge Base"
    if table_name in {"BrowserList", "reports_databrowsercolumn", "reports_databrowsersynclog"}:
        return "Data Browser"
    if table_name in {"LiveSourceConfig", "LiveSourceCustomView"}:
        return "Sources"
    if table_name in {"PowerBIReportAlias"}:
        return "Power BI"
    if table_name in {"ResourceFile"}:
        return "Resources"
    if "log" in table_name.lower() or "run" in table_name.lower():
        return "Logs"
    return "Django Config"


def _refresh_system_table_registry() -> int:
    from .mining360_repository import CONFIG_MODEL_NAMES

    config = _ensure_default_system_config()
    updated = 0
    for model_name in CONFIG_MODEL_NAMES:
        try:
            model = apps.get_model("reports", model_name)
        except Exception:
            continue
        table_name = model._meta.db_table
        row_count = model.objects.count()
        SystemManagedTable.objects.update_or_create(
            schema_name="dbo",
            table_name=table_name,
            defaults={
                "database_config": config,
                "category": _system_config_table_category(model_name, table_name),
                "model_name": model_name,
                "description": f"Django model mirror table for {model_name}.",
                "row_count": row_count,
                "last_synced_at": timezone.now(),
                "is_active": True,
            },
        )
        updated += 1
    for table_name, category in [
        ("PowerBIReportAlias", "Power BI"),
        ("ResourceFile", "Resources"),
        ("LiveSourceConfig", "Sources"),
        ("LiveSourceCustomView", "Sources"),
    ]:
        SystemManagedTable.objects.update_or_create(
            schema_name="dbo",
            table_name=table_name,
            defaults={
                "database_config": config,
                "category": category,
                "description": f"SQL Server managed table for {category}.",
                "last_synced_at": timezone.now(),
                "is_active": True,
            },
        )
        updated += 1
    return updated


@require_http_methods(["GET"])
def system_config_home(request):
    _ensure_default_system_config()
    return render(
        request,
        "reports/system_config.html",
        {
            "active_section": "system-config",
            "sidebar_stats": [
                {"label": "Config", "value": SystemDatabaseConfig.objects.count()},
                {"label": "Tables", "value": SystemManagedTable.objects.count()},
            ],
        },
    )


@require_http_methods(["GET", "POST"])
def system_database_configs_api(request):
    _ensure_default_system_config()
    if request.method == "GET":
        query = request.GET.get("q", "").strip()
        queryset = SystemDatabaseConfig.objects.all()
        if query:
            queryset = queryset.filter(
                models.Q(name__icontains=query)
                | models.Q(engine__icontains=query)
                | models.Q(host__icontains=query)
                | models.Q(database_name__icontains=query)
                | models.Q(username__icontains=query)
            )
        return JsonResponse({"ok": True, "items": [_system_db_payload(item) for item in queryset]})

    payload = _request_payload(request)
    item = SystemDatabaseConfig()
    return _save_system_database_config(item, payload, status=201)


def _save_system_database_config(item: SystemDatabaseConfig, payload: dict, status: int = 200):
    try:
        item.name = str(payload.get("name", item.name or "")).strip()
        item.engine = str(payload.get("engine", item.engine or "SQL Server")).strip()
        item.purpose = str(payload.get("purpose", item.purpose or "")).strip()
        item.host = str(payload.get("host", item.host or "")).strip()
        port = payload.get("port", item.port)
        item.port = int(port) if str(port or "").strip() else None
        item.database_name = str(payload.get("database_name", item.database_name or "")).strip()
        item.schema_name = str(payload.get("schema_name", item.schema_name or "")).strip()
        item.username = str(payload.get("username", item.username or "")).strip()
        password = str(payload.get("password", "") or "")
        if password and password != "********":
            item.password = password
        item.driver = str(payload.get("driver", item.driver or "")).strip()
        options = payload.get("connection_options", item.connection_options or {})
        if isinstance(options, str):
            options = json.loads(options) if options.strip() else {}
        item.connection_options = options if isinstance(options, dict) else {}
        item.is_default = _ia_normalize_bool(payload.get("is_default"), item.is_default)
        item.is_active = _ia_normalize_bool(payload.get("is_active"), item.is_active)
        if not item.name or not item.host:
            return _json_error("Name and host are required.")
        if item.is_default:
            SystemDatabaseConfig.objects.exclude(id=item.id).update(is_default=False)
        item.save()
    except Exception as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "item": _system_db_payload(item)}, status=status)


@require_http_methods(["PUT", "DELETE"])
def system_database_config_item_api(request, config_id):
    item = get_object_or_404(SystemDatabaseConfig, id=config_id)
    if request.method == "DELETE":
        item.is_active = False
        item.save(update_fields=["is_active", "updated_at"])
        return JsonResponse({"ok": True, "deactivated": True})
    return _save_system_database_config(item, _request_payload(request))


@require_http_methods(["POST"])
def system_database_config_verify_api(request, config_id):
    item = get_object_or_404(SystemDatabaseConfig, id=config_id)
    try:
        with connect(
            server=item.host,
            database=item.database_name or "master",
            user=item.username or None,
            password=item.password or None,
            port=item.port or None,
        ) as connection:
            row = connection.cursor().execute("SELECT @@SERVERNAME, DB_NAME()").fetchone()
        item.last_status = "Active"
        item.last_message = f"Connected to {row[0]} / {row[1]}"
        item.last_verified_at = timezone.now()
        item.save(update_fields=["last_status", "last_message", "last_verified_at", "updated_at"])
        return JsonResponse({"ok": True, "status": item.last_status, "message": item.last_message})
    except Exception as exc:
        item.last_status = "Failed"
        item.last_message = str(exc)
        item.last_verified_at = timezone.now()
        item.save(update_fields=["last_status", "last_message", "last_verified_at", "updated_at"])
        return _json_error(str(exc), status=400)


@require_http_methods(["GET", "POST"])
def system_managed_tables_api(request):
    if request.method == "POST":
        count = _refresh_system_table_registry()
        return JsonResponse({"ok": True, "refreshed": count})
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    queryset = SystemManagedTable.objects.select_related("database_config").all()
    if category:
        queryset = queryset.filter(category=category)
    if query:
        queryset = queryset.filter(
            models.Q(table_name__icontains=query)
            | models.Q(schema_name__icontains=query)
            | models.Q(category__icontains=query)
            | models.Q(model_name__icontains=query)
            | models.Q(description__icontains=query)
        )
    return JsonResponse({"ok": True, "items": [_system_table_payload(item) for item in queryset]})


def resources(request):
    query = request.GET.get("q", "")
    selected_section = request.GET.get("section", "")
    selected_category = request.GET.get("category", "")
    selected_level = request.GET.get("level", "")
    resource_source = "Local files"
    resource_items = list_resources(
        query,
        section=selected_section,
        category=selected_category,
        level=selected_level,
    )
    facets = list_resource_facets()
    return render(
        request,
        "reports/resources.html",
        {
            "active_section": "resources",
            "resources": resource_items,
            "resource_count": len(resource_items),
            "query": query,
            "selected_section": selected_section,
            "selected_category": selected_category,
            "selected_level": selected_level,
            "sections": facets["sections"],
            "categories": facets["categories"],
            "levels": facets["levels"],
            "section_cards": facets["section_cards"],
            "resource_source": resource_source,
            "sidebar_stats": [
                {"label": "Files", "value": len(resource_items)},
                {"label": "Source", "value": resource_source},
            ],
        },
    )


@require_http_methods(["POST"])
def resource_upload(request):
    uploaded_file = request.FILES.get("file")
    title = request.POST.get("title", "").strip()
    section = request.POST.get("section", "").strip()
    category = request.POST.get("category", "").strip()
    level = request.POST.get("level", "").strip()
    if not uploaded_file:
        messages.error(request, "Document file is required.")
        return redirect("resources")
    if not title:
        title = uploaded_file.name.rsplit(".", 1)[0]
    if not section or not category:
        messages.error(request, "Section and category are required.")
        return redirect("resources")

    try:
        resource = save_uploaded_resource(
            uploaded_file,
            title=title,
            section=section,
            category=category,
            level=level or "General",
        )
        try:
            from .mining360_repository import create_tables, sync_resources

            with connect(database="Mining360") as connection:
                create_tables(connection)
                sync_resources(connection)
        except Exception as exc:
            messages.warning(request, f"Document uploaded, but SQL Server sync failed: {exc}")
        else:
            messages.success(request, f"Document uploaded and indexed: {resource.title}.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("resources")


def resource_detail(request, resource_id):
    try:
        resource = get_resource(resource_id)
        text_content = ""
        if resource.is_text:
            text_content = read_text_resource(get_resource_path(resource_id))
    except (ValueError, FileNotFoundError):
        raise Http404("Resource not found")

    return render(
        request,
        "reports/resource_detail.html",
        {
            "active_section": "resources",
            "resource": resource,
            "text_content": text_content,
            "sidebar_stats": [
                {"label": "File", "value": resource.extension},
                {"label": "Class", "value": resource.section},
            ],
        },
    )


@xframe_options_sameorigin
def resource_file(request, resource_id):
    try:
        resource = get_resource(resource_id)
        path = get_resource_path(resource_id)
    except (ValueError, FileNotFoundError):
        raise Http404("Resource not found")

    return FileResponse(
        path.open("rb"),
        as_attachment=False,
        filename=resource.filename,
        content_type=resource.mime_type,
    )


BP_PAGES = {
    "overview": ("Overview", "Executive view of fleet and commercial performance."),
    "customers": ("Customers", "Customer portfolio, segmentation and contribution."),
    "parts-sales": ("Parts Sales", "Parts revenue analysis and transactions."),
    "machine-sales": ("Machine Sales", "Prime revenue and machine sales analysis."),
    "forecast": ("Forecast & Opportunities", "Reserved for predictive scenarios."),
}

BUSINESS_PERFORMANCE_ENABLED = False


def _business_performance_access(user) -> bool:
    if _user_is_platform_admin(user):
        return True
    platform_user = getattr(user, "platformuser", None)
    return bool(
        platform_user
        and platform_user.is_active
        and platform_user.can_access_reporting
        and platform_user.business_performance_role
    )


def _bp_filters(request) -> dict:
    filters = {}
    for key in BusinessPerformanceService.FILTER_KEYS:
        values = []
        for raw in request.GET.getlist(key):
            values.extend(item.strip() for item in raw.split(",") if item.strip())
        if values:
            filters[key] = values
    return filters


def _bp_json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _business_performance_disabled_response(request):
    if wants_json(request):
        return JsonResponse({"ok": False, "error": "Business Performance is currently disabled."}, status=404)
    raise Http404("Business Performance is currently disabled.")


@login_required
def business_performance_home(request, page="overview", customer=None):
    if not BUSINESS_PERFORMANCE_ENABLED:
        return _business_performance_disabled_response(request)
    if not _business_performance_access(request.user):
        return JsonResponse({"ok": False, "error": "Business Performance access required."}, status=403)
    page = page if page in BP_PAGES else "overview"
    config = BusinessPerformanceConfig.objects.filter(is_active=True).first()
    return render(
        request,
        "reports/business_performance.html",
        {
            "active_section": "business-performance",
            "page_code": page,
            "page_title": "Customer Details" if customer else BP_PAGES[page][0],
            "page_description": BP_PAGES[page][1],
            "customer": customer or "",
            "config": config,
            "is_bp_admin": _user_is_platform_admin(request.user),
            "bp_pages": BP_PAGES,
        },
    )


@login_required
def business_performance_customer(request, customer):
    if not BUSINESS_PERFORMANCE_ENABLED:
        return _business_performance_disabled_response(request)
    return business_performance_home(request, "customers", unquote(customer))


@login_required
def business_performance_api(request, section):
    if not BUSINESS_PERFORMANCE_ENABLED:
        return _business_performance_disabled_response(request)
    if not _business_performance_access(request.user):
        return JsonResponse({"ok": False, "error": "Business Performance access required."}, status=403)
    filters = _bp_filters(request)
    try:
        service = BusinessPerformanceService(request.user)
        if section == "overview":
            payload = service.overview(filters, request.GET.get("top_n"))
        elif section == "customers":
            payload = {"customers": service.customers(filters, int(request.GET.get("limit", 500)))}
        elif section in {"parts-sales", "machine-sales"}:
            category = {"parts-sales": "parts", "machine-sales": "prime"}[section]
            payload = {"rows": service.detail_rows(category, filters, int(request.GET.get("limit", 1000)))}
        elif section == "customer":
            customer = (request.GET.get("customer") or "").strip()
            if not customer:
                return JsonResponse({"ok": False, "error": "Customer is required."}, status=400)
            payload = service.customer_details(customer, filters)
        elif section == "filter-options":
            logical_name = (request.GET.get("filter") or "").strip()
            payload = {"filter": logical_name, "items": service.filter_options(logical_name, filters)}
        else:
            return JsonResponse({"ok": False, "error": "Unknown Business Performance endpoint."}, status=404)
        return JsonResponse({"ok": True, **payload})
    except MappingNotConfigured as exc:
        return JsonResponse({"ok": False, "code": "mapping_missing", "error": str(exc)}, status=422)
    except BusinessPerformanceError as exc:
        return JsonResponse({"ok": False, "code": "semantic_model_unavailable", "error": str(exc)}, status=503)
    except (TypeError, ValueError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@login_required
def business_performance_export(request, category, file_type):
    if not BUSINESS_PERFORMANCE_ENABLED:
        return _business_performance_disabled_response(request)
    if not _business_performance_access(request.user):
        return JsonResponse({"ok": False, "error": "Business Performance access required."}, status=403)
    category_map = {"parts": "parts", "prime": "prime", "fleet": "fleet", "customers": "customers"}
    if category not in category_map or file_type not in {"csv", "xlsx"}:
        raise Http404
    try:
        service = BusinessPerformanceService(request.user)
        filters = _bp_filters(request)
        rows = service.customers(filters, 10000) if category == "customers" else service.detail_rows(category, filters, 10000)
    except BusinessPerformanceError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
    columns = list(dict.fromkeys(key for row in rows for key in row.keys()))
    stamp = timezone.localdate().strftime("%Y")
    filename = f"Business_Performance_{category}_{stamp}.{file_type}"
    if file_type == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")
        writer = csv.DictWriter(response, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return response
    try:
        from openpyxl import Workbook
    except ImportError:
        return JsonResponse({"ok": False, "error": "Excel export requires openpyxl."}, status=500)
    from io import BytesIO
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Business Performance")
    sheet.append(columns)
    for row in rows:
        sheet.append([row.get(column) for column in columns])
    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def business_performance_config(request):
    if not BUSINESS_PERFORMANCE_ENABLED:
        return _business_performance_disabled_response(request)
    if not _user_is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    config, _ = BusinessPerformanceConfig.objects.get_or_create(name="Business Performance")
    fleet_mapping_names = {
        "active_fleet", "fleet_share", "parts_revenue_per_fleet", "prime_revenue_per_fleet",
        "total_revenue_per_fleet", "minesite", "equipment_type", "model", "fleet_status",
        "serial_number", "equipment_number",
    }
    return render(request, "reports/business_performance_config.html", {
        "active_section": "business-performance-config",
        "config": config,
        "mappings": BusinessPerformanceMapping.objects.exclude(logical_name__in=fleet_mapping_names),
    })


@login_required
@require_http_methods(["POST"])
def business_performance_config_api(request):
    if not BUSINESS_PERFORMANCE_ENABLED:
        return _business_performance_disabled_response(request)
    if not _user_is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)
    config, _ = BusinessPerformanceConfig.objects.get_or_create(name="Business Performance")
    editable = {
        "workspace_id", "semantic_model_name", "semantic_model_id", "report_id", "tenant_id",
        "authentication_mode", "api_endpoint", "xmla_endpoint", "default_currency",
        "default_date_range", "default_lob", "default_division", "cache_duration_seconds",
        "query_timeout_seconds", "top_n_default", "active_fleet_status_value",
        "opportunity_threshold_mode", "opportunity_fleet_threshold", "opportunity_revenue_threshold",
    }
    for field in editable:
        if field in payload:
            setattr(config, field, payload[field] if payload[field] != "" else None if field.endswith("_threshold") else "")
    config.save()
    for item in payload.get("mappings", []):
        mapping = BusinessPerformanceMapping.objects.filter(id=item.get("id")).first()
        if not mapping:
            continue
        for field in ("display_name", "table_name", "object_name", "data_type", "format_string", "description"):
            if field in item:
                setattr(mapping, field, str(item[field]).strip())
        for field in ("is_active", "is_visible", "is_required"):
            if field in item:
                setattr(mapping, field, bool(item[field]))
        mapping.save()
    cache.clear()
    return JsonResponse({"ok": True, "message": "Business Performance configuration saved."})


@login_required
@require_http_methods(["POST"])
def business_performance_import_model_api(request):
    if not BUSINESS_PERFORMANCE_ENABLED:
        return _business_performance_disabled_response(request)
    if not _user_is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    config, _ = BusinessPerformanceConfig.objects.get_or_create(name="Business Performance")
    try:
        dataset_id = config.semantic_model_id or resolve_workspace_dataset_id(config.semantic_model_name)
        measures, measure_error = _execute_powerbi_info_query(dataset_id, "MEASURES")
        columns, column_error = _execute_powerbi_info_query(dataset_id, "COLUMNS")
        if measure_error and column_error:
            raise RuntimeError(f"Measures: {measure_error}; Columns: {column_error}")
        config.semantic_model_id = dataset_id
        config.save(update_fields=["semantic_model_id", "updated_at"])
        normalized = lambda value: re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
        measure_catalog = {}
        for row in measures:
            name = str(_ai_row_value(row, "Name", "Measure", "MeasureName") or "").strip()
            if name:
                measure_catalog[normalized(name)] = name
        column_catalog = []
        for row in columns:
            table_name = str(_ai_row_value(row, "Table", "TableName", "SourceTable") or "").strip()
            column_name = str(_ai_row_value(row, "Name", "Column", "ColumnName") or "").strip()
            if table_name and column_name:
                column_catalog.append((table_name, column_name))
        matched = 0
        for mapping in BusinessPerformanceMapping.objects.all():
            candidates = {normalized(mapping.object_name), normalized(mapping.display_name), normalized(mapping.logical_name)}
            if mapping.object_type == "measure":
                match = next((measure_catalog[key] for key in candidates if key in measure_catalog), "")
                if match:
                    mapping.object_name = match
                    mapping.save(update_fields=["object_name", "updated_at"])
                    matched += 1
            else:
                match = next(((table, column) for table, column in column_catalog if normalized(column) in candidates), None)
                if match:
                    mapping.table_name, mapping.object_name = match
                    mapping.save(update_fields=["table_name", "object_name", "updated_at"])
                    matched += 1
        return JsonResponse({
            "ok": True, "dataset_id": dataset_id, "measures_found": len(measure_catalog),
            "columns_found": len(column_catalog), "mappings_matched": matched,
            "message": f"Semantic model imported. {matched} mappings matched; review before use.",
        })
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)


def report_detail(request, report_id):
    report = None
    reports = []
    embed_token = None
    error = None
    selected_role = request.GET.get("role") or "Global"

    try:
        reports = list_workspace_reports()
        report = get_workspace_report(str(report_id), reports)
        embed_token = generate_report_embed_token(report, [selected_role])
    except Exception as exc:
        error = str(exc)

    return render(
        request,
        "reports/detail.html",
        {
            "report": report,
            "reports": reports,
            "embed_token": embed_token,
            "error": error,
            "workspace_name": "Efficience Mine Workspace",
            "active_section": "reporting",
            "role_options": RLS_ROLE_OPTIONS,
            "selected_role": selected_role,
            "sidebar_stats": [
                {"label": "Reports", "value": len(reports)},
                {"label": "Role", "value": selected_role},
            ],
        },
    )


def data_quality_run(request):
    if request.method != "POST" or not _is_ajax_request(request):
        raise Http404("Not found")

    source_key = (request.POST.get("source_key") or request.GET.get("source_key") or "").strip()
    preview_url = (request.POST.get("preview_url") or request.GET.get("preview_url") or "").strip()
    control_key = (request.POST.get("control_key") or request.GET.get("control_key") or "").strip() or None
    payload_text = request.POST.get("payload") or request.GET.get("payload") or "{}"

    try:
        payload = json.loads(payload_text) if payload_text else {}
    except Exception:
        payload = {}

    if not source_key:
        return JsonResponse({"ok": False, "error": "Source key is required."}, status=400)
    if not preview_url:
        return JsonResponse({"ok": False, "error": "Preview target is required."}, status=400)

    try:
        source = get_live_source(source_key)
    except KeyError:
        return JsonResponse({"ok": False, "error": "Source not found."}, status=404)

    try:
        run, context, preview_payload, results, summary, score = _run_data_quality(source, preview_url, control_key, payload)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "run": {
                "id": run.id,
                "score": float(run.score),
                "status": run.status,
                "source_key": run.source_key,
                "source_name": run.source_name,
                "object_kind": run.object_kind,
                "object_name": run.object_name,
                "created_at": run.created_at.isoformat() if run.created_at else "",
                "finished_at": run.finished_at.isoformat() if run.finished_at else "",
                "total_rows": run.total_rows,
                "controls_count": run.controls_count,
                "summary": run.summary,
                "preview_url": run.request_payload.get("preview_url", ""),
            },
            "results": [serialize_result(result) for result in results],
            "summary": summary,
            "preview": preview_payload.get("preview", {}),
        },
    )


def data_quality_records(request, run_id: int, control_key: str):
    if request.method != "GET" or not _is_ajax_request(request):
        raise Http404("Not found")

    try:
        run = DataQualityRun.objects.get(id=run_id)
    except DataQualityRun.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Run not found."}, status=404)

    results = run.results if isinstance(run.results, list) else []
    result = next((item for item in results if isinstance(item, dict) and item.get("key") == control_key), None)
    if not result:
        return JsonResponse({"ok": False, "error": "Control not found in run."}, status=404)

    records = result.get("records") or []
    columns = list(records[0].keys()) if records else []
    return JsonResponse(
        {
            "ok": True,
            "run": {
                "id": run.id,
                "source_name": run.source_name,
                "object_name": run.object_name,
                "created_at": run.created_at.isoformat() if run.created_at else "",
            },
            "control": result,
            "columns": columns,
            "records": records,
        }
    )


def data_quality_export(request, run_id: int, control_key: str):
    try:
        run = DataQualityRun.objects.get(id=run_id)
    except DataQualityRun.DoesNotExist:
        raise Http404("Run not found")

    results = run.results if isinstance(run.results, list) else []
    result = next((item for item in results if isinstance(item, dict) and item.get("key") == control_key), None)
    if not result:
        raise Http404("Control not found")

    records = result.get("records") or []
    try:
        from io import BytesIO
        from openpyxl import Workbook
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Excel export unavailable: {exc}"}, status=500)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (result.get("name") or "Data Quality")[:31]
    columns = list(records[0].keys()) if records else ["message"]
    sheet.append(columns)
    if records:
        for record in records:
            sheet.append([_json_safe(record.get(column)) for column in columns])
    else:
        sheet.append(["No impacted records"])

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = f"dq_{run.source_key}_{control_key}_{run.id}.xlsx".replace(" ", "_")
    response = FileResponse(buffer, as_attachment=True, filename=filename)
    response["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response
