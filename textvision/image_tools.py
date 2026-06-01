from __future__ import annotations

import base64
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

try:
    from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
    PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageChops = None  # type: ignore
    ImageEnhance = None  # type: ignore
    ImageFilter = None  # type: ignore
    ImageOps = None  # type: ignore
    PIL_AVAILABLE = False


def decode_data_url(data_url: str, target: Path) -> None:
    payload = data_url.split(",", 1)[1] if "," in data_url else data_url
    target.write_bytes(base64.b64decode(payload))


def open_rgb(path: Path):
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is not installed")
    img = Image.open(path)
    return ImageOps.exif_transpose(img).convert("RGB")


def crop_content(img, padding: int = 12):
    rgb = img.convert("RGB")
    white = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, white).convert("L")
    mask = diff.point(lambda value: 255 if value > 18 else 0)
    box = mask.getbbox()
    if box is None:
        return img
    left, top, right, bottom = box
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(img.width, right + padding)
    bottom = min(img.height, bottom + padding)
    return img.crop((left, top, right, bottom))


def add_border(img, size: int = 30):
    return ImageOps.expand(img.convert("RGB"), border=size, fill="white")


def resize_for_ocr(img):
    cropped = crop_content(img, padding=14)
    scale = 4 if max(cropped.size) < 650 else 2
    width = max(1, cropped.width * scale)
    height = max(1, cropped.height * scale)
    return add_border(cropped.resize((width, height), Image.Resampling.LANCZOS), 36)


def otsu_threshold(gray) -> int:
    hist = gray.histogram()
    total = sum(hist)
    weighted_sum = sum(index * count for index, count in enumerate(hist))
    background_sum = 0.0
    background_weight = 0
    best_value = 0.0
    best_threshold = 127

    for value in range(256):
        background_weight += hist[value]
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += value * hist[value]
        mean_background = background_sum / background_weight
        mean_foreground = (weighted_sum - background_sum) / foreground_weight
        between_class = background_weight * foreground_weight * (mean_background - mean_foreground) ** 2
        if between_class > best_value:
            best_value = between_class
            best_threshold = value
    return best_threshold


def save_variant(img, target_dir: Path, name: str, result: List[Path]) -> Path:
    path = target_dir / name
    img.convert("RGB").save(path)
    result.append(path)
    return path


def build_variants(source: Path, target_dir: Path, mode: str) -> List[Path]:
    if not PIL_AVAILABLE:
        return [source]

    original = open_rgb(source)
    enlarged = resize_for_ocr(original)
    variants: List[Path] = []
    save_variant(enlarged, target_dir, "00_original_scaled.png", variants)

    gray = ImageOps.grayscale(enlarged)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    sharp = gray.filter(ImageFilter.UnsharpMask(radius=1.8, percent=190, threshold=3))
    save_variant(sharp, target_dir, "01_gray_sharp.png", variants)

    try:
        base_threshold = otsu_threshold(sharp)
    except Exception:
        base_threshold = 145

    thresholds = sorted({
        max(65, base_threshold - 35),
        max(80, base_threshold - 15),
        base_threshold,
        min(215, base_threshold + 20),
        135,
        165,
    })
    for index, threshold in enumerate(thresholds):
        bw = sharp.point(lambda px: 0 if px < threshold else 255, mode="1").convert("L")
        bw = bw.filter(ImageFilter.MedianFilter(size=3))
        save_variant(bw, target_dir, f"02_binary_{index}_{threshold}.png", variants)
        if mode in {"auto", "messy", "handwriting", "numbers"}:
            save_variant(ImageOps.invert(bw), target_dir, f"03_invert_{index}_{threshold}.png", variants)

    red, green, blue = enlarged.split()
    dark_channel = ImageChops.darker(ImageChops.darker(red, green), blue)
    dark_channel = ImageOps.autocontrast(dark_channel)
    dark_channel = ImageEnhance.Contrast(dark_channel).enhance(2.5)
    save_variant(dark_channel, target_dir, "04_color_noise_cut.png", variants)

    if mode in {"auto", "messy", "handwriting", "numbers"}:
        reconnected = sharp.filter(ImageFilter.GaussianBlur(radius=0.65))
        reconnected = ImageEnhance.Contrast(reconnected).enhance(2.2)
        save_variant(reconnected, target_dir, "05_soft_reconnect.png", variants)

    return variants


def image_fingerprint(path: Path, canvas_size: Tuple[int, int] = (96, 40)) -> Optional[List[int]]:
    if not PIL_AVAILABLE:
        return None
    try:
        img = open_rgb(path)
        img = crop_content(img, padding=4)
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img)
        img.thumbnail(canvas_size, Image.Resampling.LANCZOS)
        canvas = Image.new("L", canvas_size, 255)
        x = (canvas_size[0] - img.width) // 2
        y = (canvas_size[1] - img.height) // 2
        canvas.paste(img, (x, y))
        canvas = canvas.resize((32, 16), Image.Resampling.LANCZOS)
        pixels = list(canvas.getdata())
        average = sum(pixels) / len(pixels)
        return [1 if value < average else 0 for value in pixels]
    except Exception:
        return None


def hamming_distance(left: Iterable[int], right: Iterable[int]) -> int:
    return sum(1 for a, b in zip(left, right) if a != b)
