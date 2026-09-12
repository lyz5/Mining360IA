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


def normalize_period_value(value, *, reference_date: date | None = None):
    """Return the canonical period value consumed by governed DAX templates."""
    if isinstance(value, dict):
        value = value.get("value")
    text = _normalize(value)
    if not text:
        return value
    today = reference_date or date.today()
    ytd_match = re.fullmatch(
        r"(?:ytd|year to date|annee en cours|cette annee)(?: (20\d{2}))?",
        text,
    )
    if ytd_match and (
        not ytd_match.group(1) or int(ytd_match.group(1)) == today.year
    ):
        return "year to date"
    if text in {"mtd", "month to date", "mois en cours jusqu a ce jour"}:
        return "month to date"
    rolling_match = re.fullmatch(
        r"(?:last|rolling|trailing) (\d{1,3}) months?"
        r"|(\d{1,3}) (?:derniers? mois|mois glissants?)",
        text,
    )
    if rolling_match:
        months = int(rolling_match.group(1) or rolling_match.group(2))
        if 1 <= months <= 120:
            return f"last {months} months"
    return value


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

    month_pattern = "|".join(sorted(MONTHS, key=len, reverse=True))
    range_match = re.search(
        rf"\b(?:from|between|de|du)?\s*({month_pattern})(?:\s+(20\d{{2}}))?\s+"
        rf"(?:to|through|until|and|a|au|jusqu a)\s+"
        rf"({month_pattern})(?:\s+(20\d{{2}}))?\b",
        text,
    )
    if range_match:
        start_month = MONTHS[range_match.group(1)]
        end_month = MONTHS[range_match.group(3)]
        start_year_text = range_match.group(2)
        end_year_text = range_match.group(4)
        start_year = int(start_year_text or end_year_text or today.year)
        end_year = int(end_year_text or start_year_text or today.year)
        if not start_year_text and not end_year_text and end_month < start_month:
            end_year += 1
        if (end_year, end_month) >= (start_year, start_month):
            end_day = calendar.monthrange(end_year, end_month)[1]
            if language == "fr":
                display = (
                    f"{MONTH_NAMES_FR[start_month]} à {MONTH_NAMES_FR[end_month]} {end_year}"
                    if start_year == end_year else
                    f"{MONTH_NAMES_FR[start_month]} {start_year} à {MONTH_NAMES_FR[end_month]} {end_year}"
                )
            else:
                display = (
                    f"{MONTH_NAMES_EN[start_month]} to {MONTH_NAMES_EN[end_month]} {end_year}"
                    if start_year == end_year else
                    f"{MONTH_NAMES_EN[start_month]} {start_year} to {MONTH_NAMES_EN[end_month]} {end_year}"
                )
            return {
                "type": "month_range",
                "value": f"{start_year:04d}-{start_month:02d}/{end_year:04d}-{end_month:02d}",
                "start_date": date(start_year, start_month, 1).isoformat(),
                "end_date": date(end_year, end_month, end_day).isoformat(),
                "display_value_fr": display if language == "fr" else (
                    f"{MONTH_NAMES_FR[start_month]} à {MONTH_NAMES_FR[end_month]} {end_year}"
                    if start_year == end_year else
                    f"{MONTH_NAMES_FR[start_month]} {start_year} à {MONTH_NAMES_FR[end_month]} {end_year}"
                ),
                "display_value_en": display if language != "fr" else (
                    f"{MONTH_NAMES_EN[start_month]} to {MONTH_NAMES_EN[end_month]} {end_year}"
                    if start_year == end_year else
                    f"{MONTH_NAMES_EN[start_month]} {start_year} to {MONTH_NAMES_EN[end_month]} {end_year}"
                ),
            }

    month_match = re.search(
        r"\b(" + month_pattern + r")\b(?:\s+(20\d{2}))?",
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
    if re.search(r"\b(?:year to date|ytd|annee en cours|cette annee)\b", text):
        return {
            "type": "year_to_date",
            "value": f"YTD {today.year}",
            "start_date": date(today.year, 1, 1).isoformat(),
            "end_date": today.isoformat(),
            "display_value_fr": f"Année en cours {today.year}",
            "display_value_en": f"Year to date {today.year}",
        }
    rolling_match = re.search(
        r"\b(?:last|rolling|trailing) (\d{1,3}) months?\b"
        r"|\b(\d{1,3}) (?:derniers? mois|mois glissants?)\b",
        text,
    )
    if rolling_match:
        months = int(rolling_match.group(1) or rolling_match.group(2))
        if not 1 <= months <= 120:
            return None
        return {
            "type": "rolling_months",
            "value": f"last {months} months",
            "months": months,
            "display_value_fr": f"{months} derniers mois",
            "display_value_en": f"Last {months} months",
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
