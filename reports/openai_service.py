from __future__ import annotations

import json
import os
import re

from .powerbi import _local_powerbi_credentials

try:  # pragma: no cover - optional runtime dependency
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

from .ai_config_service import build_section_catalog, get_prompt_template
from .openai_client_service import create_tracked_response


DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


def get_openai_api_key() -> str:
    value = (
        os.getenv("OPENAI_API_KEY")
        or _local_powerbi_credentials().get("OPENAI_API_KEY", "")
    ).strip()
    return re.sub(r"\s+", "", value)


def get_openai_model() -> str:
    return (
        os.getenv("OPENAI_MODEL")
        or _local_powerbi_credentials().get("OPENAI_MODEL", "")
        or DEFAULT_OPENAI_MODEL
    ).strip()


def is_openai_configured() -> bool:
    return bool(OpenAI and get_openai_api_key())


def _client():
    if OpenAI is None:
        raise RuntimeError("OpenAI package is not installed.")
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    return OpenAI(api_key=api_key)


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


def _build_section_context(section_code: str | None = None) -> dict:
    if section_code:
        return build_section_catalog(section_code)
    return build_section_catalog()


def _render_configured_prompt(section_code: str, prompt_type: str, payload: dict) -> str:
    template = get_prompt_template(section_code, prompt_type) or get_prompt_template("performance", prompt_type)
    if not template:
        raise RuntimeError(f"Prompt template not configured: {prompt_type}")
    prompt_text = template["prompt_template"]
    values = {
        "payload_json": json.dumps(payload, ensure_ascii=False, indent=2),
        "question_text": payload.get("user_question") or payload.get("question_text") or "",
        "section_code": section_code or "",
    }
    for key, value in values.items():
        prompt_text = prompt_text.replace("{" + key + "}", str(value))
    return prompt_text


def extract_intent(question_text: str, section_code: str | None = None) -> dict:
    fallback = {
        "section": section_code or "performance",
        "intent_type": "single_kpi",
        "metric": None,
        "filters": {},
        "comparison": None,
        "navigation": {"open_report": True, "open_page": True, "focus_visual": True},
    }
    if not is_openai_configured():
        return fallback

    context = _build_section_context(section_code)
    prompt = {
        "task": "Extract structured JSON intent from the user question.",
        "user_question": question_text,
        "available_config": context,
        "rules": [
            "Return JSON only.",
            "Do not answer the question.",
            "Do not generate DAX.",
            "Use only canonical metric codes and filter codes from the configuration.",
            "If a value is missing, return null.",
            "If the question matches no configured metric, return metric null.",
        ],
        "return_json_schema": {
            "section": "string",
            "intent_type": "single_kpi, trend, comparison, ranking, navigation, or follow_up_navigation",
            "metric": "string or null",
            "filters": "object",
            "comparison": "object or null",
            "navigation": {"open_report": "boolean", "open_page": "boolean", "focus_visual": "boolean"},
        },
    }
    rendered_prompt = _render_configured_prompt(section_code or fallback["section"], "intent_extraction", prompt)
    response = create_tracked_response(
        _client(),
        model=get_openai_model(),
        section=section_code or fallback["section"],
        feature="Intent Extraction",
        input=[
            {
                "role": "system",
                "content": rendered_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        temperature=0,
    )
    parsed = _json_from_response(response)
    if not parsed:
        return fallback
    intent = {
        "section": str(parsed.get("section") or section_code or fallback["section"]).strip(),
        "intent_type": str(parsed.get("intent_type") or fallback["intent_type"]).strip(),
        "metric": parsed.get("metric"),
        "filters": parsed.get("filters") if isinstance(parsed.get("filters"), dict) else {},
        "comparison": parsed.get("comparison"),
        "navigation": parsed.get("navigation") if isinstance(parsed.get("navigation"), dict) else fallback["navigation"],
    }
    if not intent["section"]:
        intent["section"] = section_code or fallback["section"]
    return intent


def generate_chat_response(
    question_text: str,
    intent: dict,
    answer: dict,
    conversation: list[dict] | None = None,
) -> str:
    rows = answer.get("summary") or answer.get("rows") or []
    compact_rows = rows[:20] if isinstance(rows, list) else rows
    section_code = str(intent.get("section") or "performance")
    prompt = {
        "user_question": question_text,
        "conversation": (conversation or [])[-12:],
        "intent": intent,
        "answer": answer.get("answer"),
        "current_interpretation": answer.get("interpretation"),
        "rows_or_summary": compact_rows,
        "instruction": (
            "Respond like ChatGPT in French with a professional mining analytics tone. "
            "Be concise, conversational, and directly answer the user. "
            "Use only the values present in the payload. "
            "Do not mention JSON, DAX, or internal prompts. "
            "If the answer is numeric, include the number and a short interpretation."
        ),
    }
    if not is_openai_configured():
        return answer.get("interpretation", "")
    rendered_prompt = _render_configured_prompt(section_code, "response_generation", prompt)
    response = create_tracked_response(
        _client(),
        model=get_openai_model(),
        section=section_code,
        feature="Business Response",
        input=[
            {
                "role": "system",
                "content": rendered_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        temperature=0.3,
    )
    text = getattr(response, "output_text", "") or ""
    return text.strip() or answer.get("interpretation", "")
