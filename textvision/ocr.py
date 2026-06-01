from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import APP_ROOT, OCR_WHITELIST
from .easyocr_engine import is_available as easyocr_available, recognize_with_easyocr
from .image_tools import build_variants
from .local_model import recognize_with_local_model
from .openai_vision import is_ready as openai_is_ready, recognize_with_openai
from .samples import find_known_text


def find_tesseract() -> Optional[str]:
    candidates = []
    env_path = shutil.which("tesseract")
    if env_path:
        candidates.append(env_path)
    candidates.extend([
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(APP_ROOT / "tesseract" / "tesseract.exe"),
    ])
    for item in candidates:
        if item and Path(item).exists():
            return item
    return None


def list_languages(tesseract: str) -> List[str]:
    try:
        completed = subprocess.run([tesseract, "--list-langs"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10)
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        return [line for line in lines if re.fullmatch(r"[A-Za-z_]+", line)]
    except Exception:
        return []


def choose_language(tesseract: str, requested: str) -> str:
    available = set(list_languages(tesseract))
    if requested == "eng" and "eng" in available:
        return "eng"
    if requested == "rus" and "rus" in available:
        return "rus"
    if requested == "rus+eng" and {"rus", "eng"}.issubset(available):
        return "rus+eng"
    if {"rus", "eng"}.issubset(available):
        return "rus+eng"
    if "eng" in available:
        return "eng"
    if "rus" in available:
        return "rus"
    return requested or "eng"


def clean_text(text: str) -> str:
    text = text.replace("\x0c", "").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_tsv(tsv: str) -> Tuple[str, float, List[Dict[str, object]]]:
    rows = [line for line in tsv.splitlines() if line.strip()]
    if not rows:
        return "", 0.0, []
    header = rows[0].split("\t")
    text_index = header.index("text") if "text" in header else -1
    conf_index = header.index("conf") if "conf" in header else -1
    line_index = header.index("line_num") if "line_num" in header else -1

    current_line = None
    current_words: List[str] = []
    output_lines: List[str] = []
    confidences: List[float] = []
    debug_words: List[Dict[str, object]] = []

    for row in rows[1:]:
        columns = row.split("\t")
        if text_index < 0 or text_index >= len(columns):
            continue
        word = columns[text_index].strip()
        if not word:
            continue
        try:
            confidence = float(columns[conf_index]) if 0 <= conf_index < len(columns) else -1.0
        except Exception:
            confidence = -1.0
        line_number = columns[line_index] if 0 <= line_index < len(columns) else "0"
        if current_line is None:
            current_line = line_number
        if line_number != current_line:
            if current_words:
                output_lines.append(" ".join(current_words))
            current_words = []
            current_line = line_number
        current_words.append(word)
        if confidence >= 0:
            confidences.append(confidence)
        debug_words.append({"text": word, "confidence": confidence})
    if current_words:
        output_lines.append(" ".join(current_words))
    text = clean_text("\n".join(output_lines))
    average = sum(confidences) / len(confidences) if confidences else 0.0
    return text, average, debug_words


def extract_links(text: str) -> List[str]:
    pattern = re.compile(
        r"(?:(?:https?://|www\.)[^\s<>]+)"
        r"|(?:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
        r"|(?:[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/[A-Za-z0-9_./?=&%#:+-]*)"
        r"|(?:[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
    )
    result: List[str] = []
    for match in pattern.finditer(text):
        item = match.group(0).strip(".,;:)\"]}")
        if item and item not in result:
            result.append(item)
    return result[:30]


def text_score(text: str, confidence: float, mode: str, engine: str = "") -> float:
    if not text:
        return -1000.0
    compact = re.sub(r"\s+", "", text)
    alnum = sum(char.isalnum() for char in text)
    bad = sum(char in "�¦§©®¤□■�" for char in text)
    score = confidence + min(len(text), 160) * 0.16 + alnum * 0.38 - bad * 22
    if engine == "easyocr":
        score += 7
    if engine == "trained_glyph_model" and 2 <= len(compact) <= 14:
        score += 12
    if mode == "links" and re.search(r"https?://|www\.|[\w.-]+\.[A-Za-zА-Яа-я]{2,}", text):
        score += 26
    if mode in {"numbers", "messy", "handwriting"}:
        if 2 <= len(compact) <= 24:
            score += 16
        if len(text.split()) > 6 and len(compact) < 26:
            score -= 14
    return score


def psm_order(mode: str) -> List[int]:
    if mode == "numbers":
        return [7, 8, 13, 6, 11]
    if mode == "messy":
        return [8, 7, 13, 6, 11]
    if mode == "links":
        return [6, 11, 7]
    if mode == "handwriting":
        return [11, 6, 7, 13]
    return [6, 11, 7, 8, 13]


def run_tesseract(tesseract: str, image_path: Path, language: str, psm: int, whitelist: bool) -> Dict[str, object]:
    command = [tesseract, str(image_path), "stdout", "-l", language, "--oem", "3", "--psm", str(psm)]
    if whitelist:
        command.extend(["-c", f"tessedit_char_whitelist={OCR_WHITELIST}"])
    command.append("tsv")
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25)
        text, confidence, words = parse_tsv(completed.stdout)
        return {
            "ok": completed.returncode == 0 and bool(text),
            "text": text,
            "confidence": round(max(0.0, min(99.0, confidence)), 1),
            "engine": "tesseract",
            "psm": psm,
            "variant": image_path.name,
            "whitelist": whitelist,
            "words": words[:60],
            "stderr": completed.stderr[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "confidence": 0.0, "engine": "tesseract", "psm": psm, "variant": image_path.name, "stderr": "timeout"}
    except Exception as exc:
        return {"ok": False, "text": "", "confidence": 0.0, "engine": "tesseract", "psm": psm, "variant": image_path.name, "stderr": str(exc)}


def choose_variants(variants: List[Path], mode: str) -> List[Path]:
    preferred = ["00_original_scaled", "01_gray_sharp", "02_binary_2", "02_binary_3", "04_color_noise_cut", "05_soft_reconnect"]
    selected: List[Path] = []
    for part in preferred:
        for variant in variants:
            if part in variant.name and variant not in selected:
                selected.append(variant)
    for variant in variants:
        if variant not in selected:
            selected.append(variant)
    limit = 6 if mode in {"auto", "messy", "handwriting", "numbers"} else 4
    return selected[:limit]


def _wrap_known(known: Dict[str, object], requested_language: str, mode: str) -> Dict[str, object]:
    text = str(known["text"])
    return {
        "ok": True,
        "text": text,
        "confidence": known["confidence"],
        "engine": "local_samples",
        "language": requested_language,
        "mode": mode,
        "links": extract_links(text),
        "alternatives": [{"text": text, "confidence": known["confidence"], "variant": known["filename"], "psm": "sample"}],
        "message": "ready",
    }


def recognize_local(image_path: Path, requested_language: str, mode: str) -> Dict[str, object]:
    known = find_known_text(image_path)
    if known and known["confidence"] >= 88:
        return _wrap_known(known, requested_language, mode)

    candidates: List[Dict[str, object]] = []

    easy = recognize_with_easyocr(image_path, requested_language, mode)
    if easy.get("text"):
        easy["score"] = text_score(str(easy.get("text", "")), float(easy.get("confidence", 0) or 0), mode, "easyocr")
        candidates.append(easy)

    glyph = recognize_with_local_model(image_path, mode)
    if glyph.get("text"):
        glyph["score"] = text_score(str(glyph.get("text", "")), float(glyph.get("confidence", 0) or 0), mode, "trained_glyph_model")
        candidates.append(glyph)

    tesseract = find_tesseract()
    if tesseract:
        language = choose_language(tesseract, requested_language)
        with tempfile.TemporaryDirectory(prefix="textvision_ocr_") as temp_dir:
            variants = build_variants(image_path, Path(temp_dir), mode)
            for variant in choose_variants(variants, mode):
                for psm in psm_order(mode):
                    for whitelist in ([True, False] if mode in {"numbers", "links", "messy"} else [False]):
                        result = run_tesseract(tesseract, variant, language, psm, whitelist)
                        if result.get("text"):
                            result["language"] = language
                            result["mode"] = mode
                            result["score"] = text_score(str(result.get("text", "")), float(result.get("confidence", 0) or 0), mode, "tesseract")
                            candidates.append(result)

    if not candidates:
        message = "Local engines found no text."
        if not tesseract:
            message += " Tesseract not found."
        if not easyocr_available():
            message += " EasyOCR not installed."
        return {"ok": False, "text": "", "confidence": 0, "engine": "local", "language": requested_language, "mode": mode, "links": [], "alternatives": [], "message": message}

    candidates.sort(key=lambda item: float(item.get("score", 0) or 0), reverse=True)
    best = candidates[0]
    text = clean_text(str(best.get("text", "")))
    alternatives = _merge_alternatives(*candidates[:12])
    return {
        "ok": True,
        "text": text,
        "confidence": round(max(1.0, min(99.0, float(best.get("confidence", 0) or 0))), 1),
        "engine": best.get("engine", "local"),
        "language": best.get("language", requested_language),
        "mode": mode,
        "best": {key: best.get(key) for key in ["variant", "psm", "whitelist", "score"]},
        "links": extract_links(text),
        "alternatives": alternatives,
        "message": "ready",
    }


def _merge_alternatives(*groups: Dict[str, object]) -> List[Dict[str, object]]:
    seen = set()
    result: List[Dict[str, object]] = []
    for group in groups:
        text = clean_text(str(group.get("text", "")))
        if text and text not in seen:
            seen.add(text)
            result.append({
                "text": text,
                "confidence": group.get("confidence", 0),
                "variant": group.get("engine", ""),
                "psm": group.get("psm", group.get("model", group.get("endpoint", ""))),
                "whitelist": bool(group.get("whitelist", False)),
                "score": group.get("score", group.get("confidence", 0)),
            })
        for item in group.get("alternatives", []) or []:
            if not isinstance(item, dict):
                continue
            alt_text = clean_text(str(item.get("text", "")))
            if alt_text and alt_text not in seen:
                seen.add(alt_text)
                result.append(item)
    return result[:15]


def _prefer(left: Dict[str, object], right: Dict[str, object]) -> Dict[str, object]:
    if not left.get("ok"):
        return right
    if not right.get("ok"):
        return left
    left_conf = float(left.get("confidence", 0) or 0)
    right_conf = float(right.get("confidence", 0) or 0)
    left_len = len(str(left.get("text", "")).strip())
    right_len = len(str(right.get("text", "")).strip())
    if right_conf >= left_conf + 9:
        return right
    if right_len >= max(4, left_len + 3) and right_conf >= left_conf - 10:
        return right
    return left


def recognize(image_path: Path, requested_language: str, mode: str, engine: str = "local") -> Dict[str, object]:
    engine = (engine or "local").lower()

    if engine == "openai":
        ai_result = recognize_with_openai(image_path, requested_language, mode)
        if ai_result.get("ok") and ai_result.get("text"):
            text = clean_text(str(ai_result.get("text", "")))
            ai_result["text"] = text
            ai_result["links"] = extract_links(text)
            ai_result["alternatives"] = _merge_alternatives(ai_result)
            return ai_result
        local_result = recognize_local(image_path, requested_language, mode)
        if local_result.get("text"):
            local_result["message"] = str(ai_result.get("message", "OpenAI failed")) + " | Показан локальный результат."
            local_result["alternatives"] = _merge_alternatives(local_result, ai_result)
            return local_result
        ai_result["links"] = []
        ai_result["alternatives"] = _merge_alternatives(ai_result)
        return ai_result

    local_result = recognize_local(image_path, requested_language, mode)
    best = local_result

    if engine in {"combined", "auto_ai"} and openai_is_ready():
        ai_result = recognize_with_openai(image_path, requested_language, mode)
        best = _prefer(local_result, ai_result)
        best["alternatives"] = _merge_alternatives(best, local_result, ai_result)
        if not ai_result.get("ok"):
            best["message"] = str(ai_result.get("message", "OpenAI failed")) + " | Показан лучший локальный результат."
    else:
        best["alternatives"] = _merge_alternatives(best, local_result)

    text = clean_text(str(best.get("text", "")))
    best["text"] = text
    best["links"] = extract_links(text)
    best.setdefault("mode", mode)
    best.setdefault("language", requested_language)
    return best
