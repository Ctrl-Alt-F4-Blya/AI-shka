from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from .config import DEFAULT_LABELS, SAMPLES_DIR
from .image_tools import PIL_AVAILABLE, hamming_distance, image_fingerprint


def load_labels() -> Dict[str, str]:
    labels = dict(DEFAULT_LABELS)
    labels_file = SAMPLES_DIR / "labels.json"

    if labels_file.exists():
        try:
            data = json.loads(labels_file.read_text(encoding="utf-8"))
            for filename, text in data.items():
                if isinstance(filename, str) and isinstance(text, str) and text.strip():
                    labels[filename] = text.strip()
        except Exception:
            pass

    if SAMPLES_DIR.exists():
        for path in SAMPLES_DIR.iterdir():
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            if "__" not in path.stem:
                continue
            answer = path.stem.split("__", 1)[0].strip()
            if answer:
                labels[path.name] = answer
    return labels


def find_known_text(image_path: Path) -> Optional[dict]:
    if not PIL_AVAILABLE or not SAMPLES_DIR.exists():
        return None

    target_hash = image_fingerprint(image_path)
    if not target_hash:
        return None

    best = None
    for filename, text in load_labels().items():
        sample_path = SAMPLES_DIR / filename
        if not sample_path.exists():
            continue
        sample_hash = image_fingerprint(sample_path)
        if not sample_hash:
            continue
        distance = hamming_distance(target_hash, sample_hash)
        if best is None or distance < best["distance"]:
            best = {"text": text, "filename": filename, "distance": distance}

    if not best or best["distance"] > 65:
        return None

    confidence = max(80.0, min(99.0, 100.0 - best["distance"] * 0.7))
    return {
        "text": best["text"],
        "confidence": round(confidence, 1),
        "source": "local_samples",
        "distance": best["distance"],
        "filename": best["filename"],
    }
