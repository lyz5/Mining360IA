from __future__ import annotations

from datetime import date
import json
import re
import unicodedata

from django.core.serializers.json import DjangoJSONEncoder

from reports.ai_feature_rollout import feature_enabled
from reports.business_command_center_service import (
    BusinessCommandCenterInputError,
    BusinessCommandCenterService,
)
from reports.business_review_access_service import has_business_review_permission


REVENUE_TERMS = re.compile(
    r"\b(revenue|revenu|turnover|chiffre\s+d['’]?affaires?|ca(?:\s+(?:mining|machine|parts|service|rental))?|"
    r"ventes?|sales?|vendu(?:e?s)?|sold|business\s+command\s+center|clients?\s+(?:principaux|top)|top\s+(?:customers?|clients?|countries|pays|key\s+accounts?))\b",
    re.IGNORECASE,
)


def _normalized(value: str) -> str:
    folded = "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _business_line(question: str) -> str:
    text = _normalized(question)
    for code, terms in {
        "machine": ("machine", "prime"),
        "parts": ("parts", "piece", "pieces"),
        "service": ("service",),
        "rental": ("rental", "location"),
        "unclassified": ("unclassified", "non classe", "non classifie"),
    }.items():
        if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms):
            return code
    return "all_business"


def _period_params(question: str, latest_year: int) -> dict:
    text = _normalized(question)
    if "mois courant" in text or "current month" in text:
        return {"period": "current_month"}
    if "annee derniere" in text or "last year" in text:
        return {"period": "last_year"}
    years = [int(value) for value in re.findall(r"\b(20\d{2})\b", question)]
    if years:
        year = years[0]
        if year == latest_year:
            return {"period": "ytd"}
        return {
            "period": "custom",
            "start_date": date(year, 1, 1).isoformat(),
            "end_date": date(year, 12, 31).isoformat(),
            "comparison": "same_period_last_year",
        }
    return {"period": "ytd"}


def _access_profile(user) -> dict:
    permitted = lambda codename: has_business_review_permission(user, codename)
    return {
        "command_center": permitted("view_business_command_center"),
        "financials": permitted("view_business_review_financials"),
        "ai": permitted("view_business_command_center_ai"),
        "business_lines": permitted("view_business_line_revenue"),
        "customers": permitted("view_customer_revenue"),
        "countries": permitted("view_country_revenue"),
        "key_accounts": permitted("view_key_account_revenue"),
        "confidence": permitted("view_business_data_confidence"),
    }


def revenue_analysis_from_question(question: str, *, user) -> dict | None:
    result = _revenue_analysis(question, user=user)
    if result is not None:
        result["language"] = "fr" if re.search(
            r"\b(quel|quelle|quels|quelles|combien|ventes?|vendu\w*|chiffre|pieces?|donne|montre|pour|annee)\b",
            _normalized(question),
        ) else "en"
    return result


def _revenue_analysis(question: str, *, user) -> dict | None:
    if not REVENUE_TERMS.search(question):
        return None
    # Revenue is a monetary measure, never a count of parts or machines sold.
    if re.search(
        r"\b(combien\s+(?:de|d)|nombre\s+(?:de|d)|how\s+many|quantity|quantite|units?)\b",
        _normalized(question),
    ):
        return None
    access = _access_profile(user)
    if not feature_enabled("ENABLE_BUSINESS_COMMAND_CENTER", user) or not all(
        access[key] for key in ("command_center", "financials", "ai")
    ):
        return {"kind": "revenue_access_restricted"}
    try:
        initial_service = BusinessCommandCenterService(user, {"period": "ytd"})
        latest_date = initial_service.latest_business_date()
    except BusinessCommandCenterInputError as exc:
        return {"kind": "revenue_unavailable", "message": str(exc)}
    latest_year = latest_date.year
    params = {
        **_period_params(question, latest_year),
        "comparison": "same_period_last_year",
        "business_line": _business_line(question),
    }
    allowed_filter_dimensions = {
        "customer_group_ids": access["customers"],
        "country_ids": access["countries"],
        "key_account_ids": access["key_accounts"],
    }
    mentions = initial_service.resolve_filter_mentions(question)
    allowed_ambiguities = {
        parameter: candidates
        for parameter, candidates in mentions["ambiguities"].items()
        if allowed_filter_dimensions[parameter]
    }
    if allowed_ambiguities:
        return {
            "kind": "revenue_scope_ambiguous",
            "dimensions": allowed_ambiguities,
            "candidates": sorted({
                item.get("name") for candidates in allowed_ambiguities.values()
                for item in candidates if item.get("name")
            }),
        }
    for parameter, value in mentions["filters"].items():
        if allowed_filter_dimensions[parameter]:
            params[parameter] = value
    try:
        payload = BusinessCommandCenterService(user, params).bootstrap()
    except BusinessCommandCenterInputError as exc:
        return {"kind": "revenue_unavailable", "message": str(exc)}
    result = {
        "kind": "revenue_summary",
        "request": {
            "question": question,
            "resolved_scope": {key:value for key,value in mentions.get("scope", {}).items() if allowed_filter_dimensions[key]},
            "resolved_filters": {
                key: value for key, value in params.items()
                if key in {"customer_group_ids", "country_ids", "key_account_ids"}
            },
        },
        "context": payload["context"],
        "freshness": payload["freshness"],
        "hero": payload["hero"],
        "trend": payload["trend"],
        "reconciliation": payload["reconciliation"],
        "source_table": "bm_revenue_source_snapshot",
        "source_service": "BusinessCommandCenterService",
        "definition": "Actual invoiced Mining Revenue; division MI; currency EUR; governed business date.",
    }
    if access["business_lines"]:
        result["business_lines"] = payload["business_lines"]
        result["changes"] = payload["changes"]
        result["attention_items"] = payload["attention_items"]
    if access["customers"]:
        result["top_customers"] = payload["dimensions"]["customers"][:10]
        result["concentration"] = payload["concentration"]
    if access["countries"]:
        result["top_countries"] = payload["dimensions"]["countries"][:10]
    if access["key_accounts"]:
        result["top_key_accounts"] = payload["dimensions"]["key_accounts"][:10]
    if access["confidence"]:
        result["confidence"] = payload["confidence"]
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))
