from django.core.management.base import BaseCommand

from reports.sqlserver import connect


class Command(BaseCommand):
    help = "Compute Fekola 777 availability from BODEFM downtimes for a selected month."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--month", type=int, default=5)

    def handle(self, *args, **options):
        year = options["year"]
        month = options["month"]
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1
        start_date = f"{year:04d}-{month:02d}-01"
        end_date = f"{next_year:04d}-{next_month:02d}-01"

        query = """
WITH Downtimes AS (
    SELECT
        ec.[EVENTCHAINID],
        ec.[EQUIPID] AS [EquipId],
        eq.[EQUIP] AS [Equipment],
        TRY_CAST(ecv.[Col2433283] AS decimal(24,6)) AS [DowntimeHours],
        CAST(ecv.[Col2433284] AS datetime) AS [YearMonth],
        ecv.[Col2433285] AS [Model],
        ecv.[Col2434438] AS [Minesite],
        ecv.[Col2434565] AS [ModelLookup]
    FROM [EVENTCHAIN] ec
    LEFT JOIN (
        SELECT
            EVENTCHAINID,
            MAX(CASE WHEN EVENTCHAINCMTID = 3619 THEN EVENTCHAINCMTVAL END) AS Col2433283,
            MAX(CASE WHEN EVENTCHAINCMTID = 3620 THEN EVENTCHAINCMTVAL END) AS Col2433284,
            MAX(CASE WHEN EVENTCHAINCMTID = 3621 THEN EVENTCHAINCMTVAL END) AS Col2433285,
            MAX(CASE WHEN EVENTCHAINCMTID = 4641 THEN EVENTCHAINCMTVAL END) AS Col2434438,
            MAX(CASE WHEN EVENTCHAINCMTID = 4661 THEN EVENTCHAINCMTVAL END) AS Col2434565
        FROM [EVENTCHAINCMTVAL]
        WHERE EVENTCHAINCMTID IN (3619,3620,3621,4641,4661)
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
      AND CAST(ecv.[Col2433284] AS datetime) >= %s
      AND CAST(ecv.[Col2433284] AS datetime) < %s
      AND (ecv.[Col2433285] LIKE '%%777%%' OR ecv.[Col2434565] LIKE '%%777%%')
      AND ecv.[Col2434438] LIKE '%%Fekola%%'
)
SELECT
    COUNT(*) AS EventCount,
    COUNT(DISTINCT EquipId) AS DistinctEquipId,
    COUNT(DISTINCT COALESCE(NULLIF(Equipment,''), CAST(EquipId AS varchar(50)))) AS DistinctEquipment,
    SUM(COALESCE(DowntimeHours,0)) AS DowntimeHours,
    COUNT(DISTINCT COALESCE(NULLIF(Equipment,''), CAST(EquipId AS varchar(50)))) * DATEDIFF(hour, %s, %s) AS CalendarHours,
    CASE
        WHEN COUNT(DISTINCT COALESCE(NULLIF(Equipment,''), CAST(EquipId AS varchar(50)))) = 0 THEN NULL
        ELSE
            (1.0 - (
                SUM(COALESCE(DowntimeHours,0))
                / NULLIF(COUNT(DISTINCT COALESCE(NULLIF(Equipment,''), CAST(EquipId AS varchar(50)))) * DATEDIFF(hour, %s, %s), 0)
            )) * 100.0
    END AS AvailabilityPct
FROM Downtimes;
"""
        with connect() as connection:
            cursor = connection.cursor()
            cursor.execute(query, (start_date, end_date, start_date, end_date, start_date, end_date))
            row = cursor.fetchone()
            columns = [column[0] for column in cursor.description]
        result = dict(zip(columns, row))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
