from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_ROOT / "static"
SAMPLES_DIR = APP_ROOT / "samples"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("TEXTVISION_PORT", "8765"))

CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"
PUNCTUATION = r".,:;!?/\\|()[]{}<>@#$%^&*+=_-—–\"'`~№"
OCR_WHITELIST = LATIN + CYRILLIC + DIGITS + PUNCTUATION

OPENAI_KEY_FILE = APP_ROOT / "OPENAI_API_KEY.txt"
OPENAI_SETTINGS_FILE = APP_ROOT / "OPENAI_API_SETTINGS.json"

DEFAULT_LABELS = {
    "w9h5k.png": "W9H5K",
    "q2d4r.png": "Q2D4R",
    "v4xbc.png": "V4XBC",
}
