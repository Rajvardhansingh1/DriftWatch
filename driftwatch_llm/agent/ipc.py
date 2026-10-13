"""Local IPC between the capture hook (or the CLI) and the agent.

- Transport: `multiprocessing.connection` over a named pipe (Windows) or a Unix socket in a private
  directory. Only `send_bytes` / `recv_bytes` are used, carrying JSON. `send` / `recv` (pickle) are never
  called, so no peer can make this process unpickle anything.
- Authentication is MUTUAL: both sides prove they know the 32-byte key in `agent/agent.key` (mode 0600),
  with different labels so a reply cannot be reflected. The client sends nothing but the handshake until the
  server has proved it holds the key, so a listener squatting on the agent's address (another local user, or
  another process) learns nothing. The handshake runs in the connection's own thread with a timeout, so a
  client that connects and says nothing cannot block anyone else (the stock `authkey=` handshake blocks the
  accept loop).
- Endpoint: a per-user directory ($XDG_RUNTIME_DIR, else a private directory under the temp dir); the client
  refuses a socket directory that is not owned by the current user or that others can write to.
- Messages: at most 64 KB, validated field by field; unknown types and bad fields get an error reply.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any, Callable

from driftwatch_llm import paths

FAMILY = "AF_PIPE" if sys.platform == "win32" else "AF_UNIX"
MAX_MESSAGE = 64 * 1024
HANDSHAKE_TIMEOUT = 5.0
IDLE_TIMEOUT = 300.0
MAX_CLIENTS = 64
MAX_SOCKET_PATH = 100
PROTOCOL_VERSION = 2  # bumps whenever messages change in a way an older agent or client cannot follow
_MAGIC = b"DW2"
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_SDK_STATUSES = {"patched", "unsupported", "skipped"}
_BASELINE_ACTIONS = {"status", "freeze", "reset"}


class ProtocolError(ValueError):
    """A message that does not follow the protocol. The text is safe to send back."""


class AuthFailed(Exception):
    """The agent refused our key, or the server could not prove it holds the key."""


class UnsafeEndpoint(Exception):
    """The agent's socket directory is not private to this user."""


# -- addresses and key ---------------------------------------------------------------------------
def agent_dir(home: Path | str | None = None) -> Path:
    return Path(home if home is not None else paths.config_dir()) / "agent"


def _home_hash(home: Path | str | None) -> str:
    """The endpoint's name. It is derived from the secret key, so nobody without the key can compute it.

    (It used to be a hash of the config path, which anyone who knew the username could predict and squat on.
    Mutual authentication already stops a squatter from learning anything; an unpredictable name also stops
    it from blocking the real agent.)
    """
    base = os.path.normcase(str(Path(home if home is not None else paths.config_dir()).resolve()))
    key = load_or_create_authkey(home)
    return hmac.new(key, b"endpoint" + base.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def address_for(home: Path | str | None = None) -> str:
    digest = _home_hash(home)
    if sys.platform == "win32":
        return rf"\\.\pipe\driftwatch-{digest}"
    path = str(_socket_dir() / f"{digest}.sock")
    if len(os.fsencode(path)) > MAX_SOCKET_PATH:  # AF_UNIX paths hold 104 bytes (macOS) or 108 (Linux)
        path = str(Path("/tmp") / f"driftwatch-{os.getuid()}" / f"{digest}.sock")
    return path


def _socket_dir() -> Path:
    """POSIX only: the per-user runtime directory when there is one, else a private directory under the temp dir."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isabs(runtime) and os.path.isdir(runtime):
        return Path(runtime) / "driftwatch"
    return Path(tempfile.gettempdir()) / f"driftwatch-{os.getuid()}"


def _socket_dir_is_safe(directory: Path) -> bool:
    """Owned by this user, a real directory (not a symlink), and not writable by group or others."""
    if os.name != "posix":
        return True
    try:
        st = os.lstat(directory)
    except FileNotFoundError:
        return True  # nothing there yet: the connect will simply fail
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and (st.st_mode & 0o022) == 0


def _read_key(path: Path) -> bytes:
    key = bytes.fromhex(path.read_text(encoding="utf-8").strip())  # ValueError while another process is writing
    if len(key) < 32:
        raise ValueError("key not ready")
    return key


def load_or_create_authkey(home: Path | str | None = None) -> bytes:
    d = agent_dir(home)
    path = d / "agent.key"
    for _ in range(100):
        try:
            return _read_key(path)
        except (FileNotFoundError, ValueError):
            pass
        d.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(d, 0o700)
        key = os.urandom(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            time.sleep(0.01)  # another process is creating it; read theirs
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key.hex() + "\n")
        return key
    raise RuntimeError("could not create the agent key")


# -- messages ------------------------------------------------------------------------------------
def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{name} must be an integer")
    return value


def _str(value: Any, name: str, low: int, high: int) -> str:
    if not isinstance(value, str) or not (low <= len(value) <= high):
        raise ProtocolError(f"{name} must be a string of {low} to {high} characters")
    return value


def _uuid(value: Any, name: str = "project_id") -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise ProtocolError(f"{name} must be a UUID")
    return value


def parse_message(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_MESSAGE:
        raise ProtocolError("message too large")
    try:
        msg = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtocolError("message is not valid JSON") from None
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a JSON object")
    kind = msg.get("type")
    out: dict[str, Any] = {"type": kind}
    if kind == "hello":
        out["pid"] = _int(msg.get("pid"), "pid")
        if "python" in msg:
            out["python"] = _str(msg["python"], "python", 0, 32)
        if "project_id" in msg:
            out["project_id"] = _uuid(msg["project_id"])
        if "sdks" in msg:
            sdks = msg["sdks"]
            if not isinstance(sdks, dict) or len(sdks) > 16:
                raise ProtocolError("sdks must be an object with at most 16 entries")
            clean = {}
            for name, info in sdks.items():
                if not isinstance(info, dict) or info.get("status") not in _SDK_STATUSES:
                    raise ProtocolError("bad sdk entry")
                clean[_str(name, "sdk name", 1, 32)] = {
                    "version": _str(info.get("version", ""), "sdk version", 0, 32),
                    "status": info["status"],
                }
            out["sdks"] = clean
    elif kind == "heartbeat":
        out["pid"] = _int(msg.get("pid"), "pid")
        if "stats" in msg:
            stats = msg["stats"]
            if not isinstance(stats, dict) or len(stats) > 8:
                raise ProtocolError("stats must be an object with at most 8 entries")
            out["stats"] = {
                _str(k, "stat name", 1, 32): _int(v, "stat value") for k, v in stats.items()
            }
    elif kind == "capture":
        out["project_id"] = _uuid(msg.get("project_id"))
        out["provider"] = _str(msg.get("provider"), "provider", 1, 32)
        model = msg.get("model")
        out["model"] = None if model is None else _str(model, "model", 0, 64)
        out["text"] = _str(msg.get("text"), "text", 1, 32_000)
        if "latency_ms" in msg:
            latency = msg["latency_ms"]
            if latency is not None and (
                isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(latency)
            ):
                raise ProtocolError("latency_ms must be a number or null")
            out["latency_ms"] = latency
    elif kind == "baseline":
        action = msg.get("action")
        if action not in _BASELINE_ACTIONS:
            raise ProtocolError("unknown baseline action")
        out["action"] = action
        out["project_id"] = _uuid(msg.get("project_id"))
    elif kind in ("status", "stop", "dashboard"):
        pass
    else:
        raise ProtocolError("unknown message type")
    return out


def _client_mac(key: bytes, server_nonce: bytes, client_nonce: bytes) -> bytes:
    return hmac.new(key, b"client" + server_nonce + client_nonce, hashlib.sha256).digest()


def _server_mac(key: bytes, server_nonce: bytes, client_nonce: bytes) -> bytes:
    return hmac.new(key, b"server" + server_nonce + client_nonce, hashlib.sha256).digest()


# -- server --------------------------------------------------------------------------------------
class IpcServer:
    def __init__(
        self,
        home: Path | str | None,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        handshake_timeout: float = HANDSHAKE_TIMEOUT,
        max_clients: int = MAX_CLIENTS,
        idle_timeout: float = IDLE_TIMEOUT,
    ) -> None:
        self._home = home
        self._handler = handler
        self._handshake_timeout = handshake_timeout
        self._max_clients = max_clients
        self._idle_timeout = idle_timeout
        self._key = load_or_create_authkey(home)
        self._address = address_for(home)
        self._stop = threading.Event()
        self._listener: Listener | None = None
        self._accept_thread: threading.Thread | None = None
        self._active = 0
        self._active_lock = threading.Lock()
        self._conns: set[Any] = set()
        self._serve_threads: set[threading.Thread] = set()

    def start(self) -> None:
        if os.name == "posix":
            sock_dir = Path(self._address).parent
            sock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not _socket_dir_is_safe(sock_dir):
                raise PermissionError("the agent socket directory is not private to this user")
            os.chmod(sock_dir, 0o700)
            try:
                os.unlink(self._address)  # a stale socket from a crashed agent (we hold the agent lock)
            except FileNotFoundError:
                pass
        self._listener = Listener(self._address, family=FAMILY)
        self._accept_thread = threading.Thread(target=self._accept_loop, name="dw-ipc-accept", daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                if self._stop.is_set():
                    return
                time.sleep(0.05)
                continue
            if self._stop.is_set():
                conn.close()
                return
            with self._active_lock:
                if self._active >= self._max_clients:
                    conn.close()
                    continue
                self._active += 1
                self._conns.add(conn)
                thread = threading.Thread(target=self._serve, args=(conn,), name="dw-ipc-client", daemon=True)
                self._serve_threads.add(thread)
            thread.start()

    def _handshake(self, conn: Any) -> bool:
        server_nonce = os.urandom(32)
        conn.send_bytes(_MAGIC + server_nonce)
        if not conn.poll(self._handshake_timeout):
            return False
        reply = conn.recv_bytes(maxlength=128)  # client nonce (32) + client MAC (32)
        if len(reply) != 64:
            conn.send_bytes(b"NO")
            return False
        client_nonce, mac = reply[:32], reply[32:]
        if not hmac.compare_digest(mac, _client_mac(self._key, server_nonce, client_nonce)):
            conn.send_bytes(b"NO")
            return False
        conn.send_bytes(b"OK" + _server_mac(self._key, server_nonce, client_nonce))  # now prove ourselves too
        return True

    def _serve(self, conn: Any) -> None:
        try:
            if not self._handshake(conn):
                return
            last = time.monotonic()
            while not self._stop.is_set():
                if not conn.poll(0.5):
                    if time.monotonic() - last > self._idle_timeout:
                        return
                    continue
                raw = conn.recv_bytes(maxlength=MAX_MESSAGE)  # raises OSError if longer: the peer is dropped
                last = time.monotonic()
                try:
                    reply = self._handler(parse_message(raw))
                except ProtocolError as exc:
                    reply = {"ok": False, "error": str(exc)}
                except Exception:  # noqa: BLE001 - never let a handler bug kill the connection loop
                    reply = {"ok": False, "error": "internal error"}
                conn.send_bytes(json.dumps(reply).encode("utf-8"))
        except (EOFError, OSError):
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            with self._active_lock:
                self._active -= 1
                self._conns.discard(conn)
                self._serve_threads.discard(threading.current_thread())

    def stop(self) -> None:
        self._stop.set()
        try:  # wake a blocked accept() with a throwaway connection
            Client(self._address, family=FAMILY).close()
        except Exception:  # noqa: BLE001
            pass
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)
        with self._active_lock:  # release every accepted connection (a Windows pipe name stays taken until then)
            conns, threads = list(self._conns), list(self._serve_threads)
        for conn in conns:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        for thread in threads:
            thread.join(timeout=2.0)
        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:  # noqa: BLE001
                pass
        if os.name == "posix":
            try:
                os.unlink(self._address)
            except OSError:
                pass


# -- client --------------------------------------------------------------------------------------
class IpcClient:
    """Sends one JSON message and returns the JSON reply, or None if the agent cannot be reached.

    `last_error` says why: "unavailable" (no agent), "auth" (key refused, or the server could not prove it holds
    the key), "unsafe" (socket directory not private), "timeout", "too_large", "error".
    """

    def __init__(self, home: Path | str | None = None, io_timeout: float = 1.0) -> None:
        self._home = home
        self._io_timeout = io_timeout
        self._authkey: bytes | None = None
        self._conn: Any = None
        self.last_error: str | None = None

    def _connect(self) -> Any:
        if self._authkey is None:
            self._authkey = load_or_create_authkey(self._home)
        address = address_for(self._home)
        if FAMILY == "AF_UNIX" and not _socket_dir_is_safe(Path(address).parent):
            raise UnsafeEndpoint
        conn = Client(address, family=FAMILY)
        try:
            if not conn.poll(self._io_timeout):
                raise TimeoutError
            challenge = conn.recv_bytes(maxlength=64)
            if not challenge.startswith(_MAGIC) or len(challenge) != len(_MAGIC) + 32:
                raise AuthFailed
            server_nonce = challenge[len(_MAGIC):]
            client_nonce = os.urandom(32)
            conn.send_bytes(client_nonce + _client_mac(self._authkey, server_nonce, client_nonce))
            if not conn.poll(self._io_timeout):
                raise TimeoutError
            reply = conn.recv_bytes(maxlength=64)
            # Nothing but the handshake has been sent so far. Only a server that knows the key can pass this.
            if len(reply) != 34 or reply[:2] != b"OK" or not hmac.compare_digest(
                reply[2:], _server_mac(self._authkey, server_nonce, client_nonce)
            ):
                raise AuthFailed
        except BaseException:
            conn.close()
            raise
        return conn

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def send(self, message: dict[str, Any]) -> dict[str, Any] | None:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_MESSAGE:
            self.last_error = "too_large"
            return None
        try:
            if self._conn is None:
                self._conn = self._connect()
            self._conn.send_bytes(data)
            if not self._conn.poll(self._io_timeout):
                raise TimeoutError
            reply = json.loads(self._conn.recv_bytes(maxlength=MAX_MESSAGE))
            self.last_error = None
            return reply  # type: ignore[no-any-return]
        except AuthFailed:
            self.last_error = "auth"
        except UnsafeEndpoint:
            self.last_error = "unsafe"
        except (FileNotFoundError, ConnectionRefusedError):
            self.last_error = "unavailable"
        except TimeoutError:
            self.last_error = "timeout"
        except Exception:  # noqa: BLE001 - a broken connection is retried on the next call
            self.last_error = "error"
        self.close()
        return None
