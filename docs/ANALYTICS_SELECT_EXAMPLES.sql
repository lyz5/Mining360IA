-- Run in SQL Server Management Studio on BODEFM, using your existing authorized
-- SQL identity. No login, password or permission grant is included in this file.
USE [Mining360App];
GO

-- 1. Find the current default Mining/YTD snapshot for the intended user.
-- A snapshot is scoped to one user and one filter combination. Never add totals
-- across users, snapshots or overlapping dimensions.
SELECT SnapshotId, UserName, Kind, DivisionScope, PeriodCode,
       PeriodStart, PeriodEnd, DataThroughDate, GeneratedAt, MappingVersion,
       ParametersJson
FROM analytics.CurrentSnapshots
WHERE Kind = 'business' AND ParametersJson = N'{}'
ORDER BY GeneratedAt DESC;

-- 2. Copy ONE SnapshotId from the result above before running the following block.
DECLARE @SnapshotId varchar(36) = 'REPLACE-WITH-SNAPSHOT-ID';

SELECT BusinessLine, RevenueEUR, PreviousRevenueEUR
FROM analytics.RevenueSummary
WHERE SnapshotId = @SnapshotId
ORDER BY BusinessLine;

-- 3. Parts Revenue by customer, for precisely this snapshot's period and scope.
SELECT e.EntityName AS Customer, e.Country, e.KeyAccount,
       l.RevenueEUR AS PartsRevenueEUR, l.PreviousRevenueEUR AS PreviousPartsRevenueEUR
FROM analytics.RevenueEntity e
JOIN analytics.RevenueEntityLine l
  ON l.SnapshotId = e.SnapshotId AND l.Dimension = e.Dimension AND l.EntityId = e.EntityId
WHERE e.SnapshotId = @SnapshotId
  AND e.Dimension = 'customers' AND l.BusinessLine = 'parts'
-- AND e.EntityName LIKE N'%FEKOLA%'
ORDER BY l.RevenueEUR DESC;

-- 4. Reconciliation: zero difference between the total and business line sum.
SELECT
 SUM(CASE WHEN BusinessLine = 'total' THEN RevenueEUR ELSE 0 END) AS DashboardTotalEUR,
 SUM(CASE WHEN BusinessLine <> 'total' THEN RevenueEUR ELSE 0 END) AS BusinessLinesTotalEUR,
 SUM(CASE WHEN BusinessLine = 'total' THEN RevenueEUR ELSE -RevenueEUR END) AS DifferenceEUR
FROM analytics.RevenueSummary WHERE SnapshotId = @SnapshotId;

-- 5. Daily trend. Do not add daily/monthly/comparison series together.
SELECT BusinessDate, RevenueEUR
FROM analytics.RevenueTrend
WHERE SnapshotId = @SnapshotId AND Series = 'daily_trend'
ORDER BY BusinessDate;

-- 6. Official Excellence KPIs; ratios are copied from the governed measure,
-- not recomputed as an average of equipment rows. Inspect Unit before displaying.
SELECT s.SnapshotId, s.UserName, s.PeriodStart, s.PeriodEnd, s.DataThroughDate,
       s.GeneratedAt, s.ParametersJson, m.MetricCode, m.Unit, m.Value
FROM analytics.CurrentSnapshots s
JOIN analytics.ExcellenceMetric m ON m.SnapshotId = s.SnapshotId
WHERE s.Kind = 'excellence' AND m.Section = 'official'
ORDER BY s.UserName, m.MetricCode;

-- 7. Materialized equipment/site rows. A paginated dashboard snapshot includes
-- its requested page only; do not treat it as a complete fleet inventory.
-- Copy an Excellence SnapshotId from query 6, not the Revenue SnapshotId.
DECLARE @ExcellenceSnapshotId varchar(36) = 'REPLACE-WITH-EXCELLENCE-SNAPSHOT-ID';
SELECT Section, Entity, Model, MineSite, MetricCode, Unit, MetricValue,
       EquipmentCount, DowntimeHours
FROM analytics.ExcellenceDetail
WHERE SnapshotId = @ExcellenceSnapshotId
ORDER BY Section, RowNumber;

-- 8. Daily producer execution record and backup verification record.
SELECT StateKey, StateJson FROM analytics.DashboardScheduleState;
