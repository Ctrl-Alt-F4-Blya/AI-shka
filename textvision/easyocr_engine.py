from __future__ import annotations

from pathlib import Path
from typing import Dict, List


def is_available() -> bool:
    try:
        import easyocr  # noqa: F401
        return True
    except Exception:
        return False


def _langs(requested: str) -> List[str]:
    value = (requested or "").lower()
    if "rus" in value and "eng" in value:
        return ["ru", "en"]
    if "rus" in value:
        return ["ru"]
    return ["en"]


def recognize_with_easyocr(image_path: Path, requested_language: str, mode: str) -> Dict[str, object]:
    try:
        import easyocr
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "confidence": 0,
            "engine": "easyocr",
            "message": "EasyOCR is not installed. Run INSTALL_STRONG_OCR.cmd once.",
            "error": str(exc),
        }

    try:
        langs = _langs(requested_language)
        reader = easyocr.Reader(langs, gpu=False, verbose=False)
        allowlist = None
        if mode == "numbers":
            allowlist = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя+-_/.,:()№ "
        rows = reader.readtext(str(image_path), detail=1, paragraph=False, allowlist=allowlist)
        items: List[Dict[str, object]] = []
        for row in rows:
            text = str(row[1]).strip() if len(row) > 1 else ""
            try:
                conf = float(row[2]) * 100
            except Exception:
                conf = 0.0
            if text:
                items.append({"text": text, "confidence": round(conf, 1)})
        if not items:
            return {"ok": False, "text": "", "confidence": 0, "engine": "easyocr", "message": "EasyOCR found no text."}
        text = "\n".join(item["text"] for item in items).strip()
        avg = sum(float(item["confidence"]) for item in items) / len(items)
        return {
            "ok": True,
            "text": text,
            "confidence": round(avg, 1),
            "engine": "easyocr",
            "language": requested_language,
            "mode": mode,
            "alternatives": [{"text": item["text"], "confidence": item["confidence"], "variant": "easyocr", "psm": "detector"} for item in items[:10]],
            "message": "ready",
        }
    except Exception as exc:
        return {"ok": False, "text": "", "confidence": 0, "engine": "easyocr", "message": str(exc)}
