"""Real processes: single instance under a stampede, recovery after a hard kill, spawn backoff, child env."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from driftwatch_llm.agent import ipc
from driftwatch_llm.agent.launcher import ensure_agent

ROOT = Path(__file__).resolve().parent.parent.parent
CALLER = (
    "import sys\n"
    "from driftwatch_llm.agent.launcher import ensure_agent\n"
    "sys.exit(0 if ensure_agent() else 1)\n"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("DRIFTWATCH_HOME", str(h))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))  # the agent child does not run from the repo directory
    monkeypatch.setenv("DRIFTWATCH_AGENT_TEST", "1")  # real agent, but no embedding model download
    monkeypatch.setenv("DRIFTWATCH_AGENT_LINGER", "20")  # a leaked agent still exits on its own
    monkeypatch.delenv("DRIFTWATCH_AGENT_CMD", raising=False)
    yield h
    client = ipc.IpcClient(h)
    client.send({"type": "stop"})
    time.sleep(0.5)


def agent_pid(home):
    reply = ipc.IpcClient(home).send({"type": "status"})
    return reply["status"]["pid"] if reply else None


def started_log(home):
    p = home / "agent" / "started.log"
    return p.read_text().split() if p.exists() else []


def kill_hard(pid):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


def test_ensure_agent_starts_one_agent_and_reuses_it(home):
    assert ensure_agent() is True
    pid = agent_pid(home)
    assert pid
    assert ensure_agent() is True and agent_pid(home) == pid
    assert started_log(home) == [str(pid)]


def test_fifty_simultaneous_starters_leave_exactly_one_agent(home):
    env = {**os.environ}
    procs = [subprocess.Popen([sys.executable, "-c", CALLER], cwd=ROOT, env=env) for _ in range(50)]
    codes = [p.wait(timeout=120) for p in procs]
    assert codes == [0] * 50, codes
    pid = agent_pid(home)
    assert pid and started_log(home) == [str(pid)]


def test_the_agent_survives_its_starter_and_runs_detached(home):
    subprocess.run([sys.executable, "-c", CALLER], cwd=ROOT, check=True, timeout=60)
    time.sleep(1.0)  # the starter has exited by now
    assert agent_pid(home)


def test_a_hard_killed_agent_is_replaced(home):
    assert ensure_agent() is True
    first = agent_pid(home)
    kill_hard(first)
    deadline = time.time() + 10
    while time.time() < deadline and agent_pid(home) == first:
        time.sleep(0.1)
    assert ensure_agent() is True
    second = agent_pid(home)
    assert second and second != first
    assert started_log(home) == [str(first), str(second)]


def test_a_failing_spawn_is_not_retried_in_a_storm(home, tmp_path, monkeypatch):
    log = tmp_path / "spawned.log"
    standin = f"open(r'{log}', 'a').write('x\\n'); raise SystemExit(1)"
    monkeypatch.setenv("DRIFTWATCH_AGENT_CMD", json.dumps([sys.executable, "-c", standin]))
    assert ensure_agent() is False
    assert ensure_agent() is False
    assert ensure_agent() is False
    assert log.read_text().split() == ["x", "x"]  # one attempt and one short retry, then backed off (no storm)


def test_the_spawned_agent_runs_with_capture_disabled(home, tmp_path, monkeypatch):
    out = tmp_path / "env.json"
    standin = (
        "import json, os, sys\n"
        f"open(r'{out}', 'w').write(json.dumps({{'disable': os.environ.get('DRIFTWATCH_DISABLE'), 'home': os.environ.get('DRIFTWATCH_HOME')}}))\n"
    )
    monkeypatch.setenv("DRIFTWATCH_AGENT_CMD", json.dumps([sys.executable, "-c", standin]))
    ensure_agent()
    deadline = time.time() + 10
    while time.time() < deadline and not out.exists():
        time.sleep(0.1)
    got = json.loads(out.read_text())
    assert got["disable"] == "1" and got["home"] == str(home)


def test_a_spawn_that_loses_the_lock_to_an_agent_still_shutting_down_is_retried_not_recorded_as_a_failure(home, monkeypatch):
    """`agent stop` and an immediate app start: the old agent still holds its OS lock for a moment, so the new child exits
    at once. That must not poison the next minute with a 'failed' marker; one short retry finds the lock free."""
    from driftwatch_llm.agent import launcher

    real_spawn = launcher._spawn
    spawned = []

    def spawn(h, workdir):
        spawned.append(time.monotonic())
        if len(spawned) == 1:  # the first child dies immediately, as if it had lost the lock race
            return subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return real_spawn(h, workdir)

    monkeypatch.setattr(launcher, "_spawn", spawn)
    assert ensure_agent() is True
    assert len(spawned) == 2 and agent_pid(home)
    marker = json.loads((home / "agent" / "spawn.json").read_text())
    assert marker["ok"] is True  # no failure was recorded, so nothing is blocked for the next minute


def test_two_children_that_both_die_still_record_one_failure_and_stop_retrying(home, monkeypatch):
    from driftwatch_llm.agent import launcher

    spawned = []

    def spawn(h, workdir):
        spawned.append(1)
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    monkeypatch.setattr(launcher, "_spawn", spawn)
    assert ensure_agent() is False
    assert len(spawned) == 2  # one retry only: no storm
    assert json.loads((home / "agent" / "spawn.json").read_text())["ok"] is False
    assert ensure_agent() is False and len(spawned) == 2  # the backoff marker still holds


def test_a_caller_that_is_shutting_down_cuts_the_wait_short_and_records_no_outcome(home, monkeypatch, tmp_path):
    standin = "import time; time.sleep(30)"  # an agent that never comes up
    monkeypatch.setenv("DRIFTWATCH_AGENT_CMD", json.dumps([sys.executable, "-c", standin]))
    flag = {"stop": False}
    import threading

    threading.Timer(0.5, lambda: flag.update(stop=True)).start()
    t0 = time.monotonic()
    assert ensure_agent(cancelled=lambda: flag["stop"]) is False
    assert time.monotonic() - t0 < 3.0  # not the full 8-second wait
    assert not (home / "agent" / "spawn.json").exists()  # an unknown outcome must not block the next starter
