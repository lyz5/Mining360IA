import json
from functools import lru_cache
from pathlib import Path


SEMANTIC_DICTIONARY_PATH = Path(__file__).resolve().parents[1] / "semantic_model_dictionary.json"


@lru_cache(maxsize=1)
def load_semantic_dictionary() -> dict:
    if not SEMANTIC_DICTIONARY_PATH.exists():
        return {"datasets": {}}
    try:
        payload = json.loads(SEMANTIC_DICTIONARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"datasets": {}}
    return payload if isinstance(payload, dict) else {"datasets": {}}


def get_dataset_semantics(dataset_name: str) -> dict:
    datasets = load_semantic_dictionary().get("datasets", {})
    return datasets.get(dataset_name, {})


def get_measure_semantics(dataset_name: str, metric_key: str) -> dict:
    dataset = get_dataset_semantics(dataset_name)
    return dataset.get("measures", {}).get(metric_key, {})


def get_primary_measure(dataset_name: str, metric_key: str, fallback: str = "") -> str:
    # AI Config is the executable source of truth. The JSON dictionary remains
    # a compatibility fallback for datasets that have no configured mapping.
    try:
        from .models import AIMetricMapping

        configured = (
            AIMetricMapping.objects.filter(
                section__code="performance",
                metric_code=metric_key,
                is_active=True,
            )
            .values_list("powerbi_measure_name", flat=True)
            .first()
        )
        if configured:
            return str(configured).strip().strip("[]")
    except Exception:
        pass
    measure = get_measure_semantics(dataset_name, metric_key)
    return measure.get("primary_measure") or fallback


def get_candidate_measures(dataset_name: str, metric_key: str) -> list[str]:
    measure = get_measure_semantics(dataset_name, metric_key)
    primary = measure.get("primary_measure")
    candidates = list(measure.get("candidate_measures", []))
    if primary and primary not in candidates:
        candidates.insert(0, primary)
    return candidates
