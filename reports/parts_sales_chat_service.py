from __future__ import annotations

from datetime import date
import re
import unicodedata

from .business_performance_service import BusinessPerformanceService


PARTS_SALES_METRIC = "parts_sales_ytd"
PARTS_SALES_MEASURE = "CA Facture EU"


def _normalized(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _number(row: dict, preferred_label: str) -> float:
    for key, value in row.items():
        normalized_key = _normalized(key)
        if normalized_key not in {
            _normalized(preferred_label),
            _normalized(PARTS_SALES_MEASURE),
            "revenue eur",
        }:
            continue
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _format_euro(value: float, language: str) -> str:
    if abs(value) >= 1_000_000:
        formatted = f"{value / 1_000_000:,.1f} M€"
    elif abs(value) >= 1_000:
        formatted = f"{value / 1_000:,.1f} k€"
    else:
        formatted = f"{value:,.2f} €"
    if language == "fr":
        formatted = formatted.replace(",", "X").replace(".", ",").replace("X", " ")
    return formatted


def _language(question: str) -> str:
    words = set(_normalized(question).split())
    return "fr" if words.intersection({"combien", "quel", "quelle", "ventes", "pieces", "client"}) else "en"


def _year(intent: dict) -> str:
    period = str((intent.get("filters") or {}).get("period") or "").strip()
    match = re.search(r"\b(20\d{2})\b", period)
    return match.group(1) if match else str(date.today().year)


def _matching_rows(rows: list[dict], label: str, requested_value: str) -> list[dict]:
    needle = _normalized(requested_value)
    if not needle:
        return rows
    exact = [row for row in rows if _normalized(row.get(label)) == needle]
    if exact:
        return exact
    return [row for row in rows if needle in _normalized(row.get(label))]


def _resolved_row_label(rows: list[dict], *candidates: str) -> str:
    normalized_candidates = {_normalized(value) for value in candidates if value}
    for row in rows:
        for key in row:
            if _normalized(key) in normalized_candidates:
                return key
    return next((value for value in candidates if value), "")


def execute_parts_sales_intent(intent: dict, *, user=None, question_text: str = "") -> dict:
    """Resolve official Parts YTD sales by customer or analytical territory."""
    service = BusinessPerformanceService(user)
    filters = intent.get("filters") or {}
    requested_customer = str(filters.get("customer") or "").strip()
    requested_site = str(filters.get("minesite") or "").strip()
    raw_group_by = intent.get("group_by") or []
    group_by = str(raw_group_by[0] if isinstance(raw_group_by, list) and raw_group_by else raw_group_by).strip()

    if requested_site or group_by == "minesite":
        dimension = "territory"
        requested_value = requested_site
    elif requested_customer or group_by == "customer":
        dimension = "customer"
        requested_value = requested_customer
    else:
        dimension = None
        requested_value = ""

    query = service.sales_domain_query(
        "parts",
        {"year": _year(intent)},
        dimension=dimension,
        currency="EURO",
        limit=2000,
    )
    measure_label = service.mapping("global_revenue_eur").display_name
    dimension_mapping = service.mapping(dimension) if dimension else None
    dimension_label = _resolved_row_label(
        query.rows,
        getattr(dimension_mapping, "display_name", ""),
        getattr(dimension_mapping, "object_name", ""),
    ) if dimension else ""
    selected_rows = _matching_rows(query.rows, dimension_label, requested_value) if dimension else query.rows
    if requested_site and not selected_rows:
        # Some MineSites are represented by the customer name rather than the
        # analytical territory in GlobalCA (for example Fekola).
        customer_query = service.sales_domain_query(
            "parts",
            {"year": _year(intent)},
            dimension="customer",
            currency="EURO",
            limit=2000,
        )
        customer_mapping = service.mapping("customer")
        customer_label = _resolved_row_label(
            customer_query.rows,
            customer_mapping.display_name,
            customer_mapping.object_name,
        )
        customer_rows = _matching_rows(customer_query.rows, customer_label, requested_site)
        if customer_rows:
            query = customer_query
            dimension = "customer"
            dimension_label = customer_label
            selected_rows = customer_rows
    value = sum(_number(row, measure_label) for row in selected_rows)
    language = _language(question_text)

    if requested_value:
        subject = requested_value
        if selected_rows and selected_rows[0].get(dimension_label):
            subject = str(selected_rows[0][dimension_label])
        if language == "fr":
            answer = f"Le chiffre d'affaires Parts YTD de {subject} est de {_format_euro(value, language)}."
        else:
            answer = f"YTD Parts Sales for {subject} are {_format_euro(value, language)}."
        if not selected_rows:
            answer = (
                f"Aucune vente Parts YTD n'a été trouvée pour {requested_value}."
                if language == "fr"
                else f"No YTD Parts Sales were found for {requested_value}."
            )
    elif dimension:
        top_rows = sorted(query.rows, key=lambda row: _number(row, measure_label), reverse=True)[:10]
        lines = [
            f"{row.get(dimension_label) or 'Unknown'}: {_format_euro(_number(row, measure_label), language)}"
            for row in top_rows
        ]
        if language == "fr":
            heading = "Parts Sales YTD par client" if dimension == "customer" else "Parts Sales YTD par MineSite"
            answer = heading + (" :\n" + "\n".join(lines) if lines else ": aucune donnée disponible.")
        else:
            heading = "YTD Parts Sales by customer" if dimension == "customer" else "YTD Parts Sales by MineSite"
            answer = heading + (":\n" + "\n".join(lines) if lines else ": no data available.")
    else:
        answer = (
            f"Le chiffre d'affaires Parts YTD est de {_format_euro(value, language)}."
            if language == "fr"
            else f"YTD Parts Sales are {_format_euro(value, language)}."
        )

    return {
        "answer": answer,
        "rows": selected_rows if requested_value else query.rows,
        "dax": query.dax,
        "metric": PARTS_SALES_METRIC,
        "measure": PARTS_SALES_MEASURE,
        "dimension": dimension,
        "value": value,
        "year": _year(intent),
        "cached": query.cached,
    }
