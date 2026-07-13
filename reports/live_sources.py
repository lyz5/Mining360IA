from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from textwrap import dedent

from django.utils.text import slugify

from .sqlserver import connect


@dataclass(frozen=True)
class LiveView:
    key: str
    name: str
    description: str
    sql: str


@dataclass(frozen=True)
class LiveSource:
    key: str
    name: str
    engine: str
    server: str
    database: str
    user: str
    password: str
    port: int
    owner: str
    status: str
    status_class: str
    description: str
    views: tuple[LiveView, ...]
    connection_details: dict[str, str] = field(default_factory=dict)
    is_active: bool = True
    last_verified: str = ""
    verification_status: str = "Unknown"
    verification_message: str = ""


LIVE_SOURCE_STATE_FILE = Path(__file__).with_name("live_sources_state.json")
CUSTOM_LIVE_SOURCE_FILE = Path(__file__).with_name("live_sources_custom.json")
SQL_SOURCE_CONFIG_ENABLED = True


BODEFM_DOWNTIMES_SQL = dedent(
    """
    SELECT 
        ec.[EVENTCHAINID],
        ec.[EQUIPID] AS [Equip No.],
        ecv.[Col1588] AS [Comments],
        CAST(ecv.[Col3547] AS datetime) AS [Start Hours],
        CAST(ecv.[Col3548] AS datetime) AS [End Hours],
        ecv.[Col2433282] AS [WorkType],
        CAST(ecv.[Col2433283] AS decimal(24,6)) AS [DowntimeHours],
        CAST(ecv.[Col2433284] AS datetime) AS [YearMonth],
        ecv.[Col2433285] AS [Model],
        ecv.[Col2433286] AS [Labour Type],
        ecv.[Col2433463] AS [Description CAT],
        ecv.[Col2434438] AS [Minesite],
        ecv.[Col2434565] AS [Model Lookup],
        ecv.[Col2434566] AS [SerialNumber],
        ecv.[Col2435812] AS [Responsability],
        CAST(ISNULL(ecv.[Col2434438], '') + '' + ISNULL(eq.[EQUIP], '') AS varchar(max)) AS [Keymap]
    FROM [EVENTCHAIN] ec
    LEFT JOIN (
        SELECT 
            EVENTCHAINID,
            MAX(CASE WHEN EVENTCHAINCMTID = 6570 THEN EVENTCHAINCMTVAL END) AS Col1588,
            MAX(CASE WHEN EVENTCHAINCMTID = 6572 THEN EVENTCHAINCMTVAL END) AS Col3547,
            MAX(CASE WHEN EVENTCHAINCMTID = 6573 THEN EVENTCHAINCMTVAL END) AS Col3548,
            MAX(CASE WHEN EVENTCHAINCMTID = 3618 THEN EVENTCHAINCMTVAL END) AS Col2433282,
            MAX(CASE WHEN EVENTCHAINCMTID = 3619 THEN EVENTCHAINCMTVAL END) AS Col2433283,
            MAX(CASE WHEN EVENTCHAINCMTID = 3620 THEN EVENTCHAINCMTVAL END) AS Col2433284,
            MAX(CASE WHEN EVENTCHAINCMTID = 3621 THEN EVENTCHAINCMTVAL END) AS Col2433285,
            MAX(CASE WHEN EVENTCHAINCMTID = 3622 THEN EVENTCHAINCMTVAL END) AS Col2433286,
            MAX(CASE WHEN EVENTCHAINCMTID = 3640 THEN EVENTCHAINCMTVAL END) AS Col2433463,
            MAX(CASE WHEN EVENTCHAINCMTID = 4641 THEN EVENTCHAINCMTVAL END) AS Col2434438,
            MAX(CASE WHEN EVENTCHAINCMTID = 4661 THEN EVENTCHAINCMTVAL END) AS Col2434565,
            MAX(CASE WHEN EVENTCHAINCMTID = 4662 THEN EVENTCHAINCMTVAL END) AS Col2434566,
            MAX(CASE WHEN EVENTCHAINCMTID = 5783 THEN EVENTCHAINCMTVAL END) AS Col2435812
        FROM [EVENTCHAINCMTVAL]
        WHERE EVENTCHAINCMTID IN (6570,6572,6573,3618,3619,3620,3621,3622,3640,4641,4661,4662,5783)
        GROUP BY EVENTCHAINID
    ) ecv ON ec.EVENTCHAINID = ecv.EVENTCHAINID
    LEFT JOIN [EQUIP] eq ON ec.[EQUIPID] = eq.[EQUIPID]
    WHERE EXISTS (
        SELECT 1
        FROM EVENTCHAINTYPE ect
        WHERE ect.EVENTCHAINTYPEID = ec.EVENTCHAINTYPEID
          AND ect.ENABLED <> 0
          AND ect.EVENTCHAINTYPE = 'EQUIP_NEEMBA'
    )
    AND ec.CREATED_DATE >= '2015-01-01'
    /*DATE_FILTER*/
    """
).strip()


BASE_LIVE_SOURCES: tuple[LiveSource, ...] = ()


def _source_dict(source: LiveSource) -> dict:
    return {
        "key": source.key,
        "name": source.name,
        "engine": source.engine,
        "server": source.server,
        "database": source.database,
        "user": source.user,
        "password": source.password,
        "port": source.port,
        "owner": source.owner,
        "status": source.status,
        "status_class": source.status_class,
        "description": source.description,
        "connection_details": source.connection_details,
        "is_active": source.is_active,
        "last_verified": source.last_verified,
        "verification_status": source.verification_status,
        "verification_message": source.verification_message,
        "views": [
            {
                "key": view.key,
                "name": view.name,
                "description": view.description,
                "sql": view.sql,
            }
            for view in source.views
        ],
    }


def _load_source_state() -> dict[str, dict]:
    if not LIVE_SOURCE_STATE_FILE.exists():
        return {}
    try:
        payload = json.loads(LIVE_SOURCE_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {str(key).lower(): value for key, value in payload.items() if isinstance(value, dict)}
    except Exception:
        pass
    return {}


def _load_custom_sources() -> list[dict]:
    db_sources = _load_custom_sources_from_db()
    if db_sources:
        return db_sources
    if not CUSTOM_LIVE_SOURCE_FILE.exists():
        return []
    try:
        payload = json.loads(CUSTOM_LIVE_SOURCE_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _ensure_live_source_tables(connection) -> None:
    cursor = connection.cursor()
    cursor.execute(
        """
        IF OBJECT_ID(N'dbo.LiveSourceConfig', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.LiveSourceConfig (
                SourceKey NVARCHAR(160) NOT NULL CONSTRAINT PK_LiveSourceConfig PRIMARY KEY,
                SourceName NVARCHAR(255) NOT NULL,
                Engine NVARCHAR(80) NOT NULL,
                ServerName NVARCHAR(255) NOT NULL,
                DatabaseName NVARCHAR(255) NULL,
                UserName NVARCHAR(255) NULL,
                PasswordValue NVARCHAR(500) NULL,
                Port INT NULL,
                OwnerName NVARCHAR(255) NULL,
                Status NVARCHAR(80) NULL,
                StatusClass NVARCHAR(80) NULL,
                Description NVARCHAR(MAX) NULL,
                ConnectionDetails NVARCHAR(MAX) NULL,
                IsActive BIT NOT NULL CONSTRAINT DF_LiveSourceConfig_IsActive DEFAULT (1),
                LastVerified NVARCHAR(80) NULL,
                VerificationStatus NVARCHAR(80) NULL,
                VerificationMessage NVARCHAR(MAX) NULL,
                UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_LiveSourceConfig_UpdatedAt DEFAULT SYSUTCDATETIME()
            );
        END
        """
    )
    cursor.execute(
        """
        IF OBJECT_ID(N'dbo.LiveSourceCustomView', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.LiveSourceCustomView (
                SourceKey NVARCHAR(160) NOT NULL,
                ViewKey NVARCHAR(160) NOT NULL,
                ViewName NVARCHAR(255) NOT NULL,
                Description NVARCHAR(MAX) NULL,
                SqlText NVARCHAR(MAX) NOT NULL,
                UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_LiveSourceCustomView_UpdatedAt DEFAULT SYSUTCDATETIME(),
                CONSTRAINT PK_LiveSourceCustomView PRIMARY KEY (SourceKey, ViewKey)
            );
        END
        """
    )


def _load_custom_sources_from_db() -> list[dict]:
    if not SQL_SOURCE_CONFIG_ENABLED:
        return []
    try:
        with connect(database="Mining360") as connection:
            _ensure_live_source_tables(connection)
            cursor = connection.cursor()
            source_rows = cursor.execute(
                """
                SELECT
                    SourceKey, SourceName, Engine, ServerName, DatabaseName,
                    UserName, PasswordValue, Port, OwnerName, Status, StatusClass,
                    Description, ConnectionDetails, IsActive, LastVerified,
                    VerificationStatus, VerificationMessage
                FROM dbo.LiveSourceConfig
                ORDER BY SourceName
                """
            ).fetchall()
            view_rows = cursor.execute(
                """
                SELECT SourceKey, ViewKey, ViewName, Description, SqlText
                FROM dbo.LiveSourceCustomView
                ORDER BY SourceKey, ViewName
                """
            ).fetchall()
    except Exception:
        return []

    def cell(row, index, name):
        return getattr(row, name, row[index])

    views_by_source: dict[str, list[dict]] = {}
    for row in view_rows:
        source_key = cell(row, 0, "SourceKey")
        views_by_source.setdefault(str(source_key).lower(), []).append(
            {
                "key": cell(row, 1, "ViewKey"),
                "name": cell(row, 2, "ViewName"),
                "description": cell(row, 3, "Description") or "",
                "sql": cell(row, 4, "SqlText") or "",
            }
        )

    sources = []
    for row in source_rows:
        try:
            connection_details = json.loads(cell(row, 12, "ConnectionDetails") or "{}")
        except Exception:
            connection_details = {}
        source_key = cell(row, 0, "SourceKey")
        sources.append(
            {
                "key": source_key,
                "name": cell(row, 1, "SourceName"),
                "engine": cell(row, 2, "Engine"),
                "server": cell(row, 3, "ServerName"),
                "database": cell(row, 4, "DatabaseName") or "",
                "user": cell(row, 5, "UserName") or "",
                "password": cell(row, 6, "PasswordValue") or "",
                "port": int(cell(row, 7, "Port") or 0),
                "owner": cell(row, 8, "OwnerName") or "",
                "status": cell(row, 9, "Status") or "Unknown",
                "status_class": cell(row, 10, "StatusClass") or "neutral",
                "description": cell(row, 11, "Description") or "",
                "connection_details": connection_details,
                "is_active": bool(cell(row, 13, "IsActive")),
                "last_verified": cell(row, 14, "LastVerified") or "",
                "verification_status": cell(row, 15, "VerificationStatus") or "Unknown",
                "verification_message": cell(row, 16, "VerificationMessage") or "",
                "views": views_by_source.get(str(source_key).lower(), []),
            }
        )
    return sources


def _save_custom_sources_to_db(sources: list[dict]) -> None:
    if not SQL_SOURCE_CONFIG_ENABLED:
        return
    try:
        with connect(database="Mining360") as connection:
            _ensure_live_source_tables(connection)
            cursor = connection.cursor()
            cursor.execute("DELETE FROM dbo.LiveSourceCustomView; DELETE FROM dbo.LiveSourceConfig;")
            for source in sources:
                cursor.execute(
                    """
                    INSERT INTO dbo.LiveSourceConfig (
                        SourceKey, SourceName, Engine, ServerName, DatabaseName, UserName,
                        PasswordValue, Port, OwnerName, Status, StatusClass, Description,
                        ConnectionDetails, IsActive, LastVerified, VerificationStatus,
                        VerificationMessage
                    )
                    VALUES (
                        %(key)s, %(name)s, %(engine)s, %(server)s, %(database)s, %(user)s,
                        %(password)s, %(port)s, %(owner)s, %(status)s, %(status_class)s,
                        %(description)s, %(connection_details)s, %(is_active)s, %(last_verified)s,
                        %(verification_status)s, %(verification_message)s
                    )
                    """,
                    {
                        "key": str(source.get("key", "")),
                        "name": str(source.get("name", "")),
                        "engine": str(source.get("engine", "")),
                        "server": str(source.get("server", "")),
                        "database": str(source.get("database", "")),
                        "user": str(source.get("user", "")),
                        "password": str(source.get("password", "")),
                        "port": int(source.get("port", 0) or 0),
                        "owner": str(source.get("owner", "")),
                        "status": str(source.get("status", "")),
                        "status_class": str(source.get("status_class", "")),
                        "description": str(source.get("description", "")),
                        "connection_details": json.dumps(source.get("connection_details", {}) or {}, ensure_ascii=False),
                        "is_active": int(bool(source.get("is_active", True))),
                        "last_verified": str(source.get("last_verified", "")),
                        "verification_status": str(source.get("verification_status", "")),
                        "verification_message": str(source.get("verification_message", "")),
                    },
                )
                for view in source.get("views", []) or []:
                    cursor.execute(
                        """
                        INSERT INTO dbo.LiveSourceCustomView (
                            SourceKey, ViewKey, ViewName, Description, SqlText
                        )
                        VALUES (%(source_key)s, %(view_key)s, %(view_name)s, %(description)s, %(sql_text)s)
                        """,
                        {
                            "source_key": str(source.get("key", "")),
                            "view_key": str(view.get("key", "")),
                            "view_name": str(view.get("name", "")),
                            "description": str(view.get("description", "")),
                            "sql_text": str(view.get("sql", "")),
                        },
                    )
    except Exception:
        return


def _save_source_state(sources: list[LiveSource]) -> None:
    payload = {source.key.lower(): _source_dict(source) for source in sources}
    LIVE_SOURCE_STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_custom_sources(sources: list[LiveSource]) -> None:
    payload = [_source_dict(source) for source in sources]
    _save_custom_sources_to_db(payload)
    CUSTOM_LIVE_SOURCE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _source_from_dict(data: dict) -> LiveSource:
    views = tuple(
        LiveView(
            key=str(view.get("key", "")),
            name=str(view.get("name", "")),
            description=str(view.get("description", "")),
            sql=str(view.get("sql", "")),
        )
        for view in data.get("views", [])
        if isinstance(view, dict)
    )
    return LiveSource(
        key=str(data.get("key", "")),
        name=str(data.get("name", "")),
        engine=str(data.get("engine", "SQL Server")),
        server=str(data.get("server", "")),
        database=str(data.get("database", "")),
        user=str(data.get("user", "")),
        password=str(data.get("password", "")),
        port=int(data.get("port", 0) or 0),
        owner=str(data.get("owner", "")),
        status=str(data.get("status", "Unknown")),
        status_class=str(data.get("status_class", "neutral")),
        description=str(data.get("description", "")),
        views=views,
        connection_details={
            str(key): str(value)
            for key, value in dict(data.get("connection_details", {})).items()
        } if isinstance(data.get("connection_details", {}), dict) else {},
        is_active=bool(data.get("is_active", True)),
        last_verified=str(data.get("last_verified", "")),
        verification_status=str(data.get("verification_status", "Unknown")),
        verification_message=str(data.get("verification_message", "")),
    )


def _merge_source(base: LiveSource, override: dict | None) -> LiveSource:
    override = override or {}
    verification_status = str(override.get("verification_status", base.verification_status) or base.verification_status)
    is_active = bool(override.get("is_active", base.is_active))
    if not is_active:
        status = "Inactive"
        status_class = "neutral"
    elif verification_status.lower() == "active":
        status = "Active"
        status_class = "success"
    elif verification_status.lower() == "failed":
        status = "Failed"
        status_class = "failed"
    else:
        status = override.get("status", base.status)
        status_class = override.get("status_class", base.status_class)

    return replace(
        base,
        server=str(override.get("server", base.server)),
        database=str(override.get("database", base.database)),
        user=str(override.get("user", base.user)),
        password=str(override.get("password", base.password)),
        port=int(override.get("port", base.port) or 0),
        owner=str(override.get("owner", base.owner)),
        status=status,
        status_class=status_class,
        description=str(override.get("description", base.description)),
        connection_details=dict(override.get("connection_details", base.connection_details) or base.connection_details),
        is_active=is_active,
        last_verified=str(override.get("last_verified", base.last_verified) or ""),
        verification_status=verification_status,
        verification_message=str(override.get("verification_message", base.verification_message) or ""),
    )


def list_live_sources() -> list[LiveSource]:
    custom_sources = [_source_from_dict(item) for item in _load_custom_sources()]
    sources = [_merge_source(source, None) for source in BASE_LIVE_SOURCES]
    existing_keys = {source.key.lower() for source in sources}
    for source in custom_sources:
        if source.key.lower() not in existing_keys:
            sources.append(source)
    return sorted(sources, key=lambda item: item.name.lower())


def get_live_source(source_key: str) -> LiveSource:
    normalized = source_key.strip().lower()
    for source in list_live_sources():
        if source.key.lower() == normalized:
            return source
    raise KeyError(source_key)


def get_live_view(source_key: str, view_key: str) -> tuple[LiveSource, LiveView]:
    source = get_live_source(source_key)
    normalized = view_key.strip().lower()
    for view in source.views:
        if view.key.lower() == normalized:
            return source, view
    raise KeyError(view_key)


def _unique_view_key(source: LiveSource, name: str) -> str:
    base = slugify(name) or "custom-view"
    base = base.replace("-", "")
    existing = {view.key.lower() for view in source.views}
    candidate = base
    suffix = 2
    while candidate.lower() in existing:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def _coerce_sql_value(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ", timespec="seconds")
        except TypeError:
            return value.isoformat()
    return value


def _date_clause(column_name: str, date_from: str | None, date_to: str | None) -> str:
    clauses = []
    if date_from:
        clauses.append(f"CONVERT(date, {column_name}) >= CONVERT(date, '{date_from}', 23)")
    if date_to:
        clauses.append(f"CONVERT(date, {column_name}) <= CONVERT(date, '{date_to}', 23)")
    return " AND ".join(clauses)


def execute_live_view(
    source_key: str,
    view_key: str,
    limit: int = 500,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    source, view = get_live_view(source_key, view_key)
    limit = max(1, min(int(limit or 500), 5000))
    date_sql = _date_clause("ec.CREATED_DATE", date_from, date_to)
    query_sql = view.sql.replace("/*DATE_FILTER*/", f"AND {date_sql}" if date_sql else "")
    sql = f"SELECT TOP ({limit}) * FROM (\n{query_sql}\n) AS live_view"

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

    records = [
        {column: _coerce_sql_value(value) for column, value in zip(columns, row)}
        for row in rows
    ]
    row_values = [
        [_coerce_sql_value(value) for value in row]
        for row in rows
    ]

    return {
        "source": source,
        "view": view,
        "limit": limit,
        "row_count": len(records),
        "columns": columns,
        "rows": records,
        "row_values": row_values,
        "truncated": len(records) >= limit,
        "date_from": date_from,
        "date_to": date_to,
        "sql": sql,
    }


def save_live_source(source: LiveSource) -> None:
    custom_sources = _load_custom_sources()
    updated_sources = []
    replaced = False
    for item in custom_sources:
        if str(item.get("key", "")).lower() == source.key.lower():
            updated_sources.append(_source_dict(source))
            replaced = True
        else:
            updated_sources.append(item)
    if not replaced:
        updated_sources.append(_source_dict(source))
    CUSTOM_LIVE_SOURCE_FILE.write_text(
        json.dumps(updated_sources, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _save_custom_sources_to_db(updated_sources)


def add_live_view(
    source_key: str,
    *,
    name: str,
    description: str = "",
    sql: str,
) -> LiveView:
    source = get_live_source(source_key)
    view = LiveView(
        key=_unique_view_key(source, name),
        name=name,
        description=description or "",
        sql=sql.strip(),
    )
    updated = replace(source, views=(*source.views, view))
    save_live_source(updated)
    return view


def update_live_view(
    source_key: str,
    view_key: str,
    *,
    name: str,
    description: str = "",
    sql: str,
) -> LiveView:
    source = get_live_source(source_key)
    normalized = view_key.strip().lower()
    replacement_key = ""
    updated_views = []
    for view in source.views:
        if view.key.lower() == normalized:
            replacement_key = view.key
            updated_views.append(
                LiveView(
                    key=view.key,
                    name=name.strip(),
                    description=(description or "").strip(),
                    sql=sql.strip(),
                )
            )
        else:
            updated_views.append(view)
    if not replacement_key:
        raise KeyError(view_key)
    updated = replace(source, views=tuple(updated_views))
    save_live_source(updated)
    return next(view for view in updated.views if view.key == replacement_key)


def delete_live_view(source_key: str, view_key: str) -> bool:
    source = get_live_source(source_key)
    normalized = view_key.strip().lower()
    updated_views = tuple(view for view in source.views if view.key.lower() != normalized)
    if len(updated_views) == len(source.views):
        return False
    save_live_source(replace(source, views=updated_views))
    return True


def delete_live_source(source_key: str) -> bool:
    normalized = source_key.strip().lower()
    custom_sources = _load_custom_sources()
    updated_sources = []
    deleted = False
    for item in custom_sources:
        if str(item.get("key", "")).strip().lower() == normalized:
            deleted = True
            continue
        updated_sources.append(item)

    if deleted:
        CUSTOM_LIVE_SOURCE_FILE.write_text(
            json.dumps(updated_sources, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _save_custom_sources_to_db(updated_sources)

    state = _load_source_state()
    if normalized in state:
        state.pop(normalized, None)
        LIVE_SOURCE_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return deleted


def set_live_source_verification(source_key: str, ok: bool, message: str = "") -> LiveSource:
    source = get_live_source(source_key)
    status = "Active" if ok else "Failed"
    status_class = "success" if ok else "failed"
    updated = replace(
        source,
        status=status,
        status_class=status_class,
        last_verified=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        verification_status=status,
        verification_message=message,
    )
    save_live_source(updated)
    return updated


def update_live_source(
    source_key: str,
    *,
    server: str | None = None,
    database: str | None = None,
    user: str | None = None,
    password: str | None = None,
    port: int | None = None,
    owner: str | None = None,
    description: str | None = None,
    connection_details: dict[str, str] | None = None,
    is_active: bool | None = None,
) -> LiveSource:
    source = get_live_source(source_key)
    updated = replace(
        source,
        server=source.server if server is None else server,
        database=source.database if database is None else database,
        user=source.user if user is None else user,
        password=source.password if password is None else password,
        port=source.port if port is None else port,
        owner=source.owner if owner is None else owner,
        description=source.description if description is None else description,
        connection_details=source.connection_details if connection_details is None else connection_details,
        is_active=source.is_active if is_active is None else is_active,
    )
    save_live_source(updated)
    return updated


def _unique_source_key(name: str) -> str:
    base = slugify(name) or "source"
    base = base.replace("-", "")
    existing = {source.key.lower() for source in list_live_sources()}
    candidate = base
    suffix = 2
    while candidate.lower() in existing:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def add_live_source(
    *,
    name: str,
    engine: str,
    server: str,
    database: str,
    user: str = "",
    password: str = "",
    port: int = 0,
    owner: str = "",
    description: str = "",
    connection_details: dict[str, str] | None = None,
    status: str = "Active",
    status_class: str = "success",
    verification_message: str = "Connection OK",
) -> LiveSource:
    source = LiveSource(
        key=_unique_source_key(name),
        name=name,
        engine=engine,
        server=server,
        database=database,
        user=user,
        password=password,
        port=port,
        owner=owner or "",
        status=status,
        status_class=status_class,
        description=description or "",
        views=(),
        connection_details=connection_details or {},
        is_active=True,
        last_verified=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        verification_status=status,
        verification_message=verification_message,
    )
    save_live_source(source)
    return source
