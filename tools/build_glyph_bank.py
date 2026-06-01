from __future__ import annotations

import gzip
import json
import os
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "glyph_bank.json.gz"
CANVAS = (24, 32)
CHARS = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    "+-_/.,:()№@"
)


def font_paths():
    result = []
    windir = os.environ.get("WINDIR")
    if windir:
        win_fonts = Path(windir) / "Fonts"
        names = ["arial.ttf", "arialbd.ttf", "calibri.ttf", "calibrib.ttf", "times.ttf", "timesbd.ttf", "tahoma.ttf", "segoeui.ttf", "consola.ttf"]
        result.extend(win_fonts / name for name in names)
    roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
    for root in roots:
        if root.exists():
            result.extend(root.rglob("*.ttf"))
            result.extend(root.rglob("*.otf"))
    preferred = []
    for path in result:
        low = str(path).lower()
        if any(key in low for key in ["dejavu", "arimo", "tinos", "clear", "liberation", "cousine", "noto"]):
            preferred.append(path)
    final = []
    seen = set()
    for path in preferred + result:
        if path.exists() and str(path) not in seen:
            seen.add(str(path))
            final.append(path)
    return final[:4]


def otsu(gray):
    hist = gray.histogram()
    total = sum(hist)
    weighted = sum(i * count for i, count in enumerate(hist))
    b_sum = 0.0
    b_weight = 0
    best = 0.0
    threshold = 127
    for value in range(256):
        b_weight += hist[value]
        if not b_weight:
            continue
        f_weight = total - b_weight
        if not f_weight:
            break
        b_sum += value * hist[value]
        b_mean = b_sum / b_weight
        f_mean = (weighted - b_sum) / f_weight
        score = b_weight * f_weight * (b_mean - f_mean) ** 2
        if score > best:
            best = score
            threshold = value
    return threshold


def normalize(img):
    gray = img.convert("L")
    gray = ImageOps.autocontrast(gray)
    threshold = otsu(gray)
    bw = gray.point(lambda px: 0 if px < threshold else 255, mode="L")
    box = ImageOps.invert(bw).getbbox()
    if box:
        bw = bw.crop(box)
    bw.thumbnail((CANVAS[0] - 4, CANVAS[1] - 4), Image.Resampling.LANCZOS)
    target = Image.new("L", CANVAS, 255)
    target.paste(bw, ((CANVAS[0] - bw.width) // 2, (CANVAS[1] - bw.height) // 2))
    return target


def render_char(char, font_path, size, angle=0, stroke=0):
    font = ImageFont.truetype(str(font_path), size=size)
    img = Image.new("L", (72, 84), 255)
    draw = ImageDraw.Draw(img)
    box = draw.textbbox((0, 0), char, font=font, stroke_width=stroke)
    width = max(1, box[2] - box[0])
    height = max(1, box[3] - box[1])
    x = (img.width - width) // 2 - box[0]
    y = (img.height - height) // 2 - box[1]
    draw.text((x, y), char, font=font, fill=0, stroke_width=stroke, stroke_fill=0)
    if angle:
        img = img.rotate(angle, expand=False, fillcolor=255, resample=Image.Resampling.BICUBIC)
    # small synthetic damage and blur variations
    return normalize(img)


def bits(img):
    pixels = list(img.getdata())
    return "".join("1" if px < 158 else "0" for px in pixels)


def main():
    random.seed(42)
    templates = {char: [] for char in CHARS}
    fonts = font_paths()
    print("fonts:", len(fonts))
    for font_path in fonts:
        for size in [28, 36]:
            for angle in [-7, 0, 7]:
                for stroke in [0]:
                    for char in CHARS:
                        try:
                            value = bits(render_char(char, font_path, size, angle=angle, stroke=stroke))
                        except Exception:
                            continue
                        bucket = templates[char]
                        if value not in bucket:
                            bucket.append(value)
    # keep the bank compact but diverse
    compact = {char: values[:30] for char, values in templates.items() if values}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as file:
        json.dump({"canvas": CANVAS, "templates": compact}, file, ensure_ascii=False)
    print("written:", OUT, "chars:", len(compact), "templates:", sum(len(v) for v in compact.values()))


if __name__ == "__main__":
    main()
