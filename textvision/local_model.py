from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import APP_ROOT, CYRILLIC, DIGITS, LATIN, PUNCTUATION
from .image_tools import PIL_AVAILABLE, crop_content, open_rgb, otsu_threshold

if PIL_AVAILABLE:
    from PIL import Image, ImageFilter, ImageOps
else:  # pragma: no cover
    Image = None  # type: ignore
    ImageFilter = None  # type: ignore
    ImageOps = None  # type: ignore

MODEL_FILE = APP_ROOT / "models" / "glyph_bank.json.gz"
CANVAS = (24, 32)
COMMON_CHARS = DIGITS + LATIN + CYRILLIC + "+-_/.,:()№@"


def _bits_to_vec(bits: str) -> List[int]:
    return [1 if char == "1" else 0 for char in bits]


@lru_cache(maxsize=1)
def load_bank() -> Dict[str, List[List[int]]]:
    if not MODEL_FILE.exists():
        return {}
    try:
        with gzip.open(MODEL_FILE, "rt", encoding="utf-8") as file:
            raw = json.load(file)
        bank: Dict[str, List[List[int]]] = {}
        for char, variants in raw.get("templates", {}).items():
            if isinstance(char, str) and isinstance(variants, list):
                bank[char] = [_bits_to_vec(str(bits)) for bits in variants[:90]]
        return bank
    except Exception:
        return {}


def _normalize_glyph(img):
    gray = img.convert("L")
    gray = ImageOps.autocontrast(gray)
    threshold = otsu_threshold(gray)
    bw = gray.point(lambda px: 0 if px < threshold else 255, mode="L")
    box = ImageOps.invert(bw).getbbox()
    if box:
        bw = bw.crop(box)
    bw.thumbnail((CANVAS[0] - 4, CANVAS[1] - 4), Image.Resampling.LANCZOS)
    target = Image.new("L", CANVAS, 255)
    target.paste(bw, ((CANVAS[0] - bw.width) // 2, (CANVAS[1] - bw.height) // 2))
    return target


def _vector(img) -> List[int]:
    small = _normalize_glyph(img).resize(CANVAS, Image.Resampling.BILINEAR)
    return [0 if px > 158 else 1 for px in small.getdata()]


def _distance(left: Iterable[int], right: Iterable[int]) -> float:
    total = 0
    diff = 0
    for a, b in zip(left, right):
        total += 1
        if a != b:
            diff += 1
    return diff / max(1, total)


def _prepare(path: Path):
    img = open_rgb(path)
    img = crop_content(img, padding=3)
    scale = 6 if max(img.size) < 450 else 3
    img = img.resize((max(1, img.width * scale), max(1, img.height * scale)), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.3, percent=180, threshold=2))
    threshold = otsu_threshold(gray)
    bw = gray.point(lambda px: 0 if px < threshold else 255, mode="L")
    # remove tiny isolated noise
    try:
        bw = bw.filter(ImageFilter.MedianFilter(size=3))
    except Exception:
        pass
    return bw


def _column_segments(bw) -> List[Tuple[int, int]]:
    width, height = bw.size
    data = bw.load()
    ink = []
    for x in range(width):
        count = 0
        for y in range(height):
            if data[x, y] < 128:
                count += 1
        ink.append(count)

    min_ink = max(1, int(height * 0.018))
    raw: List[Tuple[int, int]] = []
    start: Optional[int] = None
    gap = 0
    max_gap = max(2, width // 110)
    for x, count in enumerate(ink):
        if count >= min_ink:
            if start is None:
                start = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= max_gap:
                end = x - gap + 1
                if end - start >= max(2, width // 250):
                    raw.append((start, end))
                start = None
                gap = 0
    if start is not None:
        raw.append((start, width - 1))

    merged: List[Tuple[int, int]] = []
    for left, right in raw:
        if right <= left:
            continue
        if not merged:
            merged.append((left, right))
            continue
        previous = merged[-1]
        gap_size = left - previous[1]
        if gap_size <= max(1, width // 180):
            merged[-1] = (previous[0], right)
        else:
            merged.append((left, right))
    return merged[:120]


def _split_wide_segments(segments: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not segments:
        return segments
    widths = [r - l for l, r in segments]
    median = sorted(widths)[len(widths) // 2]
    result: List[Tuple[int, int]] = []
    for left, right in segments:
        width = right - left
        if median > 0 and width > median * 2.15 and width > 16:
            parts = max(2, round(width / max(1, median)))
            step = width / parts
            for index in range(parts):
                a = int(left + index * step)
                b = int(left + (index + 1) * step)
                if b - a > 2:
                    result.append((a, b))
        else:
            result.append((left, right))
    return result


def _classify(glyph) -> Tuple[str, float, List[Tuple[str, float]]]:
    bank = load_bank()
    if not bank:
        return "", 0.0, []
    vec = _vector(glyph)
    scored: List[Tuple[str, float]] = []
    for char, variants in bank.items():
        best = min((_distance(vec, candidate) for candidate in variants), default=1.0)
        confidence = max(0.0, min(96.0, 100.0 * (1.0 - best * 2.15)))
        scored.append((char, confidence))
    scored.sort(key=lambda item: item[1], reverse=True)
    best_char, best_conf = scored[0]
    return best_char, best_conf, scored[:4]


def recognize_with_local_model(image_path: Path, mode: str) -> Dict[str, object]:
    if not PIL_AVAILABLE:
        return {"ok": False, "text": "", "confidence": 0, "engine": "trained_glyph_model", "message": "Pillow is not installed."}
    if not load_bank():
        return {"ok": False, "text": "", "confidence": 0, "engine": "trained_glyph_model", "message": "Glyph bank not found."}

    try:
        bw = _prepare(image_path)
        segments = _split_wide_segments(_column_segments(bw))
        if not segments:
            return {"ok": False, "text": "", "confidence": 0, "engine": "trained_glyph_model", "message": "No glyphs found."}

        widths = [right - left for left, right in segments]
        average_width = sum(widths) / len(widths)
        chars: List[str] = []
        scores: List[float] = []
        char_alts: List[str] = []
        last_right: Optional[int] = None
        for left, right in segments:
            if last_right is not None and left - last_right > average_width * 1.25:
                chars.append(" ")
            last_right = right
            glyph = bw.crop((max(0, left - 3), 0, min(bw.width, right + 4), bw.height))
            char, confidence, alternatives = _classify(glyph)
            if char:
                chars.append(char)
                scores.append(confidence)
                char_alts.append("".join(item[0] for item in alternatives[:3]))
        text = "".join(chars).strip()
        confidence = sum(scores) / len(scores) if scores else 0.0
        alnum_count = sum(ch.isalnum() for ch in text)
        if alnum_count == 0 or (len(text) >= 3 and alnum_count < len(text) * 0.35):
            return {"ok": False, "text": text, "confidence": round(min(confidence, 25), 1), "engine": "trained_glyph_model", "message": "Too much punctuation/noise."}
        confidence = min(confidence, 78.0)
        if len(text) < 2 or confidence < 22:
            return {"ok": False, "text": text, "confidence": round(confidence, 1), "engine": "trained_glyph_model", "message": "Low confidence."}
        alt_text = " ".join(char_alts[:60])
        return {
            "ok": True,
            "text": text,
            "confidence": round(confidence, 1),
            "engine": "trained_glyph_model",
            "message": "ready",
            "alternatives": [{"text": text, "confidence": round(confidence, 1), "variant": "trained_glyph_bank", "psm": "segments"}, {"text": alt_text, "confidence": round(confidence * 0.7, 1), "variant": "top_char_variants", "psm": "per-symbol"}],
        }
    except Exception as exc:
        return {"ok": False, "text": "", "confidence": 0, "engine": "trained_glyph_model", "message": str(exc)}
