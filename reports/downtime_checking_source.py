"""Bounded, read-only extraction of the inspected browser-84 facts for YTD."""
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from hashlib import sha256
import re

from django.conf import settings
from .external_data_browsers import external_browser_connection, _parameter_marker

VIEW = "META_FORM_VIEW_SCHEMA.v_metaform84"
ATTRIBUTES = {"yearmonth": ("2433284", 3620), "minesite": ("2434438", 4641),
              "serial_number": ("2434566", 4662), "model": ("2433285", 3621),
              "labour_type": ("2433286", 3622), "description_cat": ("2433463", 3640),
              "work_type": ("2433282", 3618), "comment": ("1588", 6570),
              "downtime_hours": ("2433283", 3619), "start_hours": ("3547", 6572),
              "end_hours": ("3548", 6573)}


class SourceCheckError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_browser(browser):
    if browser is None:
        raise SourceCheckError("source_not_configured")
    connection = browser.source_connection
    if (not browser.is_active or browser.source_mode != "miningprod_metaform" or browser.source_view_name != VIEW
            or not connection or not connection.is_active or connection.integration_type != "Database"
            or str(connection.settings_json.get("database", "")).casefold() != "miningprod"):
        raise SourceCheckError("source_not_configured")


def verify_definition(definition):
    text = re.sub(r"\s+", " ", str(definition or "")).casefold()
    for _, (column, attribute) in ATTRIBUTES.items():
        if not re.search(r"eventchaincmtid\]\s*=\s*" + str(attribute) + r"\).*?as\s+\[col" + column + r"\]", text):
            raise SourceCheckError("source_schema_changed")
    restrictions = ("ect.eventchaintype = 'equip_neemba'", "ect.enabled <> 0", "ec.created_date >= '2015-01-01'")
    if not all(item in text for item in restrictions):
        raise SourceCheckError("source_schema_changed")
    # Confirm that the outer browser traversal remains the inspected, enabled
    # EQUIP_NEEMBA population. SQL Server's view formatter varies the number of
    # closing parentheses, so this intentionally checks the semantic root rather
    # than an exact whitespace/parenthesis rendering.
    root = text.rsplit("where ([traversal316].[eventchainid] in (", 1)
    expected_root = ("select eventchainid from eventchaintype ect join eventchain ec on "
                     "ec.eventchaintypeid = ect.eventchaintypeid where ect.enabled <> 0 "
                     "and ect.eventchaintype = 'equip_neemba' and ec.created_date >= '2015-01-01'")
    if len(root) != 2 or expected_root not in root[1]:
        raise SourceCheckError("source_schema_changed")


def sql_queries(marker):
    keys = f"""WITH month_values AS (
        SELECT EVENTCHAINID, MAX(EVENTCHAINCMTVAL) AS ym
        FROM dbo.EVENTCHAINCMTVAL WHERE EVENTCHAINCMTID=3620 GROUP BY EVENTCHAINID
    ), selected AS (
        SELECT ec.EVENTCHAINID FROM dbo.EVENTCHAIN ec
        JOIN dbo.EVENTCHAINTYPE ect ON ect.EVENTCHAINTYPEID=ec.EVENTCHAINTYPEID
        JOIN month_values ym ON ym.EVENTCHAINID=ec.EVENTCHAINID
        WHERE ect.ENABLED<>0 AND ect.EVENTCHAINTYPE='EQUIP_NEEMBA' AND ec.CREATED_DATE>='2015-01-01'
          AND CAST(ym.ym AS datetime)>={marker} AND CAST(ym.ym AS datetime)<{marker}
    )"""
    pivots = ", ".join(f"MAX(CASE WHEN c.EVENTCHAINCMTID={attribute} THEN c.EVENTCHAINCMTVAL END) AS [{alias}]"
                       for alias, (_, attribute) in ATTRIBUTES.items())
    fields = ", ".join("f.[" + name + "]" for name in ATTRIBUTES)
    # YearMonth is deliberately converted as in the inspected source view.  The
    # other values remain source values so quality rules can identify blanks and
    # invalid values rather than hiding them with a conversion failure.
    fields = ", ".join(
        "CAST(f.[yearmonth] AS datetime) AS [yearmonth]" if name == "yearmonth" else "f.[" + name + "]"
        for name in ATTRIBUTES
    )
    query = (keys + ", facts AS (SELECT c.EVENTCHAINID, " + pivots
             + " FROM dbo.EVENTCHAINCMTVAL c JOIN selected s ON s.EVENTCHAINID=c.EVENTCHAINID"
             + " WHERE c.EVENTCHAINCMTID IN (" + ",".join(str(a) for _, a in ATTRIBUTES.values())
             + ") GROUP BY c.EVENTCHAINID) SELECT s.EVENTCHAINID AS event_id, " + fields
             + " FROM selected s LEFT JOIN facts f ON f.EVENTCHAINID=s.EVENTCHAINID ORDER BY s.EVENTCHAINID OPTION(MAXDOP 1)")
    return keys + " SELECT COUNT_BIG(1) FROM selected OPTION(MAXDOP 1)", query


@contextmanager
def scan_ytd(browser, start, end):
    validate_browser(browser)
    if start.year != end.year or start.month != 1 or start.day != 1 or end < start:
        raise SourceCheckError("invalid_period")
    limit = max(1, int(getattr(settings, "DOWNTIME_CHECKING_MAX_ROWS", 300_000)))
    with external_browser_connection(browser) as connection:
        marker = _parameter_marker(connection)
        cursor = connection.cursor()
        try:
            cursor.execute("SET LOCK_TIMEOUT 5000; SET DEADLOCK_PRIORITY LOW;")
            cursor.execute("SELECT DB_NAME()")
            if str(cursor.fetchone()[0]).casefold() != "miningprod":
                raise SourceCheckError("source_not_configured")
            cursor.execute("SELECT OBJECT_DEFINITION(OBJECT_ID(" + marker + "))", (VIEW,))
            definition = cursor.fetchone()[0]
            verify_definition(definition)
            params = (datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min))
            count_sql, row_sql = sql_queries(marker)
            cursor.execute(count_sql, params)
            expected = int(cursor.fetchone()[0])
            if expected > limit:
                raise SourceCheckError("row_limit")
            cursor.execute(row_sql, params)

            def rows():
                names = ["event_id", *ATTRIBUTES]
                while True:
                    values = cursor.fetchmany(500)
                    if not values:
                        return
                    for row in values:
                        yield dict(zip(names, row))

            yield {"expected": expected, "signature": sha256(definition.encode()).hexdigest()}, rows()
        finally:
            cursor.close()
            connection.rollback()
