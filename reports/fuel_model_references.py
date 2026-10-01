"""Source workbook scenarios; never infer a machine variant or an efficiency class."""
import json
import re
from functools import lru_cache
from pathlib import Path


def model_key(value):
    value = re.sub(r"^(?:caterpillar|cat)\s*", "", str(value or "").strip(), flags=re.I)
    return re.sub(r"\s+", "", value).upper()


@lru_cache(maxsize=1)
def reference_catalog():
    return json.loads((Path(__file__).parent / "data" / "fuel_model_references.json").read_text(encoding="utf-8"))


def reference_for_model(model):
    key = model_key(model)
    return next((row for row in reference_catalog()["models"] if model_key(row["model"]) == key), None)
