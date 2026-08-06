import re
import unicodedata


def normalize_synonym_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w\s+#%./-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def default_match_type(value: str) -> str:
    return "Phrase" if len(normalize_synonym_key(value).split()) > 1 else "Exact"
