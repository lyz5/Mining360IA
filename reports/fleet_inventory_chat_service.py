from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata

from django.conf import settings

from .ai_config_service import get_filter_mapping
from .models import PowerBIReport
from .power_automate import PowerAutomateTransientError, execute_dax_via_flow


DATASET_NAME = "FPR Global DB + RLS"
SOURCE_TABLE = "EquipmentList_MiningProd"
FIELD_CODES = {
    "site": "fleet_site",
    "equipment": "fleet_equipment",
    "model": "fleet_model",
    "equipment_family": "fleet_family",
    "serial_number": "fleet_serial_number",
    "brand": "fleet_brand",
    "equipment_id": "fleet_equipment_id",
    "status": "fleet_status",
    "smu": "fleet_smu",
}
DISPLAY_COLUMNS = ("Site", "Equipment", "Model", "Serial Number")


class FleetInventoryError(RuntimeError):
    def __init__(self, message: str, *, code: str = "fleet_inventory_unavailable", status: int = 503):
        super().__init__(message)
        self.code = code
        self.status = status


def _feature_enabled(setting_name: str, user) -> bool:
    mode = str(getattr(settings, setting_name, "Disabled") or "Disabled").strip().casefold()
    if mode in {"disabled", "false", "0", "off"}:
        return False
    if mode in {"admin only", "admin_only", "admin", "pilot"}:
        platform_admin = False
        if user:
            try:
                platform_admin = bool(user.platformuser.is_platform_admin)
            except Exception:
                platform_admin = False
        return bool(user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False) or platform_admin))
    return True


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.\-/]+", " ", text)).strip()


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", _normalize(value))


def _dax_string(value: object) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _dax_column(mapping: dict) -> str:
    table = str(mapping.get("powerbi_table_name") or "").replace("'", "''")
    column = str(mapping.get("powerbi_column_name") or "").replace("]", "]]" )
    if table != SOURCE_TABLE or not column:
        raise FleetInventoryError("Fleet Inventory field mappings are invalid.", code="fleet_mapping_invalid")
    return f"'{table}'[{column}]"


def _clean_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _row_value(row: dict, *names: str):
    values = {_clean_key(key): value for key, value in (row or {}).items()}
    for name in names:
        key = _clean_key(name)
        if key in values:
            return values[key]
        for source_key, value in values.items():
            if source_key.endswith(key):
                return value
    return None


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


@dataclass(frozen=True)
class FleetSource:
    report: PowerBIReport
    mappings: dict[str, dict]


class FleetSemanticQueryService:
    """Build fixed DAX queries over the governed equipment master table."""

    def __init__(self, user=None, max_rows: int = 5000):
        self.user = user
        self.max_rows = max(100, min(int(max_rows or 5000), 50000))
        mappings = {
            item["filter_code"]: item
            for item in get_filter_mapping("performance")
            if item.get("is_active")
        }
        selected = {}
        for field, code in FIELD_CODES.items():
            mapping = mappings.get(code)
            if not mapping:
                raise FleetInventoryError(f"The governed mapping '{code}' is missing.", code="fleet_mapping_missing")
            _dax_column(mapping)
            selected[field] = mapping
        report = PowerBIReport.objects.filter(
            is_active=True, report_name__iexact=DATASET_NAME,
        ).order_by("id").first()
        if not report:
            raise FleetInventoryError("The Fleet Performance semantic model is not configured.", code="fleet_semantic_model_missing")
        self.source = FleetSource(report=report, mappings=selected)

    def build_details_dax(self, *, site: str = "", model: str = "", serial: str = "", equipment: str = "") -> str:
        columns = {name: _dax_column(mapping) for name, mapping in self.source.mappings.items()}
        clauses = []
        for value, field in ((site, "site"), (model, "model"), (serial, "serial_number"), (equipment, "equipment")):
            if str(value or "").strip():
                clauses.append(f"TREATAS({{{_dax_string(str(value).strip())}}}, {columns[field]})")
        filters = ",\n        ".join(clauses)
        if filters:
            filters = ",\n        " + filters
        source_columns = ",\n            ".join(columns.values())
        return f"""
DEFINE
VAR __Fleet =
    CALCULATETABLE(
        SUMMARIZE(
            '{SOURCE_TABLE}',
            {source_columns}
        ){filters}
    )
EVALUATE
TOPN({self.max_rows + 1}, __Fleet)
""".strip()

    def execute(self, flow_context: dict, **filters) -> tuple[list[dict], str, dict]:
        dax = self.build_details_dax(**filters)
        payload = {
            **flow_context,
            "datasetId": self.source.report.semantic_model_id,
            "datasetName": DATASET_NAME,
            "query": dax,
            "section": "performance",
            "metric": "fleet_inventory",
            "filters": {key: value for key, value in filters.items() if value},
        }
        try:
            result = execute_dax_via_flow(payload)
        except PowerAutomateTransientError as exc:
            raise FleetInventoryError("Fleet data is temporarily unavailable. Please try again.", code="fleet_inventory_temporarily_unavailable") from exc
        except RuntimeError as exc:
            raise FleetInventoryError("Fleet data could not be loaded.") from exc
        return _extract_rows(result), dax, result


class FleetResultNormalizationService:
    @staticmethod
    def normalize(raw_rows: list[dict], *, max_rows: int = 5000) -> dict:
        truncated = len(raw_rows) > max_rows
        raw_rows = raw_rows[:max_rows]
        normalized = []
        for row in raw_rows:
            normalized.append({
                "site": str(_row_value(row, "Site") or "Not available").strip(),
                "equipment": str(_row_value(row, "Equipment") or "Not available").strip(),
                "model": str(_row_value(row, "Model") or "Unknown Model").strip(),
                "serial_number": str(_row_value(row, "Serial Number", "SN") or "Not available").strip(),
                "equipment_family": str(_row_value(row, "Equipment Family", "ParentProductGroup") or "Not classified").strip(),
                "brand": str(_row_value(row, "Brand") or "Not available").strip(),
                "equipment_id": str(_row_value(row, "Equipment ID", "EquipID") or "").strip(),
                "status": None,
                "status_display": "Status not mapped",
                "smu": _row_value(row, "SMU", "SMU.SMU"),
            })
        serial_counts = Counter(_compact(row["serial_number"]) for row in normalized if row["serial_number"] != "Not available")
        seen = set()
        distinct = []
        for row in normalized:
            if row["equipment_id"]:
                key = ("equipment_id", _normalize(row["equipment_id"]))
            elif row["serial_number"] != "Not available" and serial_counts[_compact(row["serial_number"])] == 1:
                key = ("serial", _compact(row["serial_number"]))
            else:
                key = ("composite", _normalize(row["site"]), _normalize(row["equipment"]), _normalize(row["model"]), _compact(row["serial_number"]))
            if key in seen:
                continue
            seen.add(key)
            distinct.append(row)
        distinct.sort(key=lambda row: (_normalize(row["model"]), _normalize(row["equipment"]), _compact(row["serial_number"])))
        return {
            "rows": distinct,
            "source_row_count": len(normalized),
            "distinct_equipment_count": len(distinct),
            "duplicate_count": len(normalized) - len(distinct),
            "is_complete": not truncated,
        }


class FleetModelSummaryService:
    @staticmethod
    def summarize(rows: list[dict]) -> list[dict]:
        counts = Counter(row["model"] for row in rows)
        total = len(rows)
        return [
            {"model": model, "equipment_count": count, "share_of_fleet": round(count / total, 6) if total else 0}
            for model, count in sorted(counts.items(), key=lambda item: (-item[1], _normalize(item[0])))
        ]


class FleetInventoryService:
    def __init__(self, user=None, max_rows: int = 5000):
        if not _feature_enabled("ENABLE_FLEET_INVENTORY_CHAT", user):
            raise FleetInventoryError("Fleet Inventory is not enabled for this user.", code="fleet_inventory_disabled", status=403)
        self.query = FleetSemanticQueryService(user=user, max_rows=max_rows)
        self.max_rows = self.query.max_rows

    @staticmethod
    def answer(site: str, equipment_count: int, model_count: int, *, language: str) -> str:
        if language == "fr":
            return f"La flotte de {site} comprend {equipment_count} équipements répartis sur {model_count} modèles."
        return f"The {site} fleet contains {equipment_count} equipment units across {model_count} models."

    def execute(self, intent: dict, flow_context: dict, *, question_text: str = "") -> dict:
        filters = dict(intent.get("filters") or {})
        site = str(filters.get("minesite") or filters.get("site") or "").strip()
        model = str(filters.get("model") or "").strip()
        if not site:
            raise FleetInventoryError("A MineSite is required.", code="fleet_site_required", status=400)
        raw_rows, dax, powerbi_result = self.query.execute(flow_context, site=site, model=model)
        result = FleetResultNormalizationService.normalize(raw_rows, max_rows=self.max_rows)
        if not result["is_complete"]:
            raise FleetInventoryError("The fleet result exceeded the configured safe row limit and cannot be presented as complete.", code="fleet_result_truncated")
        rows = result["rows"]
        if not rows:
            if model:
                message = f"No Model {model} equipment was found at {site}."
                code = "fleet_model_not_found"
            else:
                message = "No equipment was found for the selected MineSite."
                code = "fleet_no_equipment"
            raise FleetInventoryError(message, code=code, status=404)
        summary = FleetModelSummaryService.summarize(rows)
        language = "fr" if re.search(r"\b(?:flotte|parc|equipements|équipements|machines|donne|montre|combien)\b", question_text.casefold()) else "en"
        response_site = rows[0]["site"] if rows else site
        return {
            **result,
            "intent": "get_site_model_fleet" if model else str(intent.get("intent_type") or "get_site_fleet"),
            "answer": self.answer(response_site, len(rows), len(summary), language=language),
            "site": response_site,
            "model": model or None,
            "by_model": summary,
            "dax": dax,
            "metric": "fleet_inventory",
            "measure": "",
            "powerbi_result": powerbi_result,
            "source": {"semantic_model_id": self.query.source.report.semantic_model_id, "table": SOURCE_TABLE, "last_refresh_at": None},
            "mandatory_columns": list(DISPLAY_COLUMNS),
        }


class EquipmentSerialResolutionService:
    @staticmethod
    def resolve(rows: list[dict], query: str, field: str) -> dict:
        source_field = "serial_number" if field == "serial" else "equipment"
        matched = [row for row in rows if str(row[source_field]) == query]
        match_type = "exact"
        if not matched:
            matched = [row for row in rows if str(row[source_field]).casefold() == query.casefold()]
            match_type = "case_insensitive_exact"
        if not matched:
            matched = [row for row in rows if _compact(row[source_field]) == _compact(query)]
            match_type = "normalized_unique"
        if len(matched) == 1:
            return {"machine": matched[0], "match_type": match_type, "confidence": 100}
        if len(matched) > 1:
            return {"matches": matched, "match_type": match_type, "confidence": 100}
        return {"matches": [], "match_type": "not_found", "confidence": 0}


class EquipmentLookupService:
    def __init__(self, user=None, max_rows: int = 5000, *, enforce_feature_flag: bool = True):
        if enforce_feature_flag and not _feature_enabled("ENABLE_EQUIPMENT_SERIAL_LOOKUP", user):
            raise FleetInventoryError("Equipment lookup is not enabled for this user.", code="equipment_lookup_disabled", status=403)
        self.query = FleetSemanticQueryService(user=user, max_rows=max_rows)
        self.max_rows = self.query.max_rows

    def execute(self, intent: dict, flow_context: dict, *, question_text: str = "") -> dict:
        filters = dict(intent.get("filters") or {})
        serial = str(filters.get("serial_number") or "").strip()
        equipment = str(filters.get("equipment") or "").strip()
        lookup = serial or equipment
        lookup_type = "serial" if serial else "equipment"
        if not lookup:
            raise FleetInventoryError("A Serial Number or Equipment identifier is required.", code="equipment_lookup_required", status=400)
        raw_rows, dax, powerbi_result = self.query.execute(flow_context, **({"serial": serial} if serial else {"equipment": equipment}))
        normalized = FleetResultNormalizationService.normalize(raw_rows, max_rows=self.max_rows)
        resolution = EquipmentSerialResolutionService.resolve(normalized["rows"], lookup, lookup_type)
        if not resolution.get("machine") and not resolution.get("matches"):
            all_rows, retry_dax, powerbi_result = self.query.execute(flow_context)
            normalized = FleetResultNormalizationService.normalize(all_rows, max_rows=self.max_rows)
            resolution = EquipmentSerialResolutionService.resolve(normalized["rows"], lookup, lookup_type)
            dax = f"{dax}\n\n-- Controlled normalized lookup fallback\n{retry_dax}"
        if resolution.get("matches"):
            raise FleetInventoryError("Several equipment records match this identifier.", code="equipment_lookup_ambiguous", status=409)
        machine = resolution.get("machine")
        if not machine:
            label = "Serial Number" if lookup_type == "serial" else "Equipment"
            raise FleetInventoryError(f"No equipment was found for {label} {lookup}.", code="equipment_not_found", status=404)
        language = "fr" if re.search(r"\b(?:donne|numero|numéro|serie|série|ou|où|quel)\b", question_text.casefold()) else "en"
        answer = (
            f"Le numéro de série {machine['serial_number']} correspond à l’équipement {machine['equipment']}, modèle {machine['model']}, sur le site {machine['site']}."
            if language == "fr" else
            f"Serial Number {machine['serial_number']} belongs to equipment {machine['equipment']}, Model {machine['model']}, at {machine['site']}."
        )
        return {
            "intent": "lookup_equipment_by_serial" if lookup_type == "serial" else "lookup_equipment_by_code",
            "answer": answer,
            "machine": machine,
            "lookup": {"original_query": lookup, "match_type": resolution["match_type"], "confidence": resolution["confidence"], "matched_source_serial": machine["serial_number"] if lookup_type == "serial" else None},
            "dax": dax,
            "metric": "fleet_inventory",
            "measure": "",
            "powerbi_result": powerbi_result,
            "source": {"semantic_model_id": self.query.source.report.semantic_model_id, "table": SOURCE_TABLE, "last_refresh_at": None},
        }


def execute_fleet_inventory_intent(intent: dict, flow_context: dict, *, user=None, question_text: str = "") -> dict:
    if str(intent.get("intent_type") or "").startswith("lookup_equipment"):
        return EquipmentLookupService(user).execute(intent, flow_context, question_text=question_text)
    return FleetInventoryService(user).execute(intent, flow_context, question_text=question_text)
