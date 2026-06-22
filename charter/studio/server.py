"""Stdlib HTTP server for the beat-grid studio — no external deps.

Routes:
    GET /                              the studio page (web/index.html)
    GET /app.js /styles.css            static
    GET /api/meta                      {name, artist, duration_s}
    GET /api/analyze?tempo_mult&...    beats + tempo curve + sections + waveform
    GET /api/analyze_region?start&end  re-track one region (per-section rework) in song time
    GET /api/audio                     the full source audio, with HTTP Range (seek)

The grid is the foundation, so the studio analyzes the WHOLE song (beats drift,
sections span the song) and serves the full audio so the DAW timeline can scrub
anywhere.
"""

from __future__ import annotations

import json
import mimetypes
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .analyze import analyze_song, analyze_window
from .service import song_meta

WEB_DIR = Path(__file__).parent / "web"
_STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class StudioHandler(BaseHTTPRequestHandler):
    audio_path: str = ""

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def log_message(self, *a):
        return

    def _serve_audio(self):
        """Serve the source file, honoring a single Range request for seeking."""
        path = self.audio_path
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "audio/mpeg"
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            try:
                s, _, e = rng[6:].partition("-")
                start = int(s) if s else 0
                end = int(e) if e else size - 1
                end = min(end, size - 1)
                start = max(0, min(start, end))
            except ValueError:
                start, end = 0, size - 1
            with open(path, "rb") as f:
                f.seek(start)
                chunk = f.read(end - start + 1)
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(chunk)
        else:
            with open(path, "rb") as f:
                data = f.read()
            self._send(200, data, ctype, {"Accept-Ranges": "bytes"})

    def do_GET(self):
        parsed = urlparse(self.path)
        route, q = parsed.path, parse_qs(parsed.query)
        try:
            if route == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if route in _STATIC:
                fname, ctype = _STATIC[route]
                return self._send(200, (WEB_DIR / fname).read_bytes(), ctype)
            if route == "/api/meta":
                return self._json(200, song_meta(self.audio_path))
            if route == "/api/audio":
                return self._serve_audio()
            def f(name, default):
                return q.get(name, [str(default)])[0]

            def opt(name):
                v = q.get(name, [""])[0]
                return v if v != "" else None

            if route == "/api/analyze":
                report = analyze_song(
                    self.audio_path,
                    tempo_mult=float(f("tempo_mult", 1.0)),
                    tempo_hint=float(opt("tempo_hint")) if opt("tempo_hint") else None,
                    beats_per_bar=int(f("beats_per_bar", 4)),
                    phase=int(opt("phase")) if opt("phase") is not None else None,
                )
                return self._json(200, report)
            if route == "/api/analyze_region":
                report = analyze_window(
                    self.audio_path,
                    float(f("start", 0.0)),
                    float(f("end", 0.0)),
                    tempo_mult=float(f("tempo_mult", 1.0)),
                    tempo_hint=float(opt("tempo_hint")) if opt("tempo_hint") else None,
                    beats_per_bar=int(f("beats_per_bar", 4)),
                    phase=int(opt("phase")) if opt("phase") is not None else None,
                    anchor=float(opt("anchor")) if opt("anchor") is not None else None,
                    lock=f("lock", "0") in ("1", "true", "True"),
                )
                return self._json(200, report)
            return self._json(404, {"error": f"not found: {route}"})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})


def serve(audio_path, host="127.0.0.1", port=8765, open_browser=True):
    StudioHandler.audio_path = str(audio_path)
    httpd = ThreadingHTTPServer((host, port), StudioHandler)
    url = f"http://{host}:{port}/"
    print(f"charter studio (beat grid)  ·  {Path(audio_path).name}")
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
