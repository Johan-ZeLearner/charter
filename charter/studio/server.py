"""A tiny stdlib HTTP server for the studio — zero extra dependencies.

Deliberately not FastAPI: the user's env already has numpy/scipy/ffmpeg, and a
no-install ``python -m charter.studio song.mp3`` that just opens a browser is the
lowest-friction way to get the tune loop running. Three routes:

    GET  /                      -> the previewer page (web/index.html)
    GET  /<static>              -> web/app.js, web/styles.css
    GET  /api/meta              -> {name, artist, duration_s}
    POST /api/preview           -> notes-with-times JSON for a window+settings
    GET  /api/audio?start_s&length_s -> the clip as WAV (for playback)
"""

from __future__ import annotations

import json
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..patterns import list_patterns
from .service import clip_wav_bytes, run_preview, song_meta

WEB_DIR = Path(__file__).parent / "web"
_STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class StudioHandler(BaseHTTPRequestHandler):
    audio_path: str = ""  # set on the class before serving

    # --- helpers -------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: object) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        return

    # --- routes --------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route in _STATIC:
                fname, ctype = _STATIC[route]
                data = (WEB_DIR / fname).read_bytes()
                return self._send(200, data, ctype)
            if route == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")  # silence the console 404
            if route == "/api/meta":
                return self._json(200, song_meta(self.audio_path))
            if route == "/api/patterns":
                return self._json(200, {"patterns": list_patterns()})
            if route == "/api/audio":
                q = parse_qs(parsed.query)
                start = float(q.get("start_s", ["0"])[0])
                length = float(q.get("length_s", ["16"])[0])
                wav = clip_wav_bytes(self.audio_path, start, length)
                return self._send(200, wav, "audio/wav")
            # last-ditch static (e.g. favicon) from web dir
            candidate = (WEB_DIR / route.lstrip("/")).resolve()
            if candidate.is_file() and WEB_DIR.resolve() in candidate.parents:
                ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
                return self._send(200, candidate.read_bytes(), ctype)
            return self._json(404, {"error": f"not found: {route}"})
        except Exception as exc:  # surface errors to the UI rather than 500-silent
            return self._json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/preview":
            return self._json(404, {"error": f"not found: {parsed.path}"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n) or b"{}")
            start = float(payload.get("start_s", 0.0))
            length = float(payload.get("length_s", 16.0))
            settings = payload.get("settings", {})
            result = run_preview(self.audio_path, start, length, settings)
            return self._json(200, result)
        except Exception as exc:
            return self._json(500, {"error": str(exc)})


def serve(audio_path: str, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = True) -> None:
    StudioHandler.audio_path = str(audio_path)
    httpd = ThreadingHTTPServer((host, port), StudioHandler)
    url = f"http://{host}:{port}/"
    print(f"charter studio  ·  {Path(audio_path).name}")
    print(f"  open {url}   (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
