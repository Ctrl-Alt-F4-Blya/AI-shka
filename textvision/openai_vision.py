from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .config import APP_ROOT

KEY_FILE = APP_ROOT / "OPENAI_API_KEY.txt"
SETTINGS_FILE = APP_ROOT / "OPENAI_API_SETTINGS.json"

DEFAULT_SETTINGS = {
    "model": "gpt-4o-mini",
    "fallback_models": ["gpt-4.1-mini"],
    "timeout_seconds": 90,
    "detail": "high",
    "max_output_tokens": 900,
}


def load_key() -> str:
    env_key = os.environ.get("OPENAI_API_KEY", "").strip().strip('"').strip("'")
    if env_key:
        return env_key
    if not KEY_FILE.exists():
        return ""
    raw = KEY_FILE.read_text(encoding="utf-8", errors="ignore").replace("\ufeff", "")
    for line in raw.splitlines():
        value = line.strip().strip('"').strip("'")
        if not value or value.startswith("#") or value.upper().startswith("PASTE"):
            continue
        return value
    return ""


def load_settings() -> Dict[str, object]:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            custom = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(custom, dict):
                settings.update(custom)
        except Exception:
            pass
    return settings


def is_ready() -> bool:
    return bool(load_key())


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _image_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{_mime_type(image_path)};base64,{encoded}"


def _walk_strings(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        kind = value.get("type")
        text = value.get("text")
        if kind in {"output_text", "text"} and isinstance(text, str):
            yield text
        elif isinstance(text, str) and kind != "input_text":
            yield text
        for key in ("content", "message", "choices", "output"):
            if key in value:
                yield from _walk_strings(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _extract_output_text(payload: Dict[str, object]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts = [item.strip() for item in _walk_strings(payload) if isinstance(item, str) and item.strip()]
    return "\n".join(dict.fromkeys(parts)).strip()


def normalize_answer(text: str) -> str:
    text = text.replace("```text", "").replace("```", "").strip()
    text = re.sub(r"^\s*(ответ|текст|результат|result|recognized text|transcription)\s*[:：\-]\s*", "", text, flags=re.IGNORECASE)
    text = text.replace("\u200b", "").replace("\x00", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip().strip('"').strip("'").strip()


def _language_hint(language: str) -> str:
    value = (language or "").lower()
    if "rus" in value and "eng" in value:
        return "The text may be Russian, English, digits, links or mixed characters."
    if "rus" in value:
        return "The visible text is likely Russian."
    if "eng" in value:
        return "The visible text is likely English."
    return "The visible text may use any alphabet."


def _mode_hint(mode: str) -> str:
    return {
        "numbers": "Focus on phone numbers, short codes, digits, punctuation and separate characters. Preserve every symbol.",
        "links": "Focus on URLs, domains, emails, slashes, dots, underscores, hyphens and query parameters. Preserve them exactly.",
        "handwriting": "The image may contain messy handwriting. Return the most likely transcription and do not leave the answer empty.",
        "messy": "The image may be blurred, crossed out, skewed, noisy or low quality. Give the most likely reading.",
        "auto": "The image may contain printed text, handwriting, numbers, punctuation or links.",
    }.get(mode, "Read all visible text.")


def _prompt(language: str, mode: str) -> str:
    return (
        "You are a strict OCR transcription engine. Return only the visible text from the image. "
        "Do not explain. Do not describe the image. Do not add words that are not visible. "
        "Keep line breaks if there are multiple lines. Preserve letter case, digits, punctuation, spaces, dots, slashes and plus signs. "
        "If the image is difficult, return the most likely text. If one character is unclear, choose the closest likely character. "
        f"{_language_hint(language)} {_mode_hint(mode)}"
    )


def _post_json(url: str, api_key: str, body: Dict[str, object], timeout: int) -> Dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _responses_call(api_key: str, model: str, data_url: str, prompt: str, detail: str, max_tokens: int, timeout: int) -> Tuple[str, str]:
    body = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url, "detail": detail},
                ],
            }
        ],
        "max_output_tokens": max_tokens,
    }
    payload = _post_json("https://api.openai.com/v1/responses", api_key, body, timeout)
    return normalize_answer(_extract_output_text(payload)), f"responses/{model}"


def _chat_call(api_key: str, model: str, data_url: str, prompt: str, detail: str, max_tokens: int, timeout: int) -> Tuple[str, str]:
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": detail}},
                ],
            }
        ],
        "max_tokens": max_tokens,
    }
    payload = _post_json("https://api.openai.com/v1/chat/completions", api_key, body, timeout)
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return normalize_answer(content), f"chat/{model}"
    return normalize_answer(_extract_output_text(payload)), f"chat/{model}"


def _models_from_settings(settings: Dict[str, object]) -> List[str]:
    result: List[str] = []
    primary = str(settings.get("model") or "").strip()
    if primary:
        result.append(primary)
    fallback = settings.get("fallback_models", [])
    if isinstance(fallback, str):
        fallback = [fallback]
    if isinstance(fallback, list):
        for item in fallback:
            model = str(item or "").strip()
            if model and model not in result:
                result.append(model)
    return result or [str(DEFAULT_SETTINGS["model"])]


def _friendly_api_error(raw: str) -> str:
    lowered = raw.lower()
    if "insufficient_quota" in lowered or "exceeded your current quota" in lowered:
        return "OpenAI API: превышен лимит или нет активного баланса в кабинете. Локальный режим продолжает работать."
    if "invalid_api_key" in lowered or "incorrect api key" in lowered:
        return "OpenAI API: ключ неверный. Проверь OPENAI_API_KEY.txt."
    if "rate_limit" in lowered:
        return "OpenAI API: временный лимит запросов. Попробуй позже или включи локальный движок."
    return raw[-1000:]


def recognize_with_openai(image_path: Path, language: str, mode: str) -> Dict[str, object]:
    api_key = load_key()
    settings = load_settings()
    if not api_key:
        return {"ok": False, "text": "", "confidence": 0, "engine": "openai_vision", "message": "OpenAI API key is not set. Paste it into OPENAI_API_KEY.txt."}

    timeout = int(settings.get("timeout_seconds") or DEFAULT_SETTINGS["timeout_seconds"])
    detail = str(settings.get("detail") or DEFAULT_SETTINGS["detail"])
    max_tokens = int(settings.get("max_output_tokens") or DEFAULT_SETTINGS["max_output_tokens"])
    data_url = _image_data_url(image_path)
    prompt = _prompt(language, mode)
    errors: List[str] = []

    for model in _models_from_settings(settings):
        for caller in (_responses_call, _chat_call):
            try:
                text, endpoint = caller(api_key, model, data_url, prompt, detail, max_tokens, timeout)
                if text:
                    return {
                        "ok": True,
                        "text": text,
                        "confidence": 96.0,
                        "engine": "openai_vision",
                        "model": model,
                        "endpoint": endpoint,
                        "message": "ready",
                    }
                errors.append(f"{caller.__name__}/{model}: empty response")
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="ignore")
                errors.append(f"HTTP {exc.code}: {_friendly_api_error(raw)}")
            except Exception as exc:
                errors.append(str(exc))

    message = "OpenAI returned no usable text. " + " | ".join(errors[-4:])
    return {
        "ok": False,
        "text": "",
        "confidence": 0,
        "engine": "openai_vision",
        "model": ", ".join(_models_from_settings(settings)),
        "message": message[:1600],
    }
