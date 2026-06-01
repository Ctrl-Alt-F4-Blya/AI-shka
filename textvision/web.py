from __future__ import annotations

import json
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict

from .config import SERVER_HOST, SERVER_PORT, STATIC_DIR
from .image_tools import PIL_AVAILABLE, decode_data_url
from .ocr import find_tesseract, list_languages, recognize
from .easyocr_engine import is_available as easyocr_is_available
from .openai_vision import is_ready as openai_is_ready, load_settings

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class WebHandler(BaseHTTPRequestHandler):
    server_version = "LocalTextReader/1.3"

    def log_message(self, message: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), message % args))

    def send_json(self, payload: Dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_static_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Not found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        if route in {"/", "/index.html"}:
            self.send_static_file(STATIC_DIR / "index.html")
            return
        if route.startswith("/static/"):
            filename = route.rsplit("/", 1)[-1]
            self.send_static_file(STATIC_DIR / filename)
            return
        if route == "/api/status":
            tesseract = find_tesseract()
            self.send_json({
                "ok": True,
                "pillow": PIL_AVAILABLE,
                "tesseract": bool(tesseract),
                "tesseractPath": tesseract or "",
                "languages": list_languages(tesseract) if tesseract else [],
                "openai": openai_is_ready(),
                "easyocr": easyocr_is_available(),
                "openaiModel": str(load_settings().get("model", "")),
            })
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route != "/api/ocr":
            self.send_error(404, "Not found")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            data_url = payload.get("image", "")
            language = payload.get("language", "rus+eng")
            mode = payload.get("mode", "auto")
            engine = payload.get("engine", "local")
            if not data_url:
                self.send_json({"ok": False, "message": "Image is empty"}, 400)
                return

            with tempfile.TemporaryDirectory(prefix="textvision_upload_") as temp_dir:
                upload = Path(temp_dir) / "upload.png"
                decode_data_url(data_url, upload)
                result = recognize(upload, language, mode, engine)
            self.send_json(result)
        except Exception as exc:
            self.send_json({"ok": False, "message": str(exc)}, 500)


def open_browser(url: str) -> None:
    time.sleep(1.0)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_server() -> None:
    url = f"http://{SERVER_HOST}:{SERVER_PORT}"
    tesseract = find_tesseract()

    print("AI text recognition local site")
    print("URL:", url)
    print("Pillow:", "OK" if PIL_AVAILABLE else "missing")
    print("Tesseract:", tesseract or "not found")
    print("EasyOCR:", "installed" if easyocr_is_available() else "not installed")
    print("OpenAI API:", "configured" if openai_is_ready() else "not configured")
    if tesseract:
        print("Languages:", ", ".join(list_languages(tesseract)) or "unknown")
    print("OpenAI model:", str(load_settings().get("model", "")))
    print("Close this terminal to stop the site.")
    print("-" * 64)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    server = ThreadingHTTPServer((SERVER_HOST, SERVER_PORT), WebHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping server...")
        server.server_close()
