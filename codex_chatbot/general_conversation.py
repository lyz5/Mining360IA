from __future__ import annotations

import re


BUSINESS_DATA_TERMS = re.compile(
    r"\b(availability|disponibilit[eé]|revenue|revenu|chiffre\s+d['’]?affaires?|"
    r"fleet|flotte|mine\s*site|sites?\s+miniers?|[eé]quipements?|serial|num[eé]ro\s+de\s+s[eé]rie|"
    r"machines?|machine\s+sold|vendues?|pi[eè]ces?|parts?|"
    r"commande|order|facture|invoice|backorder|delivery|livraison|ytd|"
    r"key\s+account|compte\s+canonique|mapping)\b",
    re.IGNORECASE,
)


def looks_like_business_data_request(question: str) -> bool:
    """Keep unresolved Mining 360 data requests out of free conversation mode."""
    return bool(BUSINESS_DATA_TERMS.search(question or ""))
