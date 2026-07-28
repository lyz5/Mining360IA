import json
import os
import re

from .powerbi import _local_powerbi_credentials

from .ai_provider_gateway_service import ai_gateway
from .openai_service import is_openai_configured as gateway_is_configured


DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


def get_openai_api_key() -> str:
    try:
        from .system_configuration_service import integration_value

        configured_key = integration_value("OpenAI", "api_key", "", secret=True)
    except Exception:
        configured_key = ""
    value = (
        os.getenv("OPENAI_API_KEY")
        or configured_key
        or _local_powerbi_credentials().get("OPENAI_API_KEY", "")
    ).strip()
    return re.sub(r"\s+", "", value)


def get_openai_model() -> str:
    try:
        from .system_configuration_service import integration_value

        configured_model = integration_value("OpenAI", "default_model", "")
    except Exception:
        configured_model = ""
    return (
        os.getenv("OPENAI_MODEL")
        or configured_model
        or _local_powerbi_credentials().get("OPENAI_MODEL", "")
        or DEFAULT_OPENAI_MODEL
    ).strip()


def is_openai_configured() -> bool:
    return gateway_is_configured()


def _json_from_response(response) -> dict:
    text = getattr(response, "output_text", "") or ""
    if not text:
        try:
            text = response.output[0].content[0].text
        except Exception:
            text = ""
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    return {}


def parse_semantic_question_with_openai(question: str, fallback: dict) -> dict:
    if not is_openai_configured():
        return fallback
    prompt = {
        "task": "Extract semantic Power BI query parameters from a user question.",
        "user_question": question,
        "supported_dataset": "FPR Global DB + RLS",
        "supported_metric": "availability",
        "known_sites_examples": ["Fekola", "Siguiri", "Sangaredi/CBG", "Seguela", "Tongon"],
        "known_model_examples": ["6015", "6020", "6030", "6040", "6050", "777", "777 WT", "785", "789", "D10", "D9"],
        "fallback": fallback,
        "return_json_schema": {
            "dataset": "string",
            "site": "string",
            "model": "string or empty",
            "year": "integer",
            "month": "integer",
            "mode": "single or matrix",
            "months": "integer"
        },
        "rules": [
            "Return JSON only.",
            "Use mode=matrix when the user asks for all models or last 12 months by model.",
            "Use mode=single when a specific model and month are provided.",
            "Preserve exact model codes like 777 WT, 6020, D10.",
            "If a value is missing, keep the fallback value."
        ],
    }
    response = ai_gateway.generate_structured_output(
        use_case="semantic_question_parsing",
        messages=[
            {
                "role": "system",
                "content": "You convert mining analytics questions into strict JSON parameters. Return JSON only.",
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        output_schema={
            "type": "object",
            "properties": {
                "dataset": {"type": "string"},
                "site": {"type": "string"},
                "model": {"type": "string"},
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "mode": {"type": "string", "enum": ["single", "matrix"]},
                "months": {"type": "integer"},
            },
            "required": ["dataset", "site", "model", "year", "month", "mode", "months"],
        },
        options={"temperature": 0},
    )
    parsed = response.structured_output or {}
    if not parsed:
        return fallback
    merged = dict(fallback)
    for key in ("dataset", "site", "model", "mode"):
        if parsed.get(key) is not None:
            merged[key] = str(parsed.get(key)).strip()
    for key in ("year", "month", "months"):
        try:
            merged[key] = int(parsed.get(key))
        except Exception:
            pass
    if merged.get("mode") not in {"single", "matrix"}:
        merged["mode"] = fallback.get("mode", "single")
    return merged


def interpret_semantic_answer_with_openai(question: str, semantic_request: dict, answer: dict) -> str:
    if not is_openai_configured():
        return answer.get("interpretation", "")
    rows = answer.get("summary") or answer.get("rows") or []
    compact_rows = rows[:20] if isinstance(rows, list) else rows
    prompt = {
        "user_question": question,
        "semantic_request": {
            "dataset": semantic_request.get("dataset"),
            "measure": semantic_request.get("measure"),
            "filters": semantic_request.get("filters"),
            "period": semantic_request.get("period"),
        },
        "answer": answer.get("answer"),
        "current_interpretation": answer.get("interpretation"),
        "rows_or_summary": compact_rows,
        "instruction": (
            "Write a concise French business interpretation for a mining operations user. "
            "Do not invent numbers. Mention only values present in the payload. "
            "Highlight trend, weak points, and next analysis action."
        ),
    }
    response = ai_gateway.generate_text(
        use_case="machine_performance_response",
        messages=[
            {
                "role": "system",
                "content": "You are a mining fleet performance analyst. Explain Power BI semantic model results in French.",
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        options={"temperature": 0.2},
    )
    text = response.content
    return text.strip() or answer.get("interpretation", "")


def chat_semantic_response_with_openai(
    question: str,
    semantic_request: dict,
    answer: dict,
    conversation: list[dict] | None = None,
) -> str:
    fallback = answer.get("interpretation", "")
    if not is_openai_configured():
        return fallback

    history = []
    for item in (conversation or [])[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        history.append({"role": role, "content": content})

    prompt = {
        "user_question": question,
        "conversation": history,
        "semantic_request": {
            "dataset": semantic_request.get("dataset"),
            "measure": semantic_request.get("measure"),
            "filters": semantic_request.get("filters"),
            "period": semantic_request.get("period"),
            "rls_role": semantic_request.get("rls_role"),
        },
        "answer": answer.get("answer"),
        "current_interpretation": answer.get("interpretation"),
        "rows_or_summary": (answer.get("summary") or answer.get("rows") or [])[:20],
        "instruction": (
            "Respond like ChatGPT in French with a professional mining analytics tone. "
            "Be concise, conversational, and directly answer the user. "
            "Use only the values present in the payload. "
            "If the answer is numeric, include the number and a short interpretation. "
            "Do not mention internal JSON or prompts."
        ),
    }
    response = ai_gateway.generate_text(
        use_case="machine_performance_response",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Mining360 AI, a conversational assistant for mining operations. "
                    "Answer naturally in French like ChatGPT."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        options={"temperature": 0.3},
    )
    text = response.content
    return text.strip() or fallback
