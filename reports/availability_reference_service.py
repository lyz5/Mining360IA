from __future__ import annotations

import re

from django.core.cache import cache

from .data_browsers import BROWSER_DATABASE, quote_identifier, quote_object_name
from .models import DataBrowser, KnowledgeSynonym
from .sqlserver import connect
from .synonym_utils import normalize_synonym_key


REFERENCE_CACHE_SECONDS = 15 * 60


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
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized_question):
            return aliases[alias]
    return None


def resolve_availability_references(question: str, filters: dict) -> tuple[dict, list[dict]]:
    resolved = dict(filters or {})
    unresolved = []
    normalized_question = normalize_synonym_key(question)

    families = _family_catalog()
    family_candidate = resolved.get("family")
    if family_candidate:
        canonical = families.get(normalize_synonym_key(family_candidate))
        if canonical:
            resolved["family"] = canonical
        else:
            unresolved.append({"filter_code": "family", "value": family_candidate})
            resolved.pop("family", None)
    elif families:
        canonical = _contained_alias(normalized_question, families)
        if canonical:
            resolved["family"] = canonical

    serials = _serial_catalog()
    serial_candidate = resolved.get("serial_number")
    if serial_candidate:
        if serials:
            canonical = serials.get(normalize_synonym_key(serial_candidate))
            if canonical:
                resolved["serial_number"] = canonical
            else:
                unresolved.append({"filter_code": "serial_number", "value": serial_candidate})
                resolved.pop("serial_number", None)
        else:
            resolved["serial_number"] = str(serial_candidate).strip().upper()

    return resolved, unresolved
