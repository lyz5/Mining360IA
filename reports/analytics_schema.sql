CREATE TABLE analytics.AnalyticsSchemaVersion (Version int NOT NULL PRIMARY KEY);
INSERT INTO analytics.AnalyticsSchemaVersion VALUES (1);
CREATE TABLE analytics.DashboardSnapshot (
 SnapshotId varchar(36) NOT NULL PRIMARY KEY,
 RequestKey char(64) NOT NULL, CacheKey char(64) NOT NULL,
 Kind varchar(32) NOT NULL, UserId int NOT NULL, UserName nvarchar(150) NOT NULL,
 GeneratedAt datetime2(6) NOT NULL, ParametersJson nvarchar(max) NOT NULL,
 PayloadJson nvarchar(max) NOT NULL, PayloadSha256 char(64) NOT NULL,
 DivisionScope varchar(32) NULL, PeriodCode varchar(32) NULL,
 PeriodStart date NULL, PeriodEnd date NULL, DataThroughDate date NULL,
 MappingVersion int NULL, SourceRunId varchar(64) NULL,
 CONSTRAINT CK_AnalyticsParametersJson CHECK (ISJSON(ParametersJson)=1),
 CONSTRAINT CK_AnalyticsPayloadJson CHECK (ISJSON(PayloadJson)=1)
);
CREATE INDEX IX_AnalyticsSnapshotHistory ON analytics.DashboardSnapshot(RequestKey,GeneratedAt DESC);
CREATE INDEX IX_AnalyticsSnapshotCache ON analytics.DashboardSnapshot(CacheKey);
CREATE TABLE analytics.CurrentDashboardSnapshot (
 RequestKey char(64) NOT NULL PRIMARY KEY,
 SnapshotId varchar(36) NOT NULL REFERENCES analytics.DashboardSnapshot(SnapshotId)
);
CREATE TABLE analytics.RevenueSummary (
 SnapshotId varchar(36) NOT NULL REFERENCES analytics.DashboardSnapshot(SnapshotId),
 BusinessLine nvarchar(64) NOT NULL, RevenueEUR decimal(28,2) NULL,
 PreviousRevenueEUR decimal(28,2) NULL, PRIMARY KEY(SnapshotId,BusinessLine)
);
CREATE TABLE analytics.RevenueEntity (
 SnapshotId varchar(36) NOT NULL REFERENCES analytics.DashboardSnapshot(SnapshotId),
 Dimension varchar(32) NOT NULL, EntityId nvarchar(200) NOT NULL,
 EntityName nvarchar(1000) NOT NULL, Country nvarchar(500) NULL,
 KeyAccount nvarchar(500) NULL, RevenueEUR decimal(28,2) NULL,
 PreviousRevenueEUR decimal(28,2) NULL,
 PRIMARY KEY(SnapshotId,Dimension,EntityId)
);
CREATE TABLE analytics.RevenueEntityLine (
 SnapshotId varchar(36) NOT NULL, Dimension varchar(32) NOT NULL,
 EntityId nvarchar(200) NOT NULL, BusinessLine nvarchar(64) NOT NULL,
 RevenueEUR decimal(28,2) NULL, PreviousRevenueEUR decimal(28,2) NULL,
 FOREIGN KEY(SnapshotId,Dimension,EntityId) REFERENCES analytics.RevenueEntity(SnapshotId,Dimension,EntityId),
 PRIMARY KEY(SnapshotId,Dimension,EntityId,BusinessLine)
);
CREATE TABLE analytics.RevenueTrend (
 SnapshotId varchar(36) NOT NULL REFERENCES analytics.DashboardSnapshot(SnapshotId),
 Series varchar(40) NOT NULL, BusinessDate date NOT NULL,
 RevenueEUR decimal(28,2) NULL, PRIMARY KEY(SnapshotId,Series,BusinessDate)
);
CREATE TABLE analytics.ExcellenceMetric (
 SnapshotId varchar(36) NOT NULL REFERENCES analytics.DashboardSnapshot(SnapshotId),
 Section varchar(40) NOT NULL, MetricCode nvarchar(100) NOT NULL,
 Unit nvarchar(40) NULL, Value decimal(28,10) NULL,
 PRIMARY KEY(SnapshotId,Section,MetricCode)
);
CREATE TABLE analytics.ExcellenceDetail (
 SnapshotId varchar(36) NOT NULL REFERENCES analytics.DashboardSnapshot(SnapshotId),
 Section varchar(40) NOT NULL, RowNumber int NOT NULL,
 Entity nvarchar(1000) NULL, Model nvarchar(500) NULL, MineSite nvarchar(500) NULL,
 PeriodLabel nvarchar(100) NULL, MetricCode nvarchar(100) NOT NULL,
 Unit nvarchar(40) NULL, MetricValue decimal(28,10) NULL,
 EquipmentCount int NULL, DowntimeHours decimal(28,10) NULL,
 PRIMARY KEY(SnapshotId,Section,RowNumber)
);
CREATE TABLE analytics.DashboardScheduleState (
 StateKey varchar(40) NOT NULL PRIMARY KEY, StateJson nvarchar(max) NOT NULL,
 CONSTRAINT CK_AnalyticsStateJson CHECK (ISJSON(StateJson)=1)
);
GO
CREATE VIEW analytics.CurrentSnapshots AS
 SELECT s.* FROM analytics.DashboardSnapshot s
 JOIN analytics.CurrentDashboardSnapshot c ON c.SnapshotId=s.SnapshotId;
GO
CREATE VIEW analytics.CurrentRevenueSummary AS
 SELECT s.SnapshotId,s.UserId,s.UserName,s.GeneratedAt,s.DivisionScope,
 s.PeriodCode,s.PeriodStart,s.PeriodEnd,s.DataThroughDate,s.MappingVersion,
 s.ParametersJson,r.BusinessLine,r.RevenueEUR,r.PreviousRevenueEUR
 FROM analytics.CurrentSnapshots s JOIN analytics.RevenueSummary r ON r.SnapshotId=s.SnapshotId;
