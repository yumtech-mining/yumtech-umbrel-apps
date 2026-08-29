"""HTTP API and static server for the standalone dashboard."""

from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .service import DashboardService


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "YUMTECH-CKPool-Dashboard/1.0"
    service: DashboardService

    def _authorized(self) -> bool:
        settings = self.service.settings
        if not settings.basic_auth_user or not settings.basic_auth_password:
            return True
        header = self.headers.get("Authorization", "")
        expected = base64.b64encode(f"{settings.basic_auth_user}:{settings.basic_auth_password}".encode()).decode()
        return hmac.compare_digest(header, f"Basic {expected}")

    def _require_auth(self) -> bool:
        if self._authorized():
            return False
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="YUMTECH"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        name = "index.html" if path in {"", "/"} else posixpath.basename(unquote(path))
        if name not in {"index.html", "app.js", "style.css", "yumtech-logo.png"}:
            self.send_error(404)
            return
        target = self.service.settings.static_dir / name
        try:
            body = target.read_bytes()
        except OSError:
            self.send_error(404)
            return
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
        self.send_header("Cache-Control", "no-cache" if name == "index.html" else "public, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._json({"status": "ok"})
            return
        if self._require_auth():
            return
        try:
            if parsed.path == "/api/overview":
                self._json(self.service.overview())
            elif parsed.path == "/api/analytics":
                self._json(self.service.analytics())
            elif parsed.path == "/api/miners":
                self._json(self.service.miners())
            elif parsed.path == "/api/shares":
                query = parse_qs(parsed.query)
                self._json(self.service.storage.shares(int(query.get("limit", [100])[0])))
            elif parsed.path == "/api/blocks":
                self._json(self.service.blocks())
            elif parsed.path == "/api/node":
                self._json(self.service.node())
            elif parsed.path == "/api/config":
                self._json(self.service.config())
            elif parsed.path == "/api/history":
                query = parse_qs(parsed.query)
                self._json(self.service.storage.history(int(query.get("hours", [1])[0])))
            elif parsed.path.startswith("/api/"):
                self._json({"error": "not found"}, 404)
            else:
                self._static(parsed.path)
        except (TypeError, ValueError):
            self._json({"error": "invalid request"}, 400)
        except Exception:
            self._json({"error": "telemetry temporarily unavailable"}, 503)

    def log_message(self, fmt: str, *args: object) -> None:
        if self.path == "/healthz":
            return
        super().log_message(fmt, *args)


def make_server(service: DashboardService) -> ThreadingHTTPServer:
    handler = type("BoundDashboardHandler", (DashboardHandler,), {"service": service})
    server = ThreadingHTTPServer((service.settings.host, service.settings.port), handler)
    server.daemon_threads = True
    return server
