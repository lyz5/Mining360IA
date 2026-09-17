from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from .business_mapping_access_service import authorized_account_codes
from .business_mapping_source_service import _business_date, _extract_rows, _value
from .models import (
    EquipmentFleetAnalysis,
    EquipmentModelReference,
    EquipmentPrefixModelReference,
    EquipmentProductGroupReference,
    EquipmentSerialReference,
    MachineSaleDetail,
    MachineSalesSynchronizationRun,
    RevenueSourceSnapshot,
)
from .powerbi import execute_dataset_dax
from .sqlserver import connect


DEFAULT_DATASET_ID = "a67ebcac-97d0-4d46-b84d-8109cd2c804a"
SEMANTIC_MAX_ROWS = 50000
MACHINE_SALES_DAX = f"""
EVALUATE
VAR _MachineRevenue =
    FILTER(
        'ChriffreAffaire',
        'ChriffreAffaire'[Division] = "MI"
            && UPPER('ChriffreAffaire'[LOB]) = "PRIME"
            && UPPER('ChriffreAffaire'[Canal de distribution]) <> "INTERCO"
    )
VAR _LatestYear = MAXX(_MachineRevenue, VALUE('ChriffreAffaire'[Année]))
VAR _Window =
    FILTER(_MachineRevenue, VALUE('ChriffreAffaire'[Année]) >= _LatestYear - 3)
VAR _Groups =
    SUMMARIZE(
        _Window,
        'ChriffreAffaire'[Date ecritures],
        'ChriffreAffaire'[Code client Irium],
        'ChriffreAffaire'[Nom client],
        'ChriffreAffaire'[Code Equipement],
        'ChriffreAffaire'[N° de série],
        'ChriffreAffaire'[Produits détails],
        'ChriffreAffaire'[Facture],
        'ChriffreAffaire'[Canal de distribution],
        'ChriffreAffaire'[Etat machine],
        'ChriffreAffaire'[Code constructeur],
        'ChriffreAffaire'[Libellé constructeur]
    )
RETURN
TOPN(
    {SEMANTIC_MAX_ROWS + 1},
    SELECTCOLUMNS(
        ADDCOLUMNS(_Groups, "net_revenue_eur", CALCULATE(SUM('ChriffreAffaire'[CA euro]))),
        "business_date", 'ChriffreAffaire'[Date ecritures],
        "customer_code", 'ChriffreAffaire'[Code client Irium],
        "customer_name", 'ChriffreAffaire'[Nom client],
        "equipment_code", 'ChriffreAffaire'[Code Equipement],
        "serial_number", 'ChriffreAffaire'[N° de série],
        "product_detail", 'ChriffreAffaire'[Produits détails],
        "invoice_number", 'ChriffreAffaire'[Facture],
        "distribution_channel", 'ChriffreAffaire'[Canal de distribution],
        "machine_condition", 'ChriffreAffaire'[Etat machine],
        "brand_code", 'ChriffreAffaire'[Code constructeur],
        "brand_name", 'ChriffreAffaire'[Libellé constructeur],
        "net_revenue_eur", [net_revenue_eur]
    ),
    [business_date], DESC,
    [invoice_number], ASC,
    [equipment_code], ASC
)
"""

MACHINE_SALES_SQL = """
SELECT
    TRY_CONVERT(date, CONVERT(varchar(8), f.feca_tps_ak_date_ecriture_comptable), 112) AS business_date,
    COALESCE(CONVERT(varchar(160), t.tie_code), '') AS customer_code,
    COALESCE(CONVERT(varchar(500), t.tie_nom_tiers), '') AS customer_name,
    COALESCE(CONVERT(varchar(160), e.equ_sk), '') AS equipment_key,
    COALESCE(CONVERT(varchar(160), e.equ_code), '') AS equipment_code,
    COALESCE(CONVERT(varchar(255), e.equ_numero_serie), '') AS serial_number,
    COALESCE(CONVERT(varchar(160), e.equ_eme_code), '') AS model_code,
    COALESCE(CONVERT(varchar(255), m.eme_lib_modele_equipement), '') AS model_name,
    COALESCE(CONVERT(varchar(160), f.feca_num_piece_ecriture_comptable), '') AS invoice_number,
    COALESCE(CONVERT(varchar(20), f.feca_cdt_code), '') AS distribution_channel,
    COALESCE(CONVERT(varchar(20), e.equ_ind_vente), '') AS sale_status_code,
    COALESCE(CONVERT(varchar(20), e.equ_ind_neuf_occasion), '') AS new_used_code,
    SUM(COALESCE(f.feca_montant_credit_consolidation_analytique, 0)
      - COALESCE(f.feca_montant_debit_consolidation_analytique, 0)) AS net_revenue_eur
FROM dbo.ana_f_ecriture_analytique f
LEFT JOIN dbo.equ_d_equipement e ON e.equ_sk = f.feca_equ_sk
LEFT JOIN dbo.equ_d_modele_equipement m ON m.eme_sk = e.equ_eme_sk
LEFT JOIN dbo.tie_d_tiers t ON t.tie_sk = f.feca_tie_sk_client
WHERE f.feca_lob_code = 'PRIME'
  AND f.feca_taf_code = 'CA'
  AND f.feca_cdt_code IN ('On', 'Off')
  AND f.feca_tps_ak_date_ecriture_comptable >= ?
GROUP BY
    f.feca_tps_ak_date_ecriture_comptable, t.tie_code, t.tie_nom_tiers,
    e.equ_sk, e.equ_code, e.equ_numero_serie, e.equ_eme_code,
    m.eme_lib_modele_equipement, f.feca_num_piece_ecriture_comptable,
    f.feca_cdt_code, e.equ_ind_vente, e.equ_ind_neuf_occasion
"""


def _text(value):
    return str(value or "").strip()


def _code(value):
    return "".join(character for character in _text(value).upper() if character.isalnum())


def _record_id(values):
    identity = "|".join(_text(value) for value in values)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _record_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class MachineSalesSynchronizationService:
    """Incrementally materializes governed, direct Machine Sales from NMBEPM."""

    OVERLAP_DAYS = 14

    @classmethod
    def synchronize(cls, *, full=False):
        latest = MachineSaleDetail.objects.filter(active=True).aggregate(value=Max("business_date"))["value"]
        start = date(2023, 1, 1) if full or not latest else latest - timedelta(days=cls.OVERLAP_DAYS)
        run = MachineSalesSynchronizationRun.objects.create(incremental_from=start)
        now = timezone.now()
        try:
            rows = cls._read(start)
            payloads = [cls._payload(row) for row in rows]
            cls._enrich_equipment_dimensions(payloads)
            seen = set()
            created = updated = unchanged = 0
            with transaction.atomic():
                existing = {
                    item.source_record_id: item
                    for item in MachineSaleDetail.objects.filter(business_date__gte=start)
                }
                for payload in payloads:
                    source_id = _record_id([
                        payload["business_date"], payload["customer_code"], payload["equipment_key"],
                        payload["equipment_code"], payload["serial_number"], payload["product_category"],
                        payload["invoice_number"], payload["distribution_channel"], payload["new_used_code"],
                    ])
                    seen.add(source_id)
                    source_hash = _record_hash(payload)
                    item = existing.get(source_id)
                    if item is None:
                        MachineSaleDetail.objects.create(
                            source_record_id=source_id, source_hash=source_hash,
                            synchronization_run=run, source_last_seen_at=now, **payload,
                        )
                        created += 1
                    elif item.source_hash != source_hash or not item.active:
                        for key, value in payload.items():
                            setattr(item, key, value)
                        item.source_hash = source_hash
                        item.synchronization_run = run
                        item.source_last_seen_at = now
                        item.active = True
                        item.save()
                        updated += 1
                    else:
                        item.source_last_seen_at = now
                        item.synchronization_run = run
                        item.save(update_fields=["source_last_seen_at", "synchronization_run", "updated_at"])
                        unchanged += 1
                MachineSaleDetail.objects.filter(business_date__gte=start).exclude(source_record_id__in=seen).update(active=False)
                through = max((item["business_date"] for item in payloads if item["business_date"]), default=latest)
                warnings = []
                missing_serials = sum(1 for item in payloads if not item["serial_number"])
                if missing_serials:
                    warnings.append(f"{missing_serials} Machine Sales rows have no serial number.")
                run.status = "Completed with Warnings" if warnings else "Completed"
                run.data_through_date = through
                run.records_read = len(rows)
                run.records_created = created
                run.records_updated = updated
                run.records_unchanged = unchanged
                run.warnings_json = warnings
                run.completed_at = timezone.now()
                run.save()
            return run
        except Exception as exc:
            run.status = "Failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
            raise

    @staticmethod
    def _read(start):
        dataset_id = os.getenv("BUSINESS_MAPPING_DATASET_ID", DEFAULT_DATASET_ID)
        semantic_rows = _extract_rows(execute_dataset_dax(dataset_id, MACHINE_SALES_DAX))
        if len(semantic_rows) > SEMANTIC_MAX_ROWS:
            raise RuntimeError("Machine Sales exceeds the certified buffer limit of 50000 rows.")
        return [row for row in semantic_rows if (_business_date(_value(row, "business_date")) or date.min) >= start]

    @staticmethod
    def _read_nmbepm(start):
        server = os.getenv("NMBEPM_SQL_SERVER", "BODSQL\\BI01")
        database = os.getenv("NMBEPM_SQL_DATABASE", "NMBEPM")
        user = os.getenv("NMBEPM_SQL_USER", "neemba_user")
        password = os.getenv("NMBEPM_SQL_PASSWORD") or os.getenv("SQLSERVER_PASSWORD")
        with connect(server=server, database=database, user=user, password=password, driver="ODBC Driver 18 for SQL Server") as connection:
            cursor = connection.cursor()
            cursor.execute(MACHINE_SALES_SQL, int(start.strftime("%Y%m%d")))
            return list(cursor.fetchall())

    @staticmethod
    def _payload(row):
        if isinstance(row, dict):
            equipment_code = _text(_value(row, "equipment_code"))
            serial_number = _text(_value(row, "serial_number"))
            return {
                "business_date": _business_date(_value(row, "business_date")),
                "customer_code": _text(_value(row, "customer_code")),
                "customer_name": _text(_value(row, "customer_name")),
                "equipment_key": serial_number or equipment_code,
                "equipment_code": equipment_code,
                "serial_number": serial_number,
                "model_code": "",
                "model_name": "",
                "product_category": _text(_value(row, "product_detail")),
                "equipment_family": "",
                "family_code": "",
                "brand": MachineSalesSynchronizationService._brand(
                    _value(row, "brand_code") or _value(row, "brand_name")
                ),
                "invoice_number": _text(_value(row, "invoice_number")),
                "distribution_channel": _text(_value(row, "distribution_channel")),
                "sale_status_code": "",
                "new_used_code": _text(_value(row, "machine_condition")),
                "net_revenue_eur": Decimal(str(_value(row, "net_revenue_eur", 0) or 0)),
                "active": True,
            }
        return {
            "business_date": row[0], "customer_code": _text(row[1]), "customer_name": _text(row[2]),
            "equipment_key": _text(row[3]), "equipment_code": _text(row[4]), "serial_number": _text(row[5]),
            "model_code": _text(row[6]), "model_name": _text(row[7]), "invoice_number": _text(row[8]),
            "product_category": "", "equipment_family": "", "family_code": "", "brand": "",
            "distribution_channel": _text(row[9]), "sale_status_code": _text(row[10]),
            "new_used_code": _text(row[11]), "net_revenue_eur": Decimal(row[12] or 0), "active": True,
        }

    @staticmethod
    def _brand(value):
        clean = _text(value)
        normalized = clean.casefold()
        if normalized in {"cat", "caterpillar", "caterpillar inc"}:
            return "CAT"
        if normalized in {"epi", "epr", "epiroc"}:
            return "Epiroc"
        return clean

    @classmethod
    def _is_cat_brand(cls, value):
        return cls._brand(value) == "CAT"

    @staticmethod
    def _family_code(family, model):
        family_key = _text(family).casefold().replace("-", " ")
        model_key = _text(model).upper().replace(" ", "")
        if "hydraulic mining shovel" in family_key or model_key.startswith(("6015", "6020", "6030", "6040", "6050", "6060", "6090")):
            return "HMS"
        if "large mining truck" in family_key or model_key.startswith(("785", "789", "793", "794", "795", "797")):
            return "LMT"
        if "off highway truck" in family_key or model_key.startswith(("725", "730", "735", "740", "745", "770", "772", "773", "775", "777")):
            return "OHT"
        return ""

    @classmethod
    def _enrich_equipment_dimensions(cls, payloads):
        normalized_serials = {_code(item["serial_number"]) for item in payloads if item["serial_number"]}
        serial_references = {
            item.serial_number: item
            for item in EquipmentSerialReference.objects.filter(active=True, serial_number__in=normalized_serials)
        }
        prefixes = {serial[:3] for serial in normalized_serials if len(serial) >= 3}
        prefix_candidates = defaultdict(list)
        for reference in EquipmentPrefixModelReference.objects.filter(
            active=True, ambiguous_prefix=False, prefix__in=prefixes
        ).order_by("prefix", "model"):
            prefix_candidates[reference.prefix].append(reference)
        prefix_references = {}
        for prefix, references in prefix_candidates.items():
            distinct_models = {reference.model.casefold() for reference in references if reference.model}
            if len(distinct_models) == 1:
                prefix_references[prefix] = references[0]

        catalog = list(
            EquipmentModelReference.objects.filter(active=True, product_group__active=True)
            .select_related("product_group")
            .order_by("-normalized_model")
        )

        def catalog_match(model_name, brand):
            normalized_model = _code(model_name)
            normalized_brand = cls._brand(brand).casefold()
            if not normalized_model:
                return None
            candidates = [
                reference for reference in catalog
                if reference.normalized_model == normalized_model
                and (not normalized_brand or reference.brand.casefold() == normalized_brand)
            ]
            if not candidates:
                candidates = [
                    reference for reference in catalog
                    if normalized_model.startswith(reference.normalized_model)
                    and len(reference.normalized_model) >= 2
                    and (not normalized_brand or reference.brand.casefold() == normalized_brand)
                ]
                if candidates:
                    longest = max(len(reference.normalized_model) for reference in candidates)
                    candidates = [reference for reference in candidates if len(reference.normalized_model) == longest]
            classifications = {
                (reference.model, reference.family, reference.product_group.code)
                for reference in candidates
            }
            return candidates[0] if len(classifications) == 1 else None

        serials = {item["serial_number"] for item in payloads if item["serial_number"]}
        equipment_codes = {item["equipment_code"] for item in payloads if item["equipment_code"]}
        rows = EquipmentFleetAnalysis.objects.filter(active=True).filter(
            Q(serial_number__in=serials) | Q(equipment_id__in=equipment_codes) | Q(equipment__in=equipment_codes)
        ).order_by("-source_last_seen_at")
        by_serial, by_equipment = {}, {}
        for row in rows:
            if row.serial_number:
                by_serial.setdefault(row.serial_number, row)
            if row.equipment_id:
                by_equipment.setdefault(row.equipment_id, row)
            if row.equipment:
                by_equipment.setdefault(row.equipment, row)
        for item in payloads:
            normalized_serial = _code(item["serial_number"])
            exact_reference = serial_references.get(normalized_serial)
            if exact_reference:
                item["model_name"] = exact_reference.model
                item["model_code"] = exact_reference.model
                item["equipment_family"] = exact_reference.product_family
                item["brand"] = cls._brand(exact_reference.make) or item["brand"]

            match = by_serial.get(item["serial_number"]) or by_equipment.get(item["equipment_code"])
            if match:
                item["model_name"] = item["model_name"] or match.model
                item["model_code"] = item["model_code"] or match.model
                item["equipment_family"] = item["equipment_family"] or match.equipment_family
                item["brand"] = item["brand"] or cls._brand(match.brand)

            # Prefix references are governed CAT references. A shared-looking serial
            # prefix must never turn another manufacturer's machine into a CAT model.
            if item["brand"] and not cls._is_cat_brand(item["brand"]):
                item["equipment_family"] = "Divers"
                item["family_code"] = "OTHER"
                continue

            prefix_reference = (
                prefix_references.get(normalized_serial[:3])
                if cls._is_cat_brand(item["brand"])
                else None
            )
            if prefix_reference and not item["model_name"]:
                item["model_name"] = prefix_reference.model
                item["model_code"] = prefix_reference.model
                item["equipment_family"] = (
                    prefix_reference.product_family or prefix_reference.parent_product_family
                )
                item["brand"] = item["brand"] or cls._brand(prefix_reference.brand)
            model_reference = catalog_match(item["model_name"], item["brand"])
            if model_reference:
                item["equipment_family"] = model_reference.family or item["equipment_family"]
                item["family_code"] = model_reference.product_group.code
                item["brand"] = item["brand"] or cls._brand(model_reference.brand)
            else:
                item["family_code"] = cls._family_code(item["equipment_family"], item["model_name"])


class MachineSalesDetailService:
    PAGE_SIZE = 50
    MAX_PAGE_SIZE = 150
    OTHER_CHARGE_CATEGORIES = {"", "misc", "undefined"}

    def __init__(self, user, params):
        self.user = user
        self.params = params

    @classmethod
    def _is_other_charge(cls, category):
        return _text(category).casefold() in cls.OTHER_CHARGE_CATEGORIES

    @staticmethod
    def _sort_groups(groups, family_catalog):
        priorities = {
            str(group["code"]).upper(): int(group["priority"])
            for group in family_catalog
            if group.get("code")
        }

        def sort_key(group):
            if group["record_type"] == "reconciliation_adjustment":
                section = 3
                priority = 0
            else:
                family_code = _text(group["family_code"]).upper()
                if family_code == "OTHER":
                    section = 2
                    priority = 0
                elif not family_code:
                    section = 1
                    priority = 0
                else:
                    section = 0
                    priority = priorities.get(family_code, 9999)
            return (
                section,
                priority,
                -(group["net_revenue_eur"] or Decimal("0")),
                -group["business_date"].toordinal(),
                _text(group["customer_name"]).casefold(),
            )

        groups.sort(key=sort_key)
        return groups

    @classmethod
    def _aggregate_equipment(cls, rows):
        groups = {}
        for item in rows:
            group_key = (item.customer_code, item.equipment_key or f"source:{item.source_record_id}")
            group = groups.setdefault(group_key, {
                "id": "|".join(group_key),
                "record_type": "equipment",
                "business_date": item.business_date,
                "customer_code": item.customer_code,
                "customer_name": item.customer_name,
                "equipment_code": item.equipment_code,
                "serial_number": item.serial_number,
                "model_code": item.model_code,
                "model_name": item.model_name,
                "equipment_family": item.equipment_family,
                "family_code": item.family_code,
                "brand": item.brand,
                "invoice_numbers": set(),
                "conditions": set(),
                "product_categories": set(),
                "machine_sale_eur": Decimal("0"),
                "other_charges_eur": Decimal("0"),
                "net_revenue_eur": Decimal("0"),
                "entries": [],
            })
            group["business_date"] = max(group["business_date"], item.business_date)
            for field in ("customer_name", "equipment_code", "serial_number", "model_code", "model_name", "equipment_family", "family_code", "brand"):
                if not group[field] and getattr(item, field):
                    group[field] = getattr(item, field)
            if item.invoice_number:
                group["invoice_numbers"].add(item.invoice_number)
            if item.new_used_code:
                group["conditions"].add(item.new_used_code)
            if item.product_category:
                group["product_categories"].add(item.product_category)
            amount = item.net_revenue_eur or Decimal("0")
            is_other_charge = cls._is_other_charge(item.product_category)
            bucket = "other_charges_eur" if is_other_charge else "machine_sale_eur"
            group[bucket] += amount
            group["net_revenue_eur"] += amount
            group["entries"].append({
                "business_date": item.business_date.isoformat(),
                "invoice_number": item.invoice_number,
                "product_category": item.product_category or "Unclassified",
                "classification": "Other Charges & Adjustments" if is_other_charge else "Machine Sale",
                "amount_eur": float(amount),
            })
        for group in groups.values():
            group["invoice_numbers"] = sorted(group["invoice_numbers"])
            group["conditions"] = sorted(group["conditions"])
            group["product_categories"] = sorted(group["product_categories"])
            group["entries"].sort(key=lambda row: (row["business_date"], row["invoice_number"]), reverse=True)
        return list(groups.values())

    @staticmethod
    def _reconciliation_groups(source_rows, certified_queryset):
        raw_by_key = defaultdict(Decimal)
        names_by_key = {}
        invoices_by_key = defaultdict(set)
        for item in source_rows:
            key = (item.business_date, item.customer_code)
            raw_by_key[key] += item.net_revenue_eur or Decimal("0")
            names_by_key[key] = item.customer_name
            if item.invoice_number:
                invoices_by_key[key].add(item.invoice_number)
        certified_by_key = {
            (row["business_date"], row["source_account_code"]): row["value"] or Decimal("0")
            for row in certified_queryset.values("business_date", "source_account_code").annotate(value=Sum("revenue_eur"))
        }
        groups = []
        rounding_residual = Decimal("0")
        for key in sorted(set(raw_by_key) | set(certified_by_key)):
            difference = certified_by_key.get(key, Decimal("0")) - raw_by_key.get(key, Decimal("0"))
            if abs(difference) < Decimal("1.00"):
                rounding_residual += difference
                continue
            business_date, customer_code = key
            invoices = sorted(invoices_by_key[key])
            groups.append({
                "id": f"reconciliation|{business_date.isoformat()}|{customer_code}",
                "record_type": "reconciliation_adjustment",
                "business_date": business_date,
                "customer_code": customer_code,
                "customer_name": names_by_key.get(key, "Portfolio reconciliation"),
                "equipment_code": "",
                "serial_number": "",
                "model_code": "",
                "model_name": "Reconciliation adjustment",
                "equipment_family": "",
                "family_code": "",
                "brand": "",
                "invoice_numbers": invoices if len(invoices) == 1 else [],
                "conditions": [],
                "product_categories": ["Certified invoice-level reconciliation"],
                "machine_sale_eur": Decimal("0"),
                "other_charges_eur": difference,
                "net_revenue_eur": difference,
                "entries": [{
                    "business_date": business_date.isoformat(),
                    "invoice_number": invoices[0] if len(invoices) == 1 else "",
                    "product_category": "Certified invoice-level reconciliation",
                    "classification": "Reconciliation Adjustment",
                    "amount_eur": float(difference),
                }],
            })
        if abs(rounding_residual) > Decimal("0.005"):
            business_date = max((item.business_date for item in source_rows), default=date.today())
            groups.append({
                "id": f"reconciliation|rounding|{business_date.isoformat()}",
                "record_type": "reconciliation_adjustment",
                "business_date": business_date,
                "customer_code": "",
                "customer_name": "Portfolio rounding reconciliation",
                "equipment_code": "",
                "serial_number": "",
                "model_code": "",
                "model_name": "Rounding adjustment",
                "equipment_family": "",
                "family_code": "",
                "brand": "",
                "invoice_numbers": [],
                "conditions": [],
                "product_categories": ["Certified rounding reconciliation"],
                "machine_sale_eur": Decimal("0"),
                "other_charges_eur": rounding_residual,
                "net_revenue_eur": rounding_residual,
                "entries": [{
                    "business_date": business_date.isoformat(),
                    "invoice_number": "",
                    "product_category": "Certified rounding reconciliation",
                    "classification": "Rounding Adjustment",
                    "amount_eur": float(rounding_residual),
                }],
            })
        return groups

    def result(self):
        queryset = MachineSaleDetail.objects.filter(active=True)
        start, end = self.params.get("start_date"), self.params.get("end_date")
        if start:
            queryset = queryset.filter(business_date__gte=start)
        if end:
            queryset = queryset.filter(business_date__lte=end)
        search = str(self.params.get("search") or "").strip().casefold()
        account_scope = authorized_account_codes(self.user)
        if account_scope is not None:
            queryset = queryset.filter(customer_code__in=account_scope) if account_scope else queryset.none()
        customer_ids = {value for value in str(self.params.get("customer_codes") or "").split(",") if value}
        if customer_ids:
            queryset = queryset.filter(customer_code__in=customer_ids)
        family_totals = {
            row["family_code"]: row
            for row in queryset.exclude(family_code="").values("family_code").annotate(
                revenue_eur=Sum("net_revenue_eur"),
                detail_rows=Count("id"),
                equipment_count=Count("equipment_key", distinct=True),
            )
        }
        family_catalog = list(
            EquipmentProductGroupReference.objects.filter(active=True)
            .order_by("priority", "code")
            .values("code", "description", "priority")
        )
        if not family_catalog:
            family_catalog = [
                {"code": code, "description": code, "priority": index}
                for index, code in enumerate(sorted(family_totals), start=1)
            ]
        family_groups = []
        for group in family_catalog:
            totals = family_totals.get(group["code"], {})
            family_groups.append({
                "code": group["code"],
                "description": group["description"],
                "priority": group["priority"],
                "revenue_eur": float(totals.get("revenue_eur") or 0),
                "detail_rows": int(totals.get("detail_rows") or 0),
                "equipment_count": int(totals.get("equipment_count") or 0),
            })
        unclassified = queryset.filter(family_code="").aggregate(
            revenue_eur=Sum("net_revenue_eur"),
            detail_rows=Count("id"),
            equipment_count=Count("equipment_key", distinct=True),
        )
        filter_options = {
            "families": [group["code"] for group in family_groups],
            "family_groups": family_groups,
            "unclassified_family": {
                "revenue_eur": float(unclassified.get("revenue_eur") or 0),
                "detail_rows": int(unclassified.get("detail_rows") or 0),
                "equipment_count": int(unclassified.get("equipment_count") or 0),
            },
            "brands": list(queryset.exclude(brand="").order_by("brand").values_list("brand", flat=True).distinct()),
        }
        family = _text(self.params.get("family"))
        brand = _text(self.params.get("brand"))
        if family:
            queryset = queryset.filter(family_code=family)
        if brand:
            queryset = queryset.filter(brand=brand)

        source_rows = list(queryset.order_by("customer_code", "equipment_key", "business_date", "invoice_number"))
        groups = self._aggregate_equipment(source_rows)
        reconciliation_applied = not search and not family and not brand
        if reconciliation_applied:
            certified = RevenueSourceSnapshot.objects.filter(
                active=True, division__iexact="MI", lob="PRIME",
            )
            if start:
                certified = certified.filter(business_date__gte=start)
            if end:
                certified = certified.filter(business_date__lte=end)
            if account_scope is not None:
                certified = certified.filter(source_account_code__in=account_scope) if account_scope else certified.none()
            if customer_ids:
                certified = certified.filter(source_account_code__in=customer_ids)
            groups.extend(self._reconciliation_groups(source_rows, certified))
        if search:
            groups = [group for group in groups if search in " ".join([
                group["customer_name"], group["customer_code"], group["serial_number"],
                group["model_name"], group["model_code"], group["equipment_code"],
                *group["invoice_numbers"], *group["product_categories"],
            ]).casefold()]
        self._sort_groups(groups, family_catalog)
        all_entries = [entry for group in groups for entry in group["entries"]]
        invoice_numbers = {entry["invoice_number"] for entry in all_entries if entry["invoice_number"]}
        serial_numbers = {group["serial_number"] for group in groups if group["serial_number"]}
        page = max(1, int(self.params.get("page") or 1))
        page_size = min(self.MAX_PAGE_SIZE, max(1, int(self.params.get("page_size") or self.PAGE_SIZE)))
        total = len(groups)
        offset = (page - 1) * page_size
        rows = groups[offset:offset + page_size]
        last_run = MachineSalesSynchronizationRun.objects.filter(status__in=["Completed", "Completed with Warnings"]).first()
        return {
            "ready": bool(last_run),
            "freshness": {
                "data_through_date": last_run.data_through_date.isoformat() if last_run and last_run.data_through_date else None,
                "synchronized_at": last_run.completed_at if last_run else None,
                "status": last_run.status if last_run else "Not synchronized",
            },
            "summary": {
                "detail_rows": len(all_entries),
                "equipment_count": sum(1 for group in groups if group["record_type"] == "equipment"),
                "serial_count": len(serial_numbers), "invoice_count": len(invoice_numbers),
                "machine_sale_eur": float(sum((group["machine_sale_eur"] for group in groups), Decimal("0"))),
                "other_charges_eur": float(sum((group["other_charges_eur"] for group in groups), Decimal("0"))),
                "net_revenue_eur": float(sum((group["net_revenue_eur"] for group in groups), Decimal("0"))),
                "missing_serial_count": sum(1 for group in groups if group["record_type"] == "equipment" and not group["serial_number"]),
                "reconciliation_adjustment_eur": float(sum((
                    group["net_revenue_eur"] for group in groups if group["record_type"] == "reconciliation_adjustment"
                ), Decimal("0"))),
                "reconciliation_status": "Reconciled to certified Machine Revenue" if reconciliation_applied else "Detail filters active",
            },
            "filter_options": filter_options,
            "pagination": {"page": page, "page_size": page_size, "count": total, "pages": (total + page_size - 1) // page_size},
            "results": [{
                "id": item["id"], "record_type": item["record_type"], "business_date": item["business_date"].isoformat(),
                "customer_code": item["customer_code"], "customer_name": item["customer_name"],
                "equipment_code": item["equipment_code"], "serial_number": item["serial_number"] or None,
                "model_code": item["model_code"], "model_name": item["model_name"],
                "product_categories": item["product_categories"],
                "equipment_family": item["equipment_family"], "family_code": item["family_code"],
                "product_group_priority": next((
                    group["priority"] for group in family_catalog if group["code"] == item["family_code"]
                ), None),
                "brand": item["brand"], "invoice_numbers": item["invoice_numbers"],
                "invoice_count": len(item["invoice_numbers"]), "conditions": item["conditions"],
                "transaction_count": len(item["entries"]), "entries": item["entries"],
                "machine_sale_eur": float(item["machine_sale_eur"]),
                "other_charges_eur": float(item["other_charges_eur"]),
                "net_revenue_eur": float(item["net_revenue_eur"]),
            } for item in rows],
        }
