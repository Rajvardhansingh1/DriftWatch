"""Checks against the LIVE DriftWatch agent. Each line is PASS, FAIL or INFO; the exit code is 1 if anything FAILs.

    python agent_testkit/check_agent.py status                      # a readable snapshot of the agent
    python agent_testkit/check_agent.py wait-embedder               # start the agent, wait until the model is loaded
    python agent_testkit/check_agent.py reset --yes                 # wipe the LOCAL agent state (not your key or config)
    python agent_testkit/check_agent.py basics --expect 260 --baseline 200
    python agent_testkit/check_agent.py privacy --marker TESTKIT-MARKER-xxxx
    python agent_testkit/check_agent.py security                     # tries to attack its own agent endpoint
    python agent_testkit/check_agent.py drift --phases phases.json  # shifted traffic must score higher than stable
    python agent_testkit/check_agent.py resilience                  # 20 simultaneous starts, then kill -9 and recover

`run_all.py` runs the whole sequence for you.
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path

from driftwatch_llm import paths
from driftwatch_llm.agent import ipc
from driftwatch_llm.project import find_project_root, read_config

failures = 0
KEY_PATTERN = re.compile(rb"dw_[0-9a-f]{10}_[0-9a-f]{64}")


def report(kind: str, name: str, detail: str = "") -> None:
    global failures
    if kind == "FAIL":
        failures += 1
    print(f"{kind:<5} {name}" + (f" -- {detail}" if detail else ""), flush=True)


def check(ok: bool, name: str, detail: str = "") -> bool:
    report("PASS" if ok else "FAIL", name, detail)
    return ok


def get_status(timeout: float = 3.0):
    reply = ipc.IpcClient(io_timeout=timeout).send({"type": "status"})
    return reply["status"] if reply and reply.get("ok") and "status" in reply else None


def project_id():
    root = find_project_root(Path.cwd())
    cfg = read_config(root) if root else None
    return cfg.project_id if cfg else None


LOCK_FILES = {"agent.lock", "spawn.lock"}  # held open by the OS lock: cannot (and need not) be read


def agent_files() -> list[Path]:
    d = ipc.agent_dir()
    return [p for p in d.rglob("*") if p.is_file() and p.name not in LOCK_FILES] if d.exists() else []


def read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def start_agent() -> bool:
    from driftwatch_llm.agent.launcher import ensure_agent

    return ensure_agent()


def stop_agent(timeout: float = 20.0) -> bool:
    ipc.IpcClient().send({"type": "stop"})
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get_status(1.0) is None:
            return True
        time.sleep(0.3)
    return False


# ---------------------------------------------------------------------------------------------------------------
def cmd_status(_args) -> None:
    st = get_status()
    if st is None:
        report("INFO", "agent", "not running")
        return
    print(json.dumps(st, indent=2))


def cmd_wait_embedder(args) -> None:
    if not check(start_agent(), "agent starts"):
        return
    started = time.time()
    deadline = started + args.timeout
    last_print = 0.0
    missing_since = None
    while time.time() < deadline:
        st = get_status(5.0)
        if st is None:
            missing_since = missing_since or time.time()
            if time.time() - missing_since > 30:
                check(False, "embedding model loaded", "the agent stopped answering")
                return
            time.sleep(1.0)
            continue
        missing_since = None
        state = st["embedder"]
        if state == "ready":
            check(True, "embedding model loaded", f"{time.time() - started:.0f}s")
            return
        if state.startswith("failed"):
            check(False, "embedding model loaded", state + '  (is the extra installed? pip install "driftwatch-llm[agent]")')
            return
        if time.time() - last_print >= 10:
            waited = time.time() - started
            print(f"      embedder: {state} ({waited:.0f}s)", flush=True)
            if waited >= 60 and last_print and int(waited) % 60 < 10:
                print("      still loading: the first run downloads about 90 MB from huggingface.co (set HF_HUB_OFFLINE=1 once it is cached)", flush=True)
            last_print = time.time()
        time.sleep(1.0)
    check(False, "embedding model loaded", f"still loading after {args.timeout:.0f}s (first run downloads about 90 MB; slow network?)")


def cmd_reset(args) -> None:
    if not args.yes:
        print("This wipes the LOCAL agent state (history, baselines). Your key and project link stay. Add --yes.")
        sys.exit(2)
    check(stop_agent(), "agent stopped")
    for p in agent_files():
        if p.name in ("agent.key", "agent.lock", "spawn.lock") or p.suffix == ".log":
            continue
        try:
            p.unlink()
        except OSError:
            pass
    left = [p.name for p in agent_files() if p.suffix in (".sqlite3", ".npz") or "sqlite3" in p.name]
    check(left == [], "local agent state wiped", ", ".join(left))


def cmd_basics(args) -> None:
    st = get_status()
    if not check(st is not None, "agent is running and reachable"):
        return
    check(st["embedder"] == "ready", "embedder ready", st["embedder"])
    patched = {n: i for c in st["clients"] for n, i in c["sdks"].items() if i["status"] == "patched"}
    check(bool(patched), "an SDK is patched in a monitored process", ", ".join(f"{n} {i['version']}" for n, i in patched.items()) or "none seen (is a client still connected? clients expire 15 s after the app exits)")
    c = st["counters"]
    check(c.get("captured", 0) >= args.expect, f"captured at least {args.expect} responses", f"captured {c.get('captured', 0)}")
    check(c.get("embed_errors", 0) == 0, "no embedding errors", str(c.get("embed_errors", 0)))
    check(c.get("invalid_events", 0) == 0, "no events failed the contract", str(c.get("invalid_events", 0)))
    lost = c.get("dropped_no_embedder", 0)
    check(lost == 0, "no response lost while the model was loading", f"{lost} lost (warm the agent first: wait-embedder)")
    check(c.get("dropped_total", 0) == 0, "no events dropped from a full outbox")
    pid = project_id()
    info = st["projects"].get(pid) if pid else None
    if info:
        b = info["baseline"]
        if args.expect >= args.baseline:
            check(b["frozen"] and b["collected"] == args.baseline, f"baseline frozen at {args.baseline}", f"{b['collected']}/{b['target']} frozen={b['frozen']}")
        else:
            check(b["collected"] == args.expect and not b["frozen"], f"baseline collecting ({args.expect}/{args.baseline})", f"{b['collected']}/{b['target']}")
        if args.expect >= args.baseline + 5:
            check(c.get("emitted", 0) >= 2, "drift values were produced", f"{c.get('emitted', 0)} events")
        parked = info.get("parked")
        if parked == "needs_login":
            report("INFO", "sync", "not logged in: events wait in the local outbox. Run `driftwatch login` to send them to your project")
        elif parked == "auth_failed":
            report("INFO", "sync", "the stored key was rejected. Run `driftwatch login`")
        else:
            report("INFO", "sync", f"pending {info['pending']}, sent so far {st['sync']['sent_total']}")
    else:
        report("INFO", "project", "no project info yet (no traffic from a linked, trusted folder?)")
    check(KEY_PATTERN.search(json.dumps(st).encode()) is None, "the status contains no project key")


def cmd_privacy(args) -> None:
    files = agent_files() + [p for p in paths.config_dir().glob("*") if p.is_file()]
    if not check(bool(files), "there are local files to scan", f"{len(files)} files under {paths.config_dir()}"):
        return
    marker = args.marker.encode()
    hits = [p.name for p in files if marker and marker in read_bytes(p)]
    check(hits == [], "the planted response text is in NO local file", ", ".join(hits) or f"scanned {len(files)} files for {args.marker}")
    key_hits = [p.name for p in agent_files() if KEY_PATTERN.search(read_bytes(p))]
    check(key_hits == [], "no project key in the agent's files", ", ".join(key_hits))
    sqlite_files = [p for p in agent_files() if p.name == "agent.sqlite3"]
    if sqlite_files:
        con = sqlite3.connect(f"file:{sqlite_files[0].as_posix()}?mode=ro", uri=True)
        meta_text = " ".join(r[0] for r in con.execute("select meta from signals"))
        payloads = " ".join(r[0] for r in con.execute("select payload from outbox"))
        con.close()
        text_like = [w for w in ("Preheat", "invoice", "refund", "oven", "plan renews") if w in meta_text or w in payloads]
        check(text_like == [], "stored signals and queued events hold numbers only", ", ".join(text_like))


def raw_handshake(conn, key: bytes) -> bool:
    snonce = conn.recv_bytes(maxlength=64)[3:]
    cnonce = os.urandom(32)
    conn.send_bytes(cnonce + hmac.new(key, b"client" + snonce + cnonce, hashlib.sha256).digest())
    reply = conn.recv_bytes(maxlength=64)
    return reply == b"OK" + hmac.new(key, b"server" + snonce + cnonce, hashlib.sha256).digest()


def cmd_security(_args) -> None:
    # 1-2: a throwaway agent with its own key, so the real one is never touched
    home = Path(tempfile.mkdtemp(prefix="dwkit_sec_"))
    seen = []
    server = ipc.IpcServer(home, lambda m: seen.append(m) or {"ok": True})
    server.start()
    try:
        bad = ipc.IpcClient(home)
        bad._authkey = b"definitely not the key"
        check(bad.send({"type": "status"}) is None and bad.last_error == "auth", "a client with the wrong key is refused")
        check(seen == [], "the refused client's message never reached the agent")
    finally:
        server.stop()

    # 3: an impostor squatting on the agent's address, answering without knowing the key
    for behaviour in ("bare OK", "random proof"):
        home2 = Path(tempfile.mkdtemp(prefix="dwkit_sq_"))
        ipc.load_or_create_authkey(home2)
        received = []

        def rogue(address=ipc.address_for(home2), behaviour=behaviour):
            try:
                conn = Listener(address, family=ipc.FAMILY).accept()
                conn.send_bytes(b"DW2" + os.urandom(32))
                conn.recv_bytes(maxlength=128)
                conn.send_bytes(b"OK" if behaviour == "bare OK" else b"OK" + os.urandom(32))
                while conn.poll(1.5):
                    received.append(conn.recv_bytes(maxlength=70000))
            except Exception:  # noqa: BLE001
                pass

        t = threading.Thread(target=rogue, daemon=True)
        t.start()
        time.sleep(0.4)
        c = ipc.IpcClient(home2)
        sent = c.send({"type": "capture", "project_id": "11111111-1111-4111-8111-111111111111", "provider": "openai", "model": "m", "text": "SECRET RESPONSE"})
        t.join(4)
        check(sent is None and c.last_error == "auth" and received == [], f"an impostor agent ({behaviour}) gets nothing", f"client said: {c.last_error}")

    # 4: the real endpoint's name cannot be computed from public facts
    home_real = paths.config_dir()
    legacy = hashlib.sha256(os.path.normcase(str(home_real.resolve())).encode()).hexdigest()
    check(legacy[:16] not in ipc.address_for() and legacy[:24] not in ipc.address_for(), "the agent's endpoint name is not derived from your username or paths")
    if os.name == "posix":
        mode = (ipc.agent_dir() / "agent.key").stat().st_mode & 0o777
        check(mode == 0o600, "the key file is private to you", oct(mode))
    else:
        report("INFO", "key file", f"on Windows it is protected by your user profile's permissions: {ipc.agent_dir() / 'agent.key'}")

    # 5-6: abuse the REAL agent (if it is running) and make sure it survives
    if get_status() is None:
        report("INFO", "abuse tests on the live agent", "skipped: the agent is not running")
        return
    junk = Client(ipc.address_for(), family=ipc.FAMILY)
    try:
        junk.recv_bytes(maxlength=64)
        junk.send_bytes(b"\x00\xffgarbage that is not a handshake")
    except Exception:  # noqa: BLE001
        pass
    junk.close()
    check(get_status() is not None, "the live agent survives a client that sends garbage")
    key = ipc.load_or_create_authkey()
    big = Client(ipc.address_for(), family=ipc.FAMILY)
    try:
        if raw_handshake(big, key):
            big.send_bytes(b"x" * (ipc.MAX_MESSAGE + 100))
            dropped = False
            try:
                big.poll(3)
                big.recv_bytes()
            except (EOFError, OSError):
                dropped = True
            check(dropped, "an oversized message gets the connection dropped")
    except Exception:  # noqa: BLE001
        check(True, "an oversized message gets the connection dropped")
    finally:
        try:
            big.close()
        except Exception:  # noqa: BLE001
            pass
    check(get_status() is not None, "the live agent is still serving after the oversized message")


def cmd_drift(args) -> None:
    phases = json.loads(Path(args.phases).read_text())
    db = ipc.agent_dir() / "agent.sqlite3"
    if not check(db.exists(), "the agent's local store exists", str(db)):
        return
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    pid = project_id()
    rows = [(ts, v, json.loads(m)) for ts, v, m in con.execute(
        "select ts, value, meta from signals where project_id = ? and signal = 'embedding_drift' order by ts", (pid,))]
    con.close()

    def within(name):
        t0, t1 = phases[name]
        return [(v, m) for ts, v, m in rows if t0 <= ts <= t1 + 5]

    stable = [v for v, m in within("stable") if m.get("window_full")]
    shift = [v for v, m in within("shift")]
    if not (check(len(stable) >= 3, "enough stable-traffic values to measure the noise floor", f"{len(stable)} full-window values")
            and check(len(shift) >= 3, "enough shifted-traffic values", f"{len(shift)} values")):
        return
    floor = statistics.fmean(stable)
    late = statistics.fmean(shift[-3:])
    report("INFO", "stable traffic (billing text)", f"mean drift {floor:.3f}, max {max(stable):.3f}")
    report("INFO", "shifted traffic (cooking text)", f"first {shift[0]:.3f}, last three average {late:.3f}")
    check(late > max(0.15, floor + args.margin), "the shifted traffic scores clearly higher than stable traffic", f"{late:.3f} vs floor {floor:.3f}")
    check(max(stable) < 0.5, "stable traffic never looked like a big drift", f"max {max(stable):.3f}")


CALLER = "import sys; from driftwatch_llm.agent.launcher import ensure_agent; sys.exit(0 if ensure_agent() else 1)"


def cmd_resilience(_args) -> None:
    if not check(start_agent(), "an agent is running to begin with"):
        return
    before = get_status()
    log = ipc.agent_dir() / "started.log"
    starts_before = len(log.read_text().split()) if log.exists() else 0
    procs = [subprocess.Popen([sys.executable, "-c", CALLER]) for _ in range(20)]
    codes = [p.wait(timeout=120) for p in procs]
    check(codes == [0] * 20, "20 simultaneous starters all get a working agent", f"exit codes {sorted(set(codes))}")
    after = get_status()
    starts_after = len(log.read_text().split()) if log.exists() else 0
    check(after is not None and after["pid"] == before["pid"], "they all share the one existing agent", f"pid {before['pid']} -> {after['pid'] if after else None}")
    check(starts_after == starts_before, "no second agent was started", f"starts {starts_before} -> {starts_after}")

    pid = project_id()
    base_before = None
    if pid:
        reply = ipc.IpcClient().send({"type": "baseline", "action": "status", "project_id": pid})
        base_before = reply.get("baseline") if reply else None
    db = ipc.agent_dir() / "agent.sqlite3"
    count_before = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True).execute("select count(*) from signals").fetchone()[0] if db.exists() else 0

    old = after["pid"]
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(old)], capture_output=True)
    else:
        os.kill(old, signal.SIGKILL)
    deadline = time.time() + 15
    while time.time() < deadline and get_status(1.0) is not None:
        time.sleep(0.2)
    check(get_status(1.0) is None, "the agent was killed hard (no clean shutdown)")
    check(start_agent(), "a new agent starts right away (no stale lock)")
    new = get_status()
    check(new is not None and new["pid"] != old, "it is a different process", f"pid {old} -> {new['pid'] if new else None}")
    if pid and base_before:
        reply = ipc.IpcClient().send({"type": "baseline", "action": "status", "project_id": pid})
        base_after = reply.get("baseline") if reply else None
        check(base_after is not None and base_after["frozen"] == base_before["frozen"] and base_after["collected"] == base_before["collected"],
              "the baseline survived the crash", f"{base_before['collected']} -> {base_after['collected'] if base_after else None} collected")
    count_after = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True).execute("select count(*) from signals").fetchone()[0] if db.exists() else 0
    check(count_after >= count_before, "the stored history survived the crash", f"{count_before} -> {count_after} values")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    w = sub.add_parser("wait-embedder")
    w.add_argument("--timeout", type=float, default=600)
    r = sub.add_parser("reset")
    r.add_argument("--yes", action="store_true")
    b = sub.add_parser("basics")
    b.add_argument("--expect", type=int, required=True, help="how many responses the traffic should have produced")
    b.add_argument("--baseline", type=int, default=200)
    pv = sub.add_parser("privacy")
    pv.add_argument("--marker", required=True)
    sub.add_parser("security")
    d = sub.add_parser("drift")
    d.add_argument("--phases", required=True)
    d.add_argument("--margin", type=float, default=0.2, help="how far above the stable floor shifted traffic must score (the hash test embedder separates less than the real model)")
    sub.add_parser("resilience")
    args = ap.parse_args()
    {
        "status": cmd_status, "wait-embedder": cmd_wait_embedder, "reset": cmd_reset, "basics": cmd_basics,
        "privacy": cmd_privacy, "security": cmd_security, "drift": cmd_drift, "resilience": cmd_resilience,
    }[args.cmd](args)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
