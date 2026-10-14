"""The local dashboard's web server. It runs inside the agent, on 127.0.0.1 only, and shows the same charts as the
website from the numbers the agent already holds (no response text exists on disk, so none can be shown).

How a browser gets in, and what keeps everyone else out:

- `driftwatch dashboard` asks the agent (over its authenticated local endpoint) to start this server and gets a
  one-time token (it works once, so a link glimpsed in a process list is useless afterwards). It opens `http://127.0.0.1:PORT/#token=...`. A URL fragment is never sent to a server,
  never put in a Referer header and not stored in server logs.
- The page's script posts the token to `/session`; the server answers with a random session id in an
  `HttpOnly; SameSite=Strict` cookie, and the script removes the fragment from the address bar.
- Every request must carry a `Host` of `127.0.0.1:PORT` or `localhost:PORT` (this defeats DNS rebinding: a hostile
  site whose name points at 127.0.0.1 sends its own name as Host), no foreign `Origin`, and no cross-site
  `Sec-Fetch-Site`. `/session` accepts only `application/json`, which a cross-site HTML form cannot send.
- There are no CORS headers and no OPTIONS handler, so no other website can read a response.
- `/api/*` needs the session cookie. Only the built page itself (no data) is served without one.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
import socketserver
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlsplit

RANGES = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
SESSION_COOKIE = "dw_session"
SESSION_TTL = 8 * 3600
MAX_SESSIONS = 16
MAX_BODY = 1024
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}
_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
_MISSING = (
    "<!doctype html><meta charset=utf-8><title>DriftWatch</title>"
    "<body style='font-family:sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem'>"
    "<h1>The local dashboard files are not included in this install</h1>"
    "<p>Your numbers are safe and still sync to your DriftWatch project. Reinstall the latest release to get the "
    "local page: <code>pip install --upgrade \"driftwatch-llm[agent]\"</code>. "
    "Meanwhile, <code>driftwatch agent status</code> shows what the agent is doing.</p></body>"
)


class _LoopbackServer(ThreadingHTTPServer):
    """http.server's default bind does a reverse DNS lookup (`socket.getfqdn`) just to fill in a name nobody uses. On some
    systems (macOS CI runners) that takes seconds, which made `driftwatch dashboard` time out. Skip it."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


class Provider(Protocol):
    def projects(self) -> list[str]: ...
    def series(self, project_id: str, range_name: str) -> dict[str, Any]: ...
    def status(self) -> dict[str, Any]: ...
    def touch(self) -> None: ...


def default_static_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "dashboard_static"


class DashboardServer:
    def __init__(self, provider: Provider, static_dir: Path | str | None = None) -> None:
        self._provider = provider
        self._static = Path(static_dir) if static_dir is not None else default_static_dir()
        self.token = secrets.token_urlsafe(32)
        self._token_used = False
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()
        self._allowed_hosts: set[str] = set()
        self._allowed_origins: set[str] = set()
        self._httpd: _LoopbackServer | None = None
        self._thread: threading.Thread | None = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "driftwatch"
            sys_version = ""

            def log_message(self, *_args: Any) -> None:  # no access log: paths can carry project ids
                pass

            def do_GET(self) -> None:  # noqa: N802
                outer._get(self)

            def do_POST(self) -> None:  # noqa: N802
                outer._post(self)

        self._handler_cls = Handler

    # -- lifecycle ----------------------------------------------------------------------
    @property
    def address(self) -> tuple[str, int]:
        assert self._httpd is not None
        return self._httpd.server_address[:2]  # type: ignore[return-value]

    def start(self) -> int:
        if self._httpd is not None:
            return self.address[1]
        self._httpd = _LoopbackServer(("127.0.0.1", 0), self._handler_cls)
        self._httpd.daemon_threads = True
        port = self.address[1]
        self._allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._allowed_origins = {f"http://{h}" for h in self._allowed_hosts}
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="dw-dashboard", daemon=True)
        self._thread.start()
        return port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def issue_token(self) -> str:
        """A fresh one-time token (the previous one stops working). Every `driftwatch dashboard` gets its own."""
        with self._lock:
            self.token = secrets.token_urlsafe(32)
            self._token_used = False
            return self.token

    # -- helpers ------------------------------------------------------------------------
    def _reply(self, h: BaseHTTPRequestHandler, status: int, body: bytes = b"", ctype: str = "application/json", extra: dict[str, str] | None = None) -> None:
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("Content-Security-Policy", _CSP)
        h.send_header("X-Content-Type-Options", "nosniff")
        h.send_header("Referrer-Policy", "no-referrer")
        h.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for k, v in (extra or {}).items():
            h.send_header(k, v)
        h.end_headers()
        if body and h.command != "HEAD":
            h.wfile.write(body)

    def _json(self, h: BaseHTTPRequestHandler, status: int, payload: Any, extra: dict[str, str] | None = None) -> None:
        self._reply(h, status, json.dumps(payload).encode("utf-8"), extra=extra)

    def _error(self, h: BaseHTTPRequestHandler, status: int, text: str) -> None:
        h.close_connection = True  # a body we refused to read must not be taken for the next request
        self._json(h, status, {"error": text}, extra={"Connection": "close"})

    def _origin_ok(self, h: BaseHTTPRequestHandler) -> bool:
        host = (h.headers.get("Host") or "").strip().lower()
        if host not in self._allowed_hosts:
            return False
        origin = h.headers.get("Origin")
        if origin is not None and origin.strip().lower() not in self._allowed_origins:
            return False
        fetch_site = h.headers.get("Sec-Fetch-Site")
        return fetch_site is None or fetch_site.strip().lower() in ("same-origin", "none")

    def _session_ok(self, h: BaseHTTPRequestHandler) -> bool:
        raw = h.headers.get("Cookie")
        if not raw:
            return False
        try:
            jar = cookies.SimpleCookie()
            jar.load(raw)
            sid = jar[SESSION_COOKIE].value if SESSION_COOKIE in jar else ""
        except cookies.CookieError:
            return False
        now = time.time()
        with self._lock:
            self._sessions = {s: exp for s, exp in self._sessions.items() if exp > now}
            return any(hmac.compare_digest(sid, known) for known in self._sessions) if sid else False

    # -- routes -------------------------------------------------------------------------
    def _get(self, h: BaseHTTPRequestHandler) -> None:
        if not self._origin_ok(h):
            return self._error(h, 403, "forbidden")
        parts = urlsplit(h.path)
        path = parts.path
        if path.startswith("/api/"):
            return self._api(h, path, parts.query)
        self._static_file(h, path)

    def _api(self, h: BaseHTTPRequestHandler, path: str, query: str) -> None:
        if not self._session_ok(h):
            return self._error(h, 401, "sign in through `driftwatch dashboard`")
        try:
            self._provider.touch()  # a viewer keeps the agent alive
            if path == "/api/projects":
                return self._json(h, 200, self._provider.projects())
            if path == "/api/status":
                return self._json(h, 200, self._provider.status())
            if path == "/api/series":
                params = parse_qs(query, keep_blank_values=True)
                project = params.get("project", [])
                range_name = params.get("range", [])
                if len(project) != 1 or len(range_name) != 1 or len(params) != 2:
                    return self._error(h, 400, "project and range are required, once each")
                if not _UUID.match(project[0]) or range_name[0] not in RANGES:
                    return self._error(h, 400, "bad project or range")
                return self._json(h, 200, self._provider.series(project[0].lower(), range_name[0]))
        except Exception:  # noqa: BLE001 - never leak internals to the browser
            return self._error(h, 500, "the agent could not read its data")
        self._error(h, 404, "not found")

    def _static_file(self, h: BaseHTTPRequestHandler, raw_path: str) -> None:
        path = unquote(raw_path)
        if "\\" in path or "\x00" in path or any(seg == ".." for seg in path.split("/")):
            return self._error(h, 400, "bad path")
        rel = path.lstrip("/") or "index.html"
        try:
            root = self._static.resolve()
            target = (root / rel).resolve()
            if not (target == root or root in target.parents) or not target.is_file():
                raise FileNotFoundError
        except (OSError, ValueError):
            if rel == "index.html":
                return self._reply(h, 200, _MISSING.encode("utf-8"), "text/html; charset=utf-8")
            return self._error(h, 404, "not found")
        ctype = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._reply(h, 200, target.read_bytes(), ctype)

    def _post(self, h: BaseHTTPRequestHandler) -> None:
        if not self._origin_ok(h):
            return self._error(h, 403, "forbidden")
        if urlsplit(h.path).path != "/session":
            return self._error(h, 404, "not found")
        ctype = (h.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._error(h, 415, "application/json only")
        try:
            length = int(h.headers.get("Content-Length") or 0)
        except ValueError:
            return self._error(h, 400, "bad length")
        if length < 0 or length > MAX_BODY:
            return self._error(h, 413, "too large")
        try:
            body = json.loads(h.rfile.read(length) or b"{}")
        except ValueError:
            return self._error(h, 400, "bad json")
        token = body.get("token") if isinstance(body, dict) else None
        sid = secrets.token_urlsafe(32)
        with self._lock:
            valid = isinstance(token, str) and hmac.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))
            if not valid or self._token_used:
                return self._error(h, 401, "wrong or already used token")
            self._token_used = True  # the link may have been visible in a process list: it works once
            if len(self._sessions) >= MAX_SESSIONS:
                self._sessions.pop(min(self._sessions, key=self._sessions.get))  # type: ignore[arg-type]
            self._sessions[sid] = time.time() + SESSION_TTL
        cookie = f"{SESSION_COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"
        self._reply(h, 204, b"", extra={"Set-Cookie": cookie})
