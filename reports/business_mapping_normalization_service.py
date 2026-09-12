from __future__ import annotations

import hashlib
import json
import re
import unicodedata


NORMALIZATION_VERSION = "1.0"


def normalize_business_name(value: object) -> str:
    """Return a comparison value without changing the source value."""
    text = unicodedata.normalize("NFKD", str(value or "").strip()).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_code(prefix: str, value: object) -> str:
    normalized = normalize_business_name(value)
    readable = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:80] or "unknown"
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{readable}-{digest}".upper()


def payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
