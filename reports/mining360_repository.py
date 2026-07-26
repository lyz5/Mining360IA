import json
import time
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.apps import apps
from django.db import models

from .live_sources import _load_custom_sources, _load_source_state
from .powerbi import REPORT_DISPLAY_ALIASES
from .resource_library import ResourceFile, list_resources
from .sqlserver import connect


REPORT_ALIAS_TABLE = "dbo.PowerBIReportAlias"
RESOURCE_TABLE = "dbo.ResourceFile"
RESOURCE_CACHE_SECONDS = 120
_RESOURCE_CACHE: dict[tuple[str, str, str, str], tuple[float, list["ResourceFile"]]] = {}
_RESOURCE_FACETS_CACHE: tuple[float, dict] | None = None

CONFIG_MODEL_NAMES = [
    "DataQualityRun",
    "PlatformUser",
    "DataBrowser",
    "DataBrowserColumn",
    "DataBrowserSyncLog",
    "AIConfigSection",
    "AIQuestionExample",
    "AISynonym",
    "AIMetricMapping",
    "AIFilterMapping",
    "AIDaxTemplate",
    "AISemanticTable",
    "AISemanticColumn",
    "AISemanticMeasure",
    "AISemanticRelationship",
    "AIBusinessVocabulary",
    "AIFewShotExample",
    "AIPromptTemplate",
    "AIBusinessRule",
    "AIPowerBIPage",
    "PowerBIReport",
    "PowerBIPage",
    "PowerBIVisual",
    "PowerBISlicer",
    "KPIPageMapping",
    "KPIVisualMapping",
    "IntentNavigationMapping",
    "SupportedPowerBIAction",
    "AIConversationContext",
    "PowerBIInteractionLog",
    "RootCauseDimension",
    "RootCauseTheme",
    "CommentQualityRule",
    "RepeatFailureRule",
    "SMCSCode",
    "SMCSSynonym",
    "SMCSClassificationConfig",
    "DowntimeSMCSClassification",
    "SMCSClassificationJob",
    "DowntimeExplorerSession",
    "DowntimeExplorerInteraction",
    "DowntimeExplorerAIAnalysis",
    "AIVisualMapping",
    "AIKPITarget",
    "AIRecommendedAction",
    "AIDebugRun",
    "KnowledgeBusinessGlossary",
    "KnowledgeKPIDictionary",
    "KnowledgeMiningTerminology",
    "KnowledgeQuestion",
    "KnowledgeSynonym",
    "KnowledgeBusinessRule",
    "KnowledgePrompt",
    "KnowledgeRecommendedAction",
    "KnowledgeAILog",
    "KnowledgeUserFeedback",
    "OpenAIModelPricing",
    "VoiceInputConfiguration",
    "OpenAIBudget",
    "OpenAICreditSnapshot",
    "ResourceKnowledgeDocument",
    "ResourceKnowledgeSection",
    "ResourceKnowledgeChunk",
    "ResourceKnowledgeItem",
    "ResourceKnowledgeConflict",
    "KnowledgeEnrichmentQueue",
    "ResourceKnowledgeConfiguration",
    "ResourceKnowledgeIndexRun",
    "ResourceKnowledgeRetrievalLog",
    "SystemDatabaseConfig",
    "SystemManagedTable",
    "SystemIntegrationConfig",
    "SystemParameter",
    "BusinessPerformanceConfig",
    "BusinessPerformanceMapping",
    "BusinessPerformanceQueryLog",
]


def create_tables(connection) -> None:
    cursor = connection.cursor()
    cursor.execute(
        """
        IF OBJECT_ID(N'dbo.PowerBIReportAlias', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.PowerBIReportAlias (
                ReportName NVARCHAR(255) NOT NULL CONSTRAINT PK_PowerBIReportAlias PRIMARY KEY,
                ReportAlias NVARCHAR(255) NOT NULL,
                IsActive BIT NOT NULL CONSTRAINT DF_PowerBIReportAlias_IsActive DEFAULT (1),
                CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_PowerBIReportAlias_CreatedAt DEFAULT SYSUTCDATETIME(),
                UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_PowerBIReportAlias_UpdatedAt DEFAULT SYSUTCDATETIME()
            );
        END
        """
    )


def _quote_name(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def _qualified_table(table_name: str) -> str:
    if "." in table_name:
        return ".".join(_quote_name(part) for part in table_name.split(".", 1))
    return f"dbo.{_quote_name(table_name)}"


def _field_column_name(field) -> str:
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return field.attname
    return field.column


def _sql_type_for_field(field) -> str:
    if isinstance(field, (models.AutoField, models.BigAutoField)):
        return "INT"
    if isinstance(field, models.UUIDField):
        return "NVARCHAR(36)"
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        if isinstance(field.target_field, models.UUIDField):
            return "NVARCHAR(36)"
        return "INT"
    if isinstance(field, models.BooleanField):
        return "BIT"
    if isinstance(field, models.IntegerField):
        return "INT"
    if isinstance(field, models.DecimalField):
        return f"DECIMAL({field.max_digits or 18},{field.decimal_places or 4})"
    if isinstance(field, models.DateTimeField):
        return "DATETIME2(0)"
    if isinstance(field, models.DateField):
        return "DATE"
    if isinstance(field, models.JSONField):
        return "NVARCHAR(MAX)"
    if isinstance(field, (models.TextField, models.EmailField, models.SlugField)):
        return "NVARCHAR(MAX)" if not getattr(field, "max_length", None) else f"NVARCHAR({field.max_length})"
    if isinstance(field, models.CharField):
        return f"NVARCHAR({field.max_length or 255})"
    return "NVARCHAR(MAX)"


def _json_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _model_fields(model):
    return [
        field
        for field in model._meta.fields
        if not getattr(field, "many_to_many", False)
    ]


def _ensure_model_mirror_table(connection, model) -> None:
    cursor = connection.cursor()
    table_name = model._meta.db_table
    qualified = _qualified_table(table_name)
    columns = []
    for field in _model_fields(model):
        column_name = _field_column_name(field)
        sql_type = _sql_type_for_field(field)
        null_sql = "NOT NULL" if field.primary_key else "NULL"
        primary_sql = " CONSTRAINT " + _quote_name(f"PK_{table_name}") + " PRIMARY KEY" if field.primary_key else ""
        columns.append(f"{_quote_name(column_name)} {sql_type} {null_sql}{primary_sql}")
    cursor.execute(
        f"""
        IF OBJECT_ID(N'{table_name}', N'U') IS NULL
        BEGIN
            CREATE TABLE {qualified} (
                {", ".join(columns)}
            );
        END
        """
    )
    for field in _model_fields(model):
        is_uuid_reference = (
            isinstance(field, (models.ForeignKey, models.OneToOneField))
            and isinstance(field.target_field, models.UUIDField)
        )
        if not is_uuid_reference:
            continue
        column_name = _field_column_name(field)
        null_sql = "NOT NULL" if field.primary_key else "NULL"
        cursor.execute(
            f"IF COL_LENGTH(N'{table_name}', N'{column_name}') IS NOT NULL "
            f"ALTER TABLE {qualified} ALTER COLUMN "
            f"{_quote_name(column_name)} NVARCHAR(36) {null_sql}"
        )
    for field in _model_fields(model):
        if field.primary_key:
            continue
        column_name = _field_column_name(field)
        cursor.execute(
            f"""
            IF COL_LENGTH(N'{table_name}', N'{column_name}') IS NULL
            BEGIN
                ALTER TABLE {qualified}
                ADD {_quote_name(column_name)} {_sql_type_for_field(field)} NULL;
            END
            """
        )


def _sync_model_mirror(connection, model) -> int:
    _ensure_model_mirror_table(connection, model)
    cursor = connection.cursor()
    fields = _model_fields(model)
    rows = []
    for obj in model.objects.all().iterator():
        rows.append(
            {
                _field_column_name(field): _json_value(getattr(obj, field.attname))
                for field in fields
            }
        )
    table_name = model._meta.db_table
    qualified = _qualified_table(table_name)
    cursor.execute(f"DELETE FROM {qualified};")
    if not rows:
        return 0
    columns = [_field_column_name(field) for field in fields]
    with_clause = ", ".join(
        f"{_quote_name(column)} {_sql_type_for_field(field)} '$.{column}'"
        for column, field in zip(columns, fields)
    )
    insert_columns = ", ".join(_quote_name(column) for column in columns)
    select_columns = ", ".join(_quote_name(column) for column in columns)
    cursor.execute(
        f"""
        INSERT INTO {qualified} ({insert_columns})
        SELECT {select_columns}
        FROM OPENJSON(%(payload)s)
        WITH ({with_clause});
        """,
        {"payload": json.dumps(rows, ensure_ascii=False)},
    )
    return len(rows)


def sync_django_config_tables(connection) -> dict[str, int]:
    counts = {}
    for model_name in CONFIG_MODEL_NAMES:
        model = apps.get_model("reports", model_name)
        counts[model._meta.db_table] = _sync_model_mirror(connection, model)
    return counts


def is_config_model(model) -> bool:
    return model.__name__ in CONFIG_MODEL_NAMES


def sync_config_model(model) -> int:
    with connect() as connection:
        return _sync_model_mirror(connection, model)


def restore_config_model_from_sqlserver(model) -> int:
    fields = _model_fields(model)
    table_name = model._meta.db_table
    columns = [_field_column_name(field) for field in fields]
    select_columns = ", ".join(_quote_name(column) for column in columns)
    rows = []
    with connect(database="Mining360") as connection:
        _ensure_model_mirror_table(connection, model)
        cursor = connection.cursor()
        rows = cursor.execute(f"SELECT {select_columns} FROM {_qualified_table(table_name)}").fetchall()

    model.objects.all().delete()
    created = 0
    for row in rows:
        values = {}
        for field, column, value in zip(fields, columns, row):
            if isinstance(field, models.JSONField) and isinstance(value, str):
                try:
                    value = json.loads(value) if value else {}
                except Exception:
                    value = {}
            values[field.attname] = value
        model.objects.create(**values)
        created += 1
    return created


def restore_django_config_tables_from_sqlserver() -> dict[str, int]:
    counts = {}
    for model_name in CONFIG_MODEL_NAMES:
        model = apps.get_model("reports", model_name)
        counts[model._meta.db_table] = restore_config_model_from_sqlserver(model)
    return counts


def create_live_source_tables(connection) -> None:
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


def sync_live_source_config(connection) -> dict[str, int]:
    create_live_source_tables(connection)
    state = _load_source_state()
    sources = _load_custom_sources()
    source_rows = []
    view_rows = []
    for source in sources:
        key = str(source.get("key", "")).strip()
        if not key:
            continue
        merged = {**source, **state.get(key.lower(), {})}
        source_rows.append(
            {
                "SourceKey": key,
                "SourceName": str(merged.get("name", "")),
                "Engine": str(merged.get("engine", "")),
                "ServerName": str(merged.get("server", "")),
                "DatabaseName": str(merged.get("database", "")),
                "UserName": str(merged.get("user", "")),
                "PasswordValue": str(merged.get("password", "")),
                "Port": int(merged.get("port", 0) or 0),
                "OwnerName": str(merged.get("owner", "")),
                "Status": str(merged.get("status", "")),
                "StatusClass": str(merged.get("status_class", "")),
                "Description": str(merged.get("description", "")),
                "ConnectionDetails": json.dumps(merged.get("connection_details", {}) or {}, ensure_ascii=False),
                "IsActive": int(bool(merged.get("is_active", True))),
                "LastVerified": str(merged.get("last_verified", "")),
                "VerificationStatus": str(merged.get("verification_status", "")),
                "VerificationMessage": str(merged.get("verification_message", "")),
            }
        )
        for view in source.get("views", []) or []:
            if not isinstance(view, dict):
                continue
            view_rows.append(
                {
                    "SourceKey": key,
                    "ViewKey": str(view.get("key", "")),
                    "ViewName": str(view.get("name", "")),
                    "Description": str(view.get("description", "")),
                    "SqlText": str(view.get("sql", "")),
                }
            )
    cursor = connection.cursor()
    cursor.execute("DELETE FROM dbo.LiveSourceCustomView; DELETE FROM dbo.LiveSourceConfig;")
    if source_rows:
        cursor.execute(
            """
            INSERT INTO dbo.LiveSourceConfig (
                SourceKey, SourceName, Engine, ServerName, DatabaseName, UserName,
                PasswordValue, Port, OwnerName, Status, StatusClass, Description,
                ConnectionDetails, IsActive, LastVerified, VerificationStatus,
                VerificationMessage
            )
            SELECT
                SourceKey, SourceName, Engine, ServerName, DatabaseName, UserName,
                PasswordValue, Port, OwnerName, Status, StatusClass, Description,
                ConnectionDetails, IsActive, LastVerified, VerificationStatus,
                VerificationMessage
            FROM OPENJSON(%(payload)s)
            WITH (
                SourceKey NVARCHAR(160) '$.SourceKey',
                SourceName NVARCHAR(255) '$.SourceName',
                Engine NVARCHAR(80) '$.Engine',
                ServerName NVARCHAR(255) '$.ServerName',
                DatabaseName NVARCHAR(255) '$.DatabaseName',
                UserName NVARCHAR(255) '$.UserName',
                PasswordValue NVARCHAR(500) '$.PasswordValue',
                Port INT '$.Port',
                OwnerName NVARCHAR(255) '$.OwnerName',
                Status NVARCHAR(80) '$.Status',
                StatusClass NVARCHAR(80) '$.StatusClass',
                Description NVARCHAR(MAX) '$.Description',
                ConnectionDetails NVARCHAR(MAX) '$.ConnectionDetails',
                IsActive BIT '$.IsActive',
                LastVerified NVARCHAR(80) '$.LastVerified',
                VerificationStatus NVARCHAR(80) '$.VerificationStatus',
                VerificationMessage NVARCHAR(MAX) '$.VerificationMessage'
            );
            """,
            {"payload": json.dumps(source_rows, ensure_ascii=False)},
        )
    if view_rows:
        cursor.execute(
            """
            INSERT INTO dbo.LiveSourceCustomView (
                SourceKey, ViewKey, ViewName, Description, SqlText
            )
            SELECT SourceKey, ViewKey, ViewName, Description, SqlText
            FROM OPENJSON(%(payload)s)
            WITH (
                SourceKey NVARCHAR(160) '$.SourceKey',
                ViewKey NVARCHAR(160) '$.ViewKey',
                ViewName NVARCHAR(255) '$.ViewName',
                Description NVARCHAR(MAX) '$.Description',
                SqlText NVARCHAR(MAX) '$.SqlText'
            );
            """,
            {"payload": json.dumps(view_rows, ensure_ascii=False)},
        )
    return {"sources": len(source_rows), "custom_views": len(view_rows)}
    cursor.execute(
        """
        IF OBJECT_ID(N'dbo.ResourceFile', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.ResourceFile (
                ResourceId NVARCHAR(512) NOT NULL CONSTRAINT PK_ResourceFile PRIMARY KEY,
                Title NVARCHAR(500) NOT NULL,
                FileName NVARCHAR(500) NOT NULL,
                Extension NVARCHAR(20) NOT NULL,
                Section NVARCHAR(255) NOT NULL,
                Category NVARCHAR(255) NOT NULL,
                PracticeLevel NVARCHAR(100) NOT NULL,
                FolderPath NVARCHAR(1000) NOT NULL,
                RelativePath NVARCHAR(1000) NOT NULL,
                SizeBytes BIGINT NOT NULL,
                MimeType NVARCHAR(255) NOT NULL,
                IsPdf BIT NOT NULL,
                IsText BIT NOT NULL,
                IsActive BIT NOT NULL CONSTRAINT DF_ResourceFile_IsActive DEFAULT (1),
                CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_ResourceFile_CreatedAt DEFAULT SYSUTCDATETIME(),
                UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_ResourceFile_UpdatedAt DEFAULT SYSUTCDATETIME()
            );

            CREATE INDEX IX_ResourceFile_Section ON dbo.ResourceFile (Section);
            CREATE INDEX IX_ResourceFile_Category ON dbo.ResourceFile (Category);
            CREATE INDEX IX_ResourceFile_PracticeLevel ON dbo.ResourceFile (PracticeLevel);
        END
        """
    )


def sync_report_aliases(connection) -> int:
    cursor = connection.cursor()
    rows = [
        {"ReportName": name, "ReportAlias": alias}
        for name, alias in REPORT_DISPLAY_ALIASES.items()
    ]
    cursor.execute(
        """
        MERGE dbo.PowerBIReportAlias AS target
        USING (
            SELECT ReportName, ReportAlias
            FROM OPENJSON(%(payload)s)
            WITH (
                ReportName NVARCHAR(255) '$.ReportName',
                ReportAlias NVARCHAR(255) '$.ReportAlias'
            )
        ) AS source
            ON target.ReportName = source.ReportName
        WHEN MATCHED THEN
            UPDATE SET
                ReportAlias = source.ReportAlias,
                IsActive = 1,
                UpdatedAt = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (ReportName, ReportAlias)
            VALUES (source.ReportName, source.ReportAlias);
        """,
        {"payload": json.dumps(rows, ensure_ascii=False)},
    )
    return len(rows)


def sync_resources(connection, resources: list[ResourceFile] | None = None) -> int:
    cursor = connection.cursor()
    resources = resources or list_resources()
    now = datetime.utcnow()
    rows = [
        {
            "ResourceId": resource.id,
            "Title": resource.title,
            "FileName": resource.filename,
            "Extension": resource.extension,
            "Section": resource.section,
            "Category": resource.category,
            "PracticeLevel": resource.level,
            "FolderPath": resource.folder_path,
            "RelativePath": resource.relative_path,
            "SizeBytes": resource.size,
            "MimeType": resource.mime_type,
            "IsPdf": int(resource.is_pdf),
            "IsText": int(resource.is_text),
            "UpdatedAt": now.isoformat(timespec="seconds"),
        }
        for resource in resources
    ]
    payload = json.dumps(rows, ensure_ascii=False)
    cursor.execute(
        """
        DELETE FROM dbo.ResourceFile;

        INSERT INTO dbo.ResourceFile (
            ResourceId,
            Title,
            FileName,
            Extension,
            Section,
            Category,
            PracticeLevel,
            FolderPath,
            RelativePath,
            SizeBytes,
            MimeType,
            IsPdf,
            IsText,
            UpdatedAt
        )
        SELECT
            ResourceId,
            Title,
            FileName,
            Extension,
            Section,
            Category,
            PracticeLevel,
            FolderPath,
            RelativePath,
            SizeBytes,
            MimeType,
            IsPdf,
            IsText,
            CONVERT(DATETIME2(0), UpdatedAt, 126)
        FROM OPENJSON(%(payload)s)
        WITH (
            ResourceId NVARCHAR(512) '$.ResourceId',
            Title NVARCHAR(500) '$.Title',
            FileName NVARCHAR(500) '$.FileName',
            Extension NVARCHAR(20) '$.Extension',
            Section NVARCHAR(255) '$.Section',
            Category NVARCHAR(255) '$.Category',
            PracticeLevel NVARCHAR(100) '$.PracticeLevel',
            FolderPath NVARCHAR(1000) '$.FolderPath',
            RelativePath NVARCHAR(1000) '$.RelativePath',
            SizeBytes BIGINT '$.SizeBytes',
            MimeType NVARCHAR(255) '$.MimeType',
            IsPdf BIT '$.IsPdf',
            IsText BIT '$.IsText',
            UpdatedAt NVARCHAR(30) '$.UpdatedAt'
        );
        """,
        {"payload": payload},
    )
    return len(rows)


def sync_mining360_tables() -> dict:
    global _RESOURCE_CACHE, _RESOURCE_FACETS_CACHE
    with connect() as connection:
        create_tables(connection)
        alias_count = sync_report_aliases(connection)
        resource_count = sync_resources(connection)
        config_counts = sync_django_config_tables(connection)
        live_source_counts = sync_live_source_config(connection)
    _RESOURCE_CACHE = {}
    _RESOURCE_FACETS_CACHE = None
    return {
        "aliases": alias_count,
        "resources": resource_count,
        "config_tables": config_counts,
        "live_sources": live_source_counts,
    }


def fetch_report_aliases() -> dict[str, str]:
    with connect() as connection:
        cursor = connection.cursor()
        rows = cursor.execute(
            "SELECT ReportName, ReportAlias FROM dbo.PowerBIReportAlias WHERE IsActive = 1"
        ).fetchall()
    return {row.ReportName: row.ReportAlias for row in rows}


def resource_from_row(row) -> ResourceFile:
    return ResourceFile(
        id=row.ResourceId,
        title=row.Title,
        filename=row.FileName,
        extension=row.Extension,
        section=row.Section,
        category=row.Category,
        level=row.PracticeLevel,
        folder_path=row.FolderPath,
        relative_path=row.RelativePath,
        size=row.SizeBytes,
        size_label=_format_size(row.SizeBytes),
        mime_type=row.MimeType,
        view_url=f"/resources/{row.ResourceId}/",
        raw_url=f"/resources/files/{row.ResourceId}/",
        is_pdf=bool(row.IsPdf),
        is_text=bool(row.IsText),
    )


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def list_resources_from_db(
    query: str = "",
    section: str = "",
    category: str = "",
    level: str = "",
) -> list[ResourceFile]:
    global _RESOURCE_CACHE
    cache_key = (query.strip().lower(), section, category, level)
    now = time.monotonic()
    cached = _RESOURCE_CACHE.get(cache_key)
    if cached and now - cached[0] < RESOURCE_CACHE_SECONDS:
        return list(cached[1])

    where = ["IsActive = 1"]
    params = {}
    if section:
        where.append("Section = %(section)s")
        params["section"] = section
    if category:
        where.append("Category = %(category)s")
        params["category"] = category
    if level:
        where.append("PracticeLevel = %(level)s")
        params["level"] = level
    if query:
        like = f"%{query}%"
        where.append(
            "(Title LIKE %(query)s OR FileName LIKE %(query)s OR Section LIKE %(query)s OR Category LIKE %(query)s OR PracticeLevel LIKE %(query)s OR FolderPath LIKE %(query)s)"
        )
        params["query"] = like

    sql = f"""
        SELECT
            ResourceId,
            Title,
            FileName,
            Extension,
            Section,
            Category,
            PracticeLevel,
            FolderPath,
            RelativePath,
            SizeBytes,
            MimeType,
            IsPdf,
            IsText
        FROM dbo.ResourceFile
        WHERE {" AND ".join(where)}
        ORDER BY Section, Category, PracticeLevel, Title
    """
    with connect() as connection:
        rows = connection.cursor().execute(sql, params).fetchall()
    resources = [resource_from_row(row) for row in rows]
    _RESOURCE_CACHE[cache_key] = (now, resources)
    return list(resources)


def list_resource_facets_from_db() -> dict:
    global _RESOURCE_FACETS_CACHE
    now = time.monotonic()
    if _RESOURCE_FACETS_CACHE and now - _RESOURCE_FACETS_CACHE[0] < RESOURCE_CACHE_SECONDS:
        return dict(_RESOURCE_FACETS_CACHE[1])

    with connect() as connection:
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            SELECT
                ResourceId,
                Title,
                FileName,
                Extension,
                Section,
                Category,
                PracticeLevel,
                FolderPath,
                RelativePath,
                SizeBytes,
                MimeType,
                IsPdf,
                IsText
            FROM dbo.ResourceFile
            WHERE IsActive = 1
            ORDER BY Section, Category, PracticeLevel, Title
            """
        ).fetchall()
    resources = [resource_from_row(row) for row in rows]
    sections = sorted({item.section for item in resources})
    categories = sorted({item.category for item in resources})
    levels = sorted({item.level for item in resources})
    section_cards = [
        {"name": section, "count": count}
        for section, count in sorted(Counter(item.section for item in resources).items())
    ]
    facets = {
        "sections": sections,
        "categories": categories,
        "levels": levels,
        "section_cards": section_cards,
    }
    _RESOURCE_FACETS_CACHE = (now, facets)
    return dict(facets)


def list_resources_bundle_from_db(
    query: str = "",
    section: str = "",
    category: str = "",
    level: str = "",
) -> tuple[list[ResourceFile], dict]:
    global _RESOURCE_CACHE, _RESOURCE_FACETS_CACHE
    cache_key = (query.strip().lower(), section, category, level)
    now = time.monotonic()
    cached_resources = _RESOURCE_CACHE.get(cache_key)
    cached_facets = _RESOURCE_FACETS_CACHE
    if (
        cached_resources
        and now - cached_resources[0] < RESOURCE_CACHE_SECONDS
        and cached_facets
        and now - cached_facets[0] < RESOURCE_CACHE_SECONDS
    ):
        return list(cached_resources[1]), dict(cached_facets[1])

    where = ["IsActive = 1"]
    params = {}
    if section:
        where.append("Section = %(section)s")
        params["section"] = section
    if category:
        where.append("Category = %(category)s")
        params["category"] = category
    if level:
        where.append("PracticeLevel = %(level)s")
        params["level"] = level
    if query:
        like = f"%{query}%"
        where.append(
            "(Title LIKE %(query)s OR FileName LIKE %(query)s OR Section LIKE %(query)s OR Category LIKE %(query)s OR PracticeLevel LIKE %(query)s OR FolderPath LIKE %(query)s)"
        )
        params["query"] = like

    resource_sql = f"""
        SELECT
            ResourceId,
            Title,
            FileName,
            Extension,
            Section,
            Category,
            PracticeLevel,
            FolderPath,
            RelativePath,
            SizeBytes,
            MimeType,
            IsPdf,
            IsText
        FROM dbo.ResourceFile
        WHERE {" AND ".join(where)}
        ORDER BY Section, Category, PracticeLevel, Title
    """
    with connect() as connection:
        cursor = connection.cursor()
        resource_rows = cursor.execute(resource_sql, params).fetchall()
        resources = [resource_from_row(row) for row in resource_rows]
    sections = sorted({item.section for item in resources})
    categories = sorted({item.category for item in resources})
    levels = sorted({item.level for item in resources})
    section_cards = [
        {"name": section, "count": count}
        for section, count in sorted(Counter(item.section for item in resources).items())
    ]
    facets = {
        "sections": sections,
        "categories": categories,
        "levels": levels,
        "section_cards": section_cards,
    }
    _RESOURCE_CACHE[cache_key] = (now, resources)
    _RESOURCE_FACETS_CACHE = (now, facets)
    return list(resources), dict(facets)
