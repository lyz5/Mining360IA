from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date


MONTHS = {
    "january": 1, "janvier": 1, "jan": 1,
    "february": 2, "fevrier": 2, "feb": 2,
    "march": 3, "mars": 3, "mar": 3,
    "april": 4, "avril": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "juin": 6, "jun": 6,
    "july": 7, "juillet": 7, "jul": 7,
    "august": 8, "aout": 8, "aug": 8,
    "september": 9, "septembre": 9, "sep": 9, "sept": 9,
    "october": 10, "octobre": 10, "oct": 10,
    "november": 11, "novembre": 11, "nov": 11,
    "december": 12, "decembre": 12, "dec": 12,
}
MONTH_NAMES_FR = (
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
)
MONTH_NAMES_EN = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _month_payload(year: int, month: int) -> dict:
    last_day = calendar.monthrange(year, month)[1]
    return {
        "type": "month",
        "value": f"{year:04d}-{month:02d}",
        "start_date": date(year, month, 1).isoformat(),
        "end_date": date(year, month, last_day).isoformat(),
        "display_value_fr": f"{MONTH_NAMES_FR[month]} {year}",
        "display_value_en": f"{MONTH_NAMES_EN[month]} {year}",
    }


def resolve_temporal_expression(
    expression: str,
    *,
    language: str = "en",
    reference_date: date | None = None,
) -> dict | None:
    text = _normalize(expression)
    if not text:
        return None
    today = reference_date or date.today()

    month_match = re.search(
        r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+(20\d{2}))?",
        text,
    )
    if month_match:
        year = int(month_match.group(2) or today.year)
        return _month_payload(year, MONTHS[month_match.group(1)])

    canonical_match = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", text)
    if canonical_match:
        return _month_payload(int(canonical_match.group(1)), int(canonical_match.group(2)))

    if any(marker in text for marker in ("last month", "previous month", "mois dernier", "mois precedent")):
        month = today.month - 1 or 12
        year = today.year - 1 if today.month == 1 else today.year
        return _month_payload(year, month)
    if any(marker in text for marker in ("this month", "current month", "ce mois", "mois en cours")):
        return _month_payload(today.year, today.month)
    if any(marker in text for marker in ("year to date", " ytd", "annee en cours", "cette annee")):
        return {
            "type": "year_to_date",
            "value": f"YTD {today.year}",
            "start_date": date(today.year, 1, 1).isoformat(),
            "end_date": today.isoformat(),
            "display_value_fr": f"Année en cours {today.year}",
            "display_value_en": f"Year to date {today.year}",
        }
    if any(marker in text for marker in ("last 12 months", "12 derniers mois")):
        return {
            "type": "rolling_months",
            "value": "last 12 months",
            "months": 12,
            "display_value_fr": "12 derniers mois",
            "display_value_en": "Last 12 months",
        }
    return None


class TemporalExpressionResolutionService:
    @staticmethod
    def resolve(expression, language="en", reference_date=None):
        return resolve_temporal_expression(
            expression,
            language=language,
            reference_date=reference_date,
        )
