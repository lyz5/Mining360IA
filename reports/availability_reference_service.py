from __future__ import annotations

import re

from django.core.cache import cache

from .data_browsers import BROWSER_DATABASE, quote_identifier, quote_object_name
from .models import DataBrowser, KnowledgeSynonym
from .sqlserver import connect
from .synonym_utils import normalize_synonym_key


REFERENCE_CACHE_SECONDS = 15 * 60

# Product-group labels are display aliases for ModelList[PrimeMovers] codes.
# They are not valid EquipmentList[ParentProductGroup] values.
PRIME_MOVER_ALIASES = {
    normalize_synonym_key(alias): code
    for code, aliases in {
        "EXC": ("EXC", "Excavator", "Excavators"),
        "HMS": ("HMS", "Hydraulic Mining Shovel", "Hydraulic Mining Shovels"),
        "LMT": ("LMT", "Large Mining Truck", "Large Mining Trucks"),
        "LTTT": ("LTTT", "Large Track Type Tractor", "Large Track Type Tractors"),
        "LWL": ("LWL", "Large Wheel Loader", "Large Wheel Loaders"),
        "MG": ("MG", "Motor Grader", "Motor Graders"),
        "OHT": ("OHT", "Off Highway Truck", "Off Highway Trucks", "Off-Highway Truck", "Off-Highway Trucks"),
        "SRD": ("SRD", "Surface Rotary Drill", "Surface Rotary Drills"),
        "WD": ("WD", "Wheel Dozer", "Wheel Dozers"),
    }.items()
    for alias in aliases
}


def _browser_values(browser_name: str, sql_columns: list[str]) -> list[tuple]:
    browser = DataBrowser.objects.filter(name__iexact=browser_name, is_active=True).first()
    if not browser:
        return []
    available = {
        column.sql_name.casefold(): column.sql_name
        for column in browser.columns.all()
    }
    selected = []
    for sql_column in sql_columns:
        actual = available.get(sql_column.casefold())
        if not actual:
            return []
        selected.append(quote_identifier(actual))
    sql = (
        f"SELECT DISTINCT {', '.join(selected)} "
        f"FROM {quote_object_name(browser.table_name, 'Table name')}"
    )
    with connect(database=BROWSER_DATABASE) as connection:
        cursor = connection.cursor()
        cursor.execute(sql)
        return list(cursor.fetchall())


def _family_catalog() -> dict[str, str]:
    cache_key = "availability:reference:families:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    aliases = {
        normalize_synonym_key(synonym): normalized_value
        for synonym, normalized_value in KnowledgeSynonym.objects.filter(
            section__code="performance",
            entity_type="Equipment Family",
            validation_status="Validated",
            is_active=True,
        ).values_list("synonym", "normalized_value")
        if normalize_synonym_key(synonym) and normalized_value
    }
    if aliases:
        cache.set(cache_key, aliases, REFERENCE_CACHE_SECONDS)
        return aliases
    # Browser values are retained as a discovery fallback. They are not used
    # once the semantic-model values have been imported into the Knowledge Base.
    for code, description in _browser_values(
        "Equipment Product Group",
        ["product_group_code", "product_group_description"],
    ):
        code_value = str(code or "").strip().upper()
        canonical = str(description or "").strip()
        if not code_value or code_value == "OTHER" or not canonical:
            continue
        for value in (code_value, canonical):
            normalized = normalize_synonym_key(value)
            if normalized:
                aliases[normalized] = canonical
    cache.set(cache_key, aliases, REFERENCE_CACHE_SECONDS)
    return aliases


def _serial_catalog() -> dict[str, str]:
    cache_key = "availability:reference:serials:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    values = {}
    try:
        for row in _browser_values("Equipment Browser", ["serial_number"]):
            serial = str(row[0] or "").strip().upper()
            if serial:
                values[normalize_synonym_key(serial)] = serial
    except Exception:
        # Power BI remains authoritative for the analytical query. A temporary
        # MiningProd outage must not prevent a safely quoted serial filter.
        return {}
    cache.set(cache_key, values, REFERENCE_CACHE_SECONDS)
    return values


def _contained_alias(normalized_question: str, aliases: dict[str, str]) -> str | None:
    values = _contained_aliases(normalized_question, aliases)
    return values[0] if values else None


def _contained_aliases(normalized_question: str, aliases: dict[str, str]) -> list[str]:
    """Return every non-overlapping alias in source-text order."""
    matches = []
    for alias, canonical in aliases.items():
        for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized_question):
            matches.append((match.start(), match.end(), -len(alias), canonical))

    selected = []
    occupied = []
    for start, end, _negative_length, canonical in sorted(matches, key=lambda item: (item[0], item[2])):
        if any(start < existing_end and end > existing_start for existing_start, existing_end in occupied):
            continue
        occupied.append((start, end))
        if canonical not in selected:
            selected.append(canonical)
    return selected


def _as_values(value) -> list:
    return value if isinstance(value, list) else [value]


def _one_or_many(values: list[str]):
    return values[0] if len(values) == 1 else values


def resolve_availability_references(question: str, filters: dict) -> tuple[dict, list[dict]]:
    resolved = dict(filters or {})
    unresolved = []
    normalized_question = normalize_synonym_key(question)

    families = _family_catalog()
    family_candidate = resolved.get("family")
    if family_candidate:
        product_groups = _contained_aliases(normalized_question, PRIME_MOVER_ALIASES)
        canonical_families = []
        unknown_families = []
        for candidate in _as_values(family_candidate):
            normalized_family = normalize_synonym_key(candidate)
            product_group = PRIME_MOVER_ALIASES.get(normalized_family)
            canonical = families.get(normalized_family)
            if product_group:
                if product_group not in product_groups:
                    product_groups.append(product_group)
            elif canonical and canonical not in canonical_families:
                canonical_families.append(canonical)
            elif not product_group:
                unknown_families.append(candidate)

        if product_groups and not canonical_families and not unknown_families:
            resolved.pop("family", None)
            resolved["product_group"] = _one_or_many(product_groups)
        elif canonical_families and not product_groups and not unknown_families:
            resolved["family"] = _one_or_many(canonical_families)
        else:
            unresolved.extend(
                {"filter_code": "family", "value": value}
                for value in _as_values(family_candidate)
            )
            resolved.pop("family", None)
    else:
        product_groups = _contained_aliases(normalized_question, PRIME_MOVER_ALIASES)
        canonical_families = _contained_aliases(normalized_question, families) if families else []
        if product_groups:
            resolved["product_group"] = _one_or_many(product_groups)
        elif canonical_families:
            resolved["family"] = _one_or_many(canonical_families)

    serials = _serial_catalog()
    serial_candidate = resolved.get("serial_number")
    if serial_candidate:
        canonical_serials = []
        for candidate in _as_values(serial_candidate):
            if serials:
                canonical = serials.get(normalize_synonym_key(candidate))
                if canonical and canonical not in canonical_serials:
                    canonical_serials.append(canonical)
                elif not canonical:
                    unresolved.append({"filter_code": "serial_number", "value": candidate})
            else:
                canonical = str(candidate).strip().upper()
                if canonical not in canonical_serials:
                    canonical_serials.append(canonical)
        if canonical_serials:
            resolved["serial_number"] = _one_or_many(canonical_serials)
        else:
            resolved.pop("serial_number", None)

    return resolved, unresolved
