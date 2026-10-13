"""A stand-in for DriftWatch's free-allowance relay, so the judge can be tested end to end with no account, no
internet and no provider quota.

    python agent_testkit/fake_relay.py --port 8766

Point an agent at it (loopback http is accepted only in dev mode):

    DRIFTWATCH_DEV=1  DRIFTWATCH_DEV_RELAY_URL=http://127.0.0.1:8766

It speaks `POST /v1/judge` the way the real relay does (same body rules, same status codes) and records every request,
so a test can check exactly what the agent sent. Modes (set `server.mode`, or `POST /_control {"mode": ...}`):
    ok          grade and answer 200, counting against a cap (default 50), then 429 "allowance used"
    exhausted   answer 429 "The free allowance is used..."
    unauth      answer 401
    unverified  answer 403
    slow        wait 3 s (a cold start), then behave like ok
    error       answer 500
    unscorable  answer 502 (the provider's answer was unusable)
`GET /_requests` lists what arrived (text, fields, whether the key looked right); it never includes the key itself.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODES = ("ok", "exhausted", "unauth", "unverified", "slow", "error", "unscorable")
KEY = re.compile(r"^dw_[0-9a-f]{10}_[0-9a-f]{64}$")


class FakeRelay:
    def __init__(self, port: int = 0, mode: str = "ok", cap: int = 50) -> None:
        self.mode = mode
        self.cap = cap
        self.used = 0
        self.requests: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: Any) -> None:
                pass

            def _send(self, status: int, body: Any) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/_requests":
                    with outer._lock:
                        self._send(200, list(outer.requests))
                else:
                    self._send(404, {})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                if self.path == "/_control":
                    mode = json.loads(raw or b"{}").get("mode")
                    if mode in MODES:
                        outer.mode = mode
                    self._send(200, {"mode": outer.mode})
                elif self.path == "/v1/judge":
                    outer._judge(self, raw)
                else:
                    self._send(404, {})

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _judge(self, h: Any, raw: bytes) -> None:
        auth = h.headers.get("authorization") or ""
        key = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        record: dict[str, Any] = {"key_ok": bool(KEY.match(key)), "fields": None, "text": None, "mode": self.mode}
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError
            record["fields"] = sorted(body)
            record["text"] = body.get("text")
            uuid.UUID(str(body.get("idempotency_key")))
            valid = set(body) == {"text", "idempotency_key"} and isinstance(body["text"], str) and 0 < len(body["text"]) <= 4000
        except (ValueError, TypeError):
            valid = False
        with self._lock:
            self.requests.append(record)
        if not record["key_ok"]:
            return h._send(401, {"detail": "The project key was not accepted."})
        if not valid:
            return h._send(422, {"detail": "The request was not valid."})
        mode = self.mode
        if mode == "slow":
            time.sleep(3.0)
            mode = "ok"
        if mode == "unauth":
            return h._send(401, {"detail": "The project key was not accepted."})
        if mode == "unverified":
            return h._send(403, {"detail": "Verify your email address to use the free allowance."})
        if mode == "error":
            return h._send(500, {"detail": "boom"})
        if mode == "unscorable":
            return h._send(502, {"detail": "The judge could not score that response. Nothing was counted."})
        with self._lock:
            idem = str(body["idempotency_key"])
            if mode == "exhausted" or self.used >= self.cap:
                return h._send(429, {"detail": "The free allowance is used. Add your own key to keep going."})
            if idem in self._seen:
                return h._send(409, {"detail": "That request was already handled."})
            self._seen.add(idem)
            self.used += 1
            remaining = self.cap - self.used
        # a plausible grade: longer, sentence-like answers score a little higher
        score = min(0.95, 0.5 + len(body["text"].split()) / 100.0)
        h._send(200, {"score": round(score, 2), "remaining": remaining})

    def start(self) -> "FakeRelay":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def dev_env(self) -> dict[str, str]:
        return {"DRIFTWATCH_DEV": "1", "DRIFTWATCH_DEV_RELAY_URL": self.url}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--mode", choices=MODES, default="ok")
    ap.add_argument("--cap", type=int, default=50)
    args = ap.parse_args()
    server = FakeRelay(args.port, args.mode, args.cap).start()
    print(f"fake relay on {server.url} (mode {server.mode}). Point an agent at it with:")
    print(f"  DRIFTWATCH_DEV=1 DRIFTWATCH_DEV_RELAY_URL={server.url}")
    print("Ctrl-C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
