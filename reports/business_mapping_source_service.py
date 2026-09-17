from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .business_mapping_country_scope import operating_country_for_company
from .business_mapping_normalization_service import normalize_business_name, payload_hash, stable_code
from .models import (
    BusinessAccount,
    BusinessCompanyCodeReference,
    EquipmentFleetAnalysis,
    FleetSourceSnapshot,
    MappingAuditLog,
    MappingSynchronizationRun,
    MineSite,
    PowerBIReport,
    RevenueSourceSnapshot,
    SourceAccountRecord,
    SourceAccountFieldOverride,
)
from .power_automate import execute_dax_via_flow
from .powerbi import execute_dataset_dax


DEFAULT_DATASET_ID = "a67ebcac-97d0-4d46-b84d-8109cd2c804a"
SOURCE_NAME = "Customer Fleet & Revenue Planning Model"
MINING_DIVISION = "MI"
BUSINESS_REVENUE_DIVISIONS = {
    "MI": "Mining",
    "TP": "Construction",
    "MO": "Energy",
}
MINING_REVENUE_LOBS = ("PRIME", "PARTS", "SERVICE", "RENTAL")
UNCLASSIFIED_REVENUE_LOB = "UNCLASSIFIED"
MINING_REVENUE_LABELS = {"PRIME": "Machine", "PARTS": "Parts", "SERVICE": "Service", "RENTAL": "Rental"}
MINING_EXCLUDED_DISTRIBUTION_CHANNELS = ("INTERCO",)
EQUIPMENT_DATASET_NAME = "FPR Global DB + RLS"
EQUIPMENT_SOURCE_TABLE = "EquipmentList_MiningProd"
EQUIPMENT_MAX_ROWS = 50000


class BusinessMappingSourceError(RuntimeError):
    pass


def _value(row: dict, name: str, default=""):
    compact = name.casefold().replace(" ", "").replace("_", "")
    for key, value in (row or {}).items():
        normalized = str(key).split("[")[-1].rstrip("]").casefold().replace(" ", "").replace("_", "")
        if normalized == compact:
            return value if value is not None else default
    return default


def _extract_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    rows = payload.get("firstTableRows")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    try:
        rows = payload["results"][0]["tables"][0]["rows"]
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    except (KeyError, IndexError, TypeError):
        pass
    for key in ("rows", "results", "body", "value"):
        rows = _extract_rows(payload.get(key))
        if rows:
            return rows
    return []


def _decimal_or_none(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _business_date(value):
    if value in (None, ""):
        return None
    digits = str(value).strip().split(".", 1)[0]
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def _snapshot_change_counts(previous_by_id, objects):
    created = updated = unchanged = 0
    for item in objects:
        previous_hash = previous_by_id.get(item.source_record_id)
        if previous_hash is None:
            created += 1
        elif previous_hash == item.source_hash:
            unchanged += 1
        else:
            updated += 1
    return created, updated, unchanged


class BusinessMappingSourceSynchronizationService:
    ACCOUNT_DAX = """
EVALUATE
SELECTCOLUMNS(
    'MiningAccounts',
    "source_record_id", 'MiningAccounts'[tie_code],
    "source_account_name", 'MiningAccounts'[tie_nom_tiers],
    "business_unit", 'MiningAccounts'[tie_bu_code],
    "jade_id", 'MiningAccounts'[tie_identifiant_jade],
    "source_customer_id", 'MiningAccounts'[tie_identifiant_source_tiers],
    "country_code", 'MiningAccounts'[tie_pay_code]
)
"""
    FLEET_DAX = """
EVALUATE
SELECTCOLUMNS(
    'Fleet',
    "customer", 'Fleet'[Customer],
    "minesite", 'Fleet'[Minesite],
    "equipment", 'Fleet'[Equipment],
    "equipment_type", 'Fleet'[Equipment Type],
    "model", 'Fleet'[Model],
    "serial_number", 'Fleet'[SerialNumber],
    "equipment_family", 'Fleet'[Parent Product Family],
    "brand", 'Fleet'[Brand]
)
"""
    REVENUE_DAX = """
EVALUATE
VAR _BusinessRevenue =
    FILTER(
        'ChriffreAffaire',
        'ChriffreAffaire'[Division] = "__DIVISION_CODE__"
            && UPPER('ChriffreAffaire'[Canal de distribution]) <> "INTERCO"
    )
VAR _LatestYear = MAXX(_BusinessRevenue, VALUE('ChriffreAffaire'[Année]))
VAR _RevenueWindow =
    FILTER(
        _BusinessRevenue,
        VALUE('ChriffreAffaire'[Année]) >= _LatestYear - 3
            && VALUE('ChriffreAffaire'[Année]) <= _LatestYear
    )
VAR _Groups =
    SUMMARIZE(
        _RevenueWindow,
        'ChriffreAffaire'[Code client Irium],
        'ChriffreAffaire'[Nom client],
        'ChriffreAffaire'[Code CIC],
        'ChriffreAffaire'[Code Société],
        'ChriffreAffaire'[Code Succursale],
        'ChriffreAffaire'[Date ecritures],
        'ChriffreAffaire'[LOB],
        'ChriffreAffaire'[Division],
        'ChriffreAffaire'[Canal de distribution],
        'ChriffreAffaire'[Année]
    )
RETURN
SELECTCOLUMNS(
    ADDCOLUMNS(
        _Groups,
        "revenue_eur", CALCULATE(SUM('ChriffreAffaire'[CA euro])),
        "invoice_count", CALCULATE(DISTINCTCOUNT('ChriffreAffaire'[Facture]))
    ),
    "source_account_code", 'ChriffreAffaire'[Code client Irium],
    "source_account_name", 'ChriffreAffaire'[Nom client],
    "code_cic", 'ChriffreAffaire'[Code CIC],
    "company_code", 'ChriffreAffaire'[Code Société],
    "branch_code", 'ChriffreAffaire'[Code Succursale],
    "business_date", 'ChriffreAffaire'[Date ecritures],
    "lob", 'ChriffreAffaire'[LOB],
    "division", 'ChriffreAffaire'[Division],
    "distribution_channel", 'ChriffreAffaire'[Canal de distribution],
    "period_year", VALUE('ChriffreAffaire'[Année]),
    "revenue_ytd_eur", [revenue_eur],
    "revenue_eur", [revenue_eur],
    "revenue_previous_year_eur", 0,
    "invoice_count", [invoice_count]
)
"""

    @classmethod
    def revenue_dax(cls, division_code):
        code = str(division_code or "").strip().upper()
        if code not in BUSINESS_REVENUE_DIVISIONS:
            raise BusinessMappingSourceError("The requested Revenue division is not governed.")
        return cls.REVENUE_DAX.replace("__DIVISION_CODE__", code)

    EQUIPMENT_ANALYSIS_DAX = f"""
EVALUATE
TOPN(
    {EQUIPMENT_MAX_ROWS + 1},
    SUMMARIZE(
        '{EQUIPMENT_SOURCE_TABLE}',
        '{EQUIPMENT_SOURCE_TABLE}'[Site],
        '{EQUIPMENT_SOURCE_TABLE}'[Equipment],
        '{EQUIPMENT_SOURCE_TABLE}'[Model],
        '{EQUIPMENT_SOURCE_TABLE}'[ParentProductGroup],
        '{EQUIPMENT_SOURCE_TABLE}'[SN],
        '{EQUIPMENT_SOURCE_TABLE}'[Brand],
        '{EQUIPMENT_SOURCE_TABLE}'[EquipID],
        '{EQUIPMENT_SOURCE_TABLE}'[Status],
        '{EQUIPMENT_SOURCE_TABLE}'[SMU.SMU]
    ),
    '{EQUIPMENT_SOURCE_TABLE}'[EquipID], ASC
)
"""

    def __init__(self, user=None, dataset_id=None):
        self.user = user
        self.dataset_id = dataset_id or getattr(settings, "BUSINESS_MAPPING_DATASET_ID", DEFAULT_DATASET_ID)

    def queue(self) -> MappingSynchronizationRun:
        return MappingSynchronizationRun.objects.create(
            source=SOURCE_NAME,
            initiated_by=self.user,
            status="Queued",
            progress_percent=0,
            stage_code="queued",
            stage_label="Waiting for the synchronization worker",
            heartbeat_at=timezone.now(),
        )

    @staticmethod
    def update_progress(run, percent, stage_code, stage_label):
        now = timezone.now()
        MappingSynchronizationRun.objects.filter(pk=run.pk).update(
            progress_percent=max(0, min(100, int(percent))),
            stage_code=stage_code,
            stage_label=stage_label,
            heartbeat_at=now,
        )
        run.progress_percent = max(0, min(100, int(percent)))
        run.stage_code = stage_code
        run.stage_label = stage_label
        run.heartbeat_at = now

    def fetch_source_rows(self):
        run = getattr(self, "_active_run", None)
        if run:
            self.update_progress(run, 10, "accounts", "Retrieving Business Accounts")
        account_rows = execute_dataset_dax(self.dataset_id, self.ACCOUNT_DAX)
        if run:
            self.update_progress(run, 25, "legacy_fleet", "Retrieving legacy Fleet references")
        fleet_rows = None
        try:
            fleet_rows = execute_dataset_dax(self.dataset_id, self.FLEET_DAX)
        except Exception as exc:
            self._source_warnings.append({
                "code": "LEGACY_FLEET_SOURCE_UNAVAILABLE",
                "message": str(exc)[:1000],
            })
        if run:
            self.update_progress(run, 40, "revenue", "Retrieving governed Revenue divisions")
        revenue_rows = []
        for division_code in BUSINESS_REVENUE_DIVISIONS:
            revenue_rows.extend(execute_dataset_dax(self.dataset_id, self.revenue_dax(division_code)))
        return account_rows, fleet_rows, revenue_rows

    def fetch_equipment_analysis_rows(self):
        report = PowerBIReport.objects.filter(
            is_active=True,
            report_name__iexact=EQUIPMENT_DATASET_NAME,
        ).order_by("id").first()
        if not report or not report.semantic_model_id:
            raise BusinessMappingSourceError("The EquipmentList_MiningProd semantic model is not configured.")
        payload = execute_dax_via_flow({
            "datasetId": report.semantic_model_id,
            "datasetName": EQUIPMENT_DATASET_NAME,
            "query": self.EQUIPMENT_ANALYSIS_DAX,
            "section": "business_mapping",
            "metric": "equipment_fleet_analysis",
            "filters": {},
        })
        rows = _extract_rows(payload)
        if len(rows) > EQUIPMENT_MAX_ROWS:
            raise BusinessMappingSourceError("EquipmentList_MiningProd exceeded the configured safe row limit.")
        return rows, report.semantic_model_id

    def process(self, run: MappingSynchronizationRun):
        with transaction.atomic():
            current = MappingSynchronizationRun.objects.select_for_update().get(pk=run.pk)
            if current.status not in {"Queued", "Failed", "Partial"}:
                return current
            current.status = "Running"
            current.started_at = timezone.now()
            current.completed_at = None
            current.errors_json = []
            current.save(update_fields=["status", "started_at", "completed_at", "errors_json"])
        run.refresh_from_db()
        self.update_progress(run, 5, "starting", "Starting source synchronization")
        self._source_warnings = []
        self._active_run = run
        try:
            account_rows, fleet_rows, revenue_rows = self.fetch_source_rows()
            self.update_progress(run, 60, "equipment", "Retrieving EquipmentList_MiningProd Fleet")
            equipment_rows, equipment_semantic_model_id = self.fetch_equipment_analysis_rows()
            self.update_progress(run, 75, "validating", "Validating source records")
            return self._commit_snapshot(
                run,
                account_rows,
                fleet_rows,
                revenue_rows,
                equipment_rows,
                equipment_semantic_model_id,
            )
        except Exception as exc:
            run.status = "Failed"
            run.completed_at = timezone.now()
            run.failure_count = 1
            run.progress_percent = 100
            run.stage_code = "failed"
            run.stage_label = "Source synchronization failed"
            run.heartbeat_at = timezone.now()
            run.errors_json = [{"code": "SOURCE_SYNCHRONIZATION_FAILED", "message": str(exc)[:1000]}]
            run.save(update_fields=["status", "completed_at", "failure_count", "progress_percent", "stage_code", "stage_label", "heartbeat_at", "errors_json"])
            raise BusinessMappingSourceError("The source data is temporarily unavailable. Existing validated mappings remain available.") from exc

    @transaction.atomic
    def _commit_snapshot(
        self,
        run,
        account_rows,
        fleet_rows,
        revenue_rows,
        equipment_rows,
        equipment_semantic_model_id,
    ):
        company_references = {
            item.company_code: item
            for item in BusinessCompanyCodeReference.objects.filter(active=True)
        }
        now = timezone.now()
        self.update_progress(run, 85, "saving", "Saving synchronized data to Mining 360")
        revenue_rows = [
            row for row in revenue_rows
            if str(_value(row, "division")).strip().upper() in BUSINESS_REVENUE_DIVISIONS
            and str(_value(row, "distribution_channel")).strip().upper() not in MINING_EXCLUDED_DISTRIBUTION_CHANNELS
        ]
        available_year_values = set()
        for row in revenue_rows:
            try:
                available_year_values.add(int(float(_value(row, "period_year"))))
            except (TypeError, ValueError):
                continue
        available_years = sorted(available_year_values, reverse=True)
        period_year = available_years[0] if available_years else None
        created = updated = unchanged = rejected = 0
        seen_accounts = set()
        synchronized_account_ids = set()
        country_overrides = {
            item.source_record_id: item.corrected_value
            for item in SourceAccountFieldOverride.objects.filter(
                source_system="MiningAccounts", field_name="country", active=True,
            )
        }
        for row in account_rows:
            source_id = str(_value(row, "source_record_id")).strip()
            if not source_id:
                continue
            name = str(_value(row, "source_account_name")).strip() or source_id
            normalized = normalize_business_name(name)
            source_country = str(_value(row, "country_code")).strip()
            country = country_overrides.get(source_id, source_country)
            account, account_created = BusinessAccount.objects.get_or_create(
                canonical_account_code=f"MININGACCOUNTS:{source_id}",
                defaults={"canonical_account_name": name, "normalized_account_name": normalized, "country": country, "origin_country": country, "created_by": self.user, "updated_by": self.user},
            )
            if account.country != country or account.origin_country != country:
                account.country = country
                account.origin_country = country
                account.updated_by = self.user
                account.save(update_fields=["country", "origin_country", "updated_by", "updated_at"])
            record_payload = {
                "business_unit": _value(row, "business_unit"),
                "jade_id": _value(row, "jade_id"),
                "source_customer_id": _value(row, "source_customer_id"),
                "normalization_version": "1.0",
                "source_country": source_country,
                "origin_country": country,
                "country_override_applied": country != source_country,
            }
            previous_record = SourceAccountRecord.objects.filter(source_system="MiningAccounts", source_record_id=source_id).only("source_hash").first()
            new_hash = payload_hash(row)
            _, record_created = SourceAccountRecord.objects.update_or_create(
                source_system="MiningAccounts",
                source_record_id=source_id,
                defaults={
                    "source_account_name": name, "normalized_account_name": normalized,
                    "country": country, "origin_country": country, "canonical_account": account,
                    "source_payload_json": record_payload, "source_hash": new_hash,
                    "source_last_seen_at": now, "active": True, "synchronization_run": run,
                },
            )
            seen_accounts.add(source_id)
            synchronized_account_ids.add(account.pk)
            if record_created:
                created += 1
            elif previous_record and previous_record.source_hash == new_hash:
                unchanged += 1
            else:
                updated += 1
        SourceAccountRecord.objects.filter(source_system="MiningAccounts", active=True).exclude(source_record_id__in=seen_accounts).update(active=False)
        from .business_mapping_country_account_service import CountryAccountService
        CountryAccountService.ensure_all_accounts_grouped(
            actor=self.user,
            account_ids=synchronized_account_ids,
        )

        fleet_objects = []
        site_names = {}
        if fleet_rows is not None:
            previous_fleet = FleetSourceSnapshot.objects.filter(active=True)
            previous_fleet_by_id = dict(previous_fleet.values_list("source_record_id", "source_hash"))
            previous_fleet_ids = previous_fleet.values_list("pk", flat=True)
            FleetSourceSnapshot.objects.filter(pk__in=previous_fleet_ids).update(active=False)
            for position, row in enumerate(fleet_rows):
                site_name = str(_value(row, "minesite")).strip()
                normalized_site = normalize_business_name(site_name)
                if site_name:
                    site_names[normalized_site] = site_name
                identity = "|".join(str(_value(row, field)) for field in ("serial_number", "equipment", "minesite", "customer")) + f"|{position}"
                fleet_objects.append(FleetSourceSnapshot(
                    synchronization_run=run, source_record_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    customer=str(_value(row, "customer")), normalized_customer=normalize_business_name(_value(row, "customer")),
                    minesite_name=site_name, normalized_minesite_name=normalized_site,
                    equipment=str(_value(row, "equipment")), equipment_type=str(_value(row, "equipment_type")),
                    model=str(_value(row, "model")), serial_number=str(_value(row, "serial_number")),
                    equipment_family=str(_value(row, "equipment_family")), brand=str(_value(row, "brand")),
                    source_hash=payload_hash(row), source_last_seen_at=now,
                ))
            FleetSourceSnapshot.objects.bulk_create(fleet_objects, batch_size=500)
            counts = _snapshot_change_counts(previous_fleet_by_id, fleet_objects)
            created += counts[0]
            updated += counts[1]
            unchanged += counts[2]

        previous_equipment = EquipmentFleetAnalysis.objects.filter(active=True)
        previous_equipment_by_id = dict(previous_equipment.values_list("source_record_id", "source_hash"))
        previous_equipment.update(active=False)
        equipment_objects = []
        for position, row in enumerate(equipment_rows):
            equipment_id = str(_value(row, "EquipID")).strip()
            serial_number = str(_value(row, "SN")).strip()
            equipment = str(_value(row, "Equipment")).strip()
            site = str(_value(row, "Site")).strip()
            identity = equipment_id or serial_number or f"{site}|{equipment}|{position}"
            source_record_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            equipment_objects.append(EquipmentFleetAnalysis(
                synchronization_run=run,
                source_record_id=source_record_id,
                semantic_model_id=equipment_semantic_model_id,
                equipment_id=equipment_id,
                site=site,
                normalized_site=normalize_business_name(site),
                equipment=equipment,
                model=str(_value(row, "Model")).strip(),
                serial_number=serial_number,
                equipment_family=str(_value(row, "ParentProductGroup")).strip(),
                brand=str(_value(row, "Brand")).strip(),
                source_status=str(_value(row, "Status")).strip(),
                smu=_decimal_or_none(_value(row, "SMU.SMU", None)),
                source_hash=payload_hash(row),
                source_last_seen_at=now,
            ))
            if site:
                site_names[normalize_business_name(site)] = site
        EquipmentFleetAnalysis.objects.bulk_create(equipment_objects, batch_size=500)
        counts = _snapshot_change_counts(previous_equipment_by_id, equipment_objects)
        created += counts[0]
        updated += counts[1]
        unchanged += counts[2]
        for normalized, original in site_names.items():
            MineSite.objects.get_or_create(
                minesite_code=stable_code("SITE", original),
                defaults={"canonical_minesite_name": original, "normalized_minesite_name": normalized, "source_version": str(run.id)},
            )

        previous_revenue = RevenueSourceSnapshot.objects.filter(active=True)
        previous_revenue_by_id = dict(previous_revenue.values_list("source_record_id", "source_hash"))
        previous_revenue.update(active=False)
        revenue_objects = []
        account_attributes = defaultdict(lambda: {
            "code_cic": set(), "company_code": set(), "company_name": set(),
            "branch_code": set(), "operating_country": set(),
        })
        for position, row in enumerate(revenue_rows):
            parts = [str(_value(row, field)) for field in ("source_account_code", "code_cic", "company_code", "branch_code", "lob", "division", "distribution_channel")]
            row_business_date = _business_date(_value(row, "business_date"))
            try:
                row_period_year = int(float(_value(row, "period_year")))
            except (TypeError, ValueError):
                row_period_year = period_year
            parts.append(str(row_period_year or ""))
            parts.append(row_business_date.isoformat() if row_business_date else "")
            source_id = hashlib.sha256(("|".join(parts) + f"|{position}").encode("utf-8")).hexdigest()
            company_reference = company_references.get(parts[2])
            operating_country = (
                company_reference.operating_country_code
                if company_reference else operating_country_for_company(parts[2], parts[3])
            )
            source_lob = parts[4].strip().upper()
            canonical_lob = source_lob if source_lob in MINING_REVENUE_LOBS else UNCLASSIFIED_REVENUE_LOB
            revenue_value = _value(row, "revenue_eur", _value(row, "revenue_ytd_eur", 0)) or 0
            revenue_objects.append(RevenueSourceSnapshot(
                synchronization_run=run, source_record_id=source_id,
                source_account_code=parts[0], source_account_name=str(_value(row, "source_account_name")),
                normalized_account_name=normalize_business_name(_value(row, "source_account_name")), code_cic=parts[1],
                company_code=parts[2], branch_code=parts[3], operating_country=operating_country,
                business_date=row_business_date, source_lob=source_lob, lob=canonical_lob,
                division=parts[5], distribution_channel=parts[6], period_year=row_period_year,
                revenue_ytd_eur=revenue_value, revenue_eur=revenue_value,
                revenue_previous_year_eur=_value(row, "revenue_previous_year_eur", 0) or 0,
                invoice_count=int(_value(row, "invoice_count", 0) or 0), source_hash=payload_hash(row), source_last_seen_at=now,
            ))
            for field, value in zip(("code_cic", "company_code", "branch_code"), parts[1:4]):
                if value:
                    account_attributes[parts[0]][field].add(value)
            if company_reference:
                account_attributes[parts[0]]["company_name"].add(company_reference.legal_entity_name)
            if operating_country:
                account_attributes[parts[0]]["operating_country"].add(operating_country)
        RevenueSourceSnapshot.objects.bulk_create(revenue_objects, batch_size=500)
        counts = _snapshot_change_counts(previous_revenue_by_id, revenue_objects)
        created += counts[0]
        updated += counts[1]
        unchanged += counts[2]
        SourceAccountRecord.objects.filter(source_system="MiningAccounts", active=True).update(operating_countries_json=[])
        enriched_records = list(SourceAccountRecord.objects.filter(source_system="MiningAccounts", source_record_id__in=account_attributes))
        for record in enriched_records:
            values = account_attributes[record.source_record_id]
            record.code_cic = next(iter(values["code_cic"])) if len(values["code_cic"]) == 1 else ""
            record.company_code = next(iter(values["company_code"])) if len(values["company_code"]) == 1 else ""
            record.branch_code = next(iter(values["branch_code"])) if len(values["branch_code"]) == 1 else ""
            record.operating_countries_json = sorted(values["operating_country"])
            record.source_payload_json = {
                **(record.source_payload_json or {}),
                "revenue_code_cic_values": sorted(values["code_cic"]),
                "revenue_company_code_values": sorted(values["company_code"]),
                "revenue_company_name_values": sorted(values["company_name"]),
                "revenue_branch_code_values": sorted(values["branch_code"]),
                "operating_countries": record.operating_countries_json,
            }
        SourceAccountRecord.objects.bulk_update(enriched_records, ["code_cic", "company_code", "branch_code", "operating_countries_json", "source_payload_json"], batch_size=500)
        canonical_operating_countries = defaultdict(set)
        for record in SourceAccountRecord.objects.filter(active=True, canonical_account__isnull=False).only("canonical_account_id", "operating_countries_json"):
            canonical_operating_countries[record.canonical_account_id].update(record.operating_countries_json or [])
        canonical_accounts = list(BusinessAccount.objects.filter(pk__in=canonical_operating_countries))
        for account in canonical_accounts:
            account.operating_countries_json = sorted(canonical_operating_countries[account.id])
        BusinessAccount.objects.bulk_update(canonical_accounts, ["operating_countries_json"], batch_size=500)
        # A non-critical legacy Fleet warning does not make the synchronized
        # Account, Revenue and EquipmentList_MiningProd snapshots partial.
        run.status = "Completed"
        run.completed_at = now
        run.records_read = len(account_rows) + len(fleet_rows or []) + len(revenue_rows) + len(equipment_rows)
        run.records_created = created
        run.records_updated = updated
        run.records_unchanged = unchanged
        run.records_rejected = rejected
        run.failure_count = 0
        run.source_version = str(run.id)
        run.source_context_json = {
            "revenue_period_kind": "YTD",
            "revenue_period_year": period_year,
            "previous_year": period_year - 1 if period_year else None,
            "available_revenue_years": available_years,
            "revenue_scope_code": "GOVERNED_BUSINESS_DIVISIONS",
            "revenue_division": MINING_DIVISION,
            "revenue_divisions": BUSINESS_REVENUE_DIVISIONS,
            "revenue_lobs": list(MINING_REVENUE_LOBS),
            "unclassified_revenue_lob": UNCLASSIFIED_REVENUE_LOB,
            "revenue_categories": MINING_REVENUE_LABELS,
            "revenue_excluded_distribution_channels": list(MINING_EXCLUDED_DISTRIBUTION_CHANNELS),
            "semantic_data_through": max((item.business_date for item in revenue_objects if item.business_date), default=None).isoformat() if any(item.business_date for item in revenue_objects) else None,
            "snapshot_completed_at": now.isoformat(),
            "fleet_snapshot_kind": "current_source_snapshot",
            "legacy_fleet_snapshot_updated": fleet_rows is not None,
            "fleet_analysis_source": EQUIPMENT_SOURCE_TABLE,
            "fleet_analysis_semantic_model_id": equipment_semantic_model_id,
            "fleet_analysis_row_count": len(equipment_objects),
            "mapping_state_kind": "current_database_state",
        }
        run.warnings_json = self._source_warnings
        run.progress_percent = 100
        run.stage_code = "completed_with_warnings" if self._source_warnings else "completed"
        run.stage_label = "Source synchronization completed with warnings" if self._source_warnings else "Source synchronization completed"
        run.heartbeat_at = now
        run.save()
        MappingAuditLog.objects.create(actor=self.user, action="Source synchronization", entity_type="MappingSynchronizationRun", entity_id=str(run.id), new_value_json={"records_read": run.records_read, "records_created": run.records_created, "records_updated": run.records_updated, "records_unchanged": run.records_unchanged, "records_rejected": run.records_rejected, "failure_count": run.failure_count})
        return run


def process_business_mapping_sync_run(run_id):
    """Run one queued synchronization with an isolated database connection."""
    close_old_connections()
    try:
        run = MappingSynchronizationRun.objects.select_related("initiated_by").get(pk=run_id)
        BusinessMappingSourceSynchronizationService(user=run.initiated_by).process(run)
    except (MappingSynchronizationRun.DoesNotExist, BusinessMappingSourceError):
        pass
    finally:
        close_old_connections()


def enqueue_business_mapping_sync(run):
    thread = threading.Thread(
        target=process_business_mapping_sync_run,
        args=(run.pk,),
        daemon=True,
        name=f"business-mapping-sync-{run.pk}",
    )
    thread.start()
    return run
