"""A stand-in for DriftWatch's cloud, for testing the agent's syncing without internet, an account or a real key.

It answers the one call the agent makes (`POST /rest/v1/rpc/ingest_event`) the way the real service does, checks
every event against the real contract (driftwatch_llm.core.events.validate_event), and can misbehave on request.

    python agent_testkit/fake_ingest_server.py --port 8765            # prints the settings to point an agent at it

Point an agent at it (loopback http is accepted only in dev mode):

    DRIFTWATCH_DEV=1  DRIFTWATCH_DEV_SUPABASE_URL=http://127.0.0.1:8765  DRIFTWATCH_API_KEY=dw_...

Modes (set with `server.mode = ...`, or `POST /_control {"mode": "..."}` while it runs):
    ok          accept every valid event (a repeated event_id answers "duplicate")
    down        close the connection without answering (the internet is gone)
    error       answer 500
    slow        wait 2 s, then accept
    unauth      answer PT401 (the key was revoked)
    throttle    answer 429 with Retry-After: 3
`GET /_events` lists what was accepted (signal, value, event_id, project); it never includes a key.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODES = ("ok", "down", "error", "slow", "unauth", "throttle")


class FakeIngest:
    def __init__(self, port: int = 0, mode: str = "ok") -> None:
        self.mode = mode
        self.events: list[dict[str, Any]] = []
        self.rejected = 0
        self.attempts = 0
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: Any) -> None:  # silence
                pass

            def _send(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/_events":
                    with outer._lock:
                        self._send(200, [dict(e) for e in outer.events])
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
                    return
                if self.path != "/rest/v1/rpc/ingest_event":
                    self._send(404, {})
                    return
                outer._ingest(self, raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _ingest(self, handler: Any, raw: bytes) -> None:
        from driftwatch_llm.core.events import IngestionError, validate_event

        with self._lock:
            self.attempts += 1
        mode = self.mode
        if mode == "down":
            handler.connection.close()
            return
        if mode == "error":
            handler._send(500, {"message": "boom"})
            return
        if mode == "unauth":
            handler._send(401, {"code": "PT401", "message": "invalid key"})
            return
        if mode == "throttle":
            handler._send(429, {"message": "slow down"}, {"Retry-After": "3"})
            return
        if mode == "slow":
            time.sleep(2.0)
        try:
            body = json.loads(raw)
            event = body["p_event"]
            if not isinstance(body.get("p_api_key"), str) or not body["p_api_key"]:
                handler._send(401, {"code": "PT401", "message": "invalid key"})
                return
            validate_event(event)
        except (ValueError, KeyError, TypeError, IngestionError) as exc:
            with self._lock:
                self.rejected += 1
            handler._send(400, {"code": "PT422", "message": str(exc)[:100]})
            return
        with self._lock:
            duplicate = event["event_id"] in self._seen
            if not duplicate:
                self._seen.add(event["event_id"])
                self.events.append(
                    {k: event[k] for k in ("event_id", "signal", "value", "occurred_at", "source")} | {"meta": event.get("meta", {})}
                )
        handler._send(200, "duplicate" if duplicate else "accepted")

    def start(self) -> "FakeIngest":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def count(self, signal: str | None = None) -> int:
        with self._lock:
            return sum(1 for e in self.events if signal is None or e["signal"] == signal)

    def dev_env(self) -> dict[str, str]:
        """The environment that points an agent (or the CLI) at this server."""
        return {"DRIFTWATCH_DEV": "1", "DRIFTWATCH_DEV_SUPABASE_URL": self.url}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--mode", choices=MODES, default="ok")
    args = ap.parse_args()
    server = FakeIngest(args.port, args.mode).start()
    print(f"fake DriftWatch cloud on {server.url} (mode {server.mode}). Point an agent at it with:")
    print(f"  DRIFTWATCH_DEV=1 DRIFTWATCH_DEV_SUPABASE_URL={server.url} DRIFTWATCH_API_KEY=dw_test")
    print("Ctrl-C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
