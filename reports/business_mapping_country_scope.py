from __future__ import annotations

from collections import OrderedDict


# Governed commercial scopes, distinct from the customer's legal/origin country.
NEEMBA_OPERATING_COUNTRIES = OrderedDict([
    ("SN", "Senegal"),
    ("CI", "Cote d'Ivoire"),
    ("GN", "Guinea"),
    ("ML", "Mali"),
    ("BF", "Burkina Faso"),
    ("NE", "Niger"),
    ("BJ", "Benin"),
    ("TG", "Togo"),
    ("MR", "Mauritania"),
    ("FR", "France"),
    ("CM", "Cameroon"),
    ("GW", "Guinea-Bissau"),
    ("MU", "Mauritius"),
])


# Company codes observed in the governed Mining revenue source. Regional/group
# companies remain unassigned until a business rule is approved.
NEEMBA_COMPANY_OPERATING_COUNTRY = {
    "22": "MU", "23": "MU", "24": "MU", "25": "GN", "27": "FR", "29": "FR", "30": "BJ",
    "31": "BF", "32": "CI", "33": "GN", "34": "GN", "35": "GW", "36": "ML", "37": "MR",
    "38": "MU", "39": "NE", "40": "SN", "41": "TG", "42": "MU", "43": "CM", "44": "CI",
    "45": "BF", "46": "SN", "47": "ML", "48": "FR", "49": "GN", "61": "BF", "62": "BF", "66": "ML",
}


def normalize_operating_country(value):
    code = str(value or "").strip().upper()
    return code if code in NEEMBA_OPERATING_COUNTRIES else ""


def operating_country_for_company(company_code, branch_code=""):
    del branch_code  # Reserved for future governed branch-level exceptions.
    return NEEMBA_COMPANY_OPERATING_COUNTRY.get(str(company_code or "").strip().upper(), "")


def operating_country_options():
    return [{"code": code, "label": label} for code, label in NEEMBA_OPERATING_COUNTRIES.items()]
