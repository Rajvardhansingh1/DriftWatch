"""agent / autostart / baseline / run commands, and the autostart question in init."""

from __future__ import annotations

from pathlib import Path

import pytest

from driftwatch_llm import cli as cli_module
from driftwatch_llm import cli_agent
from tests.cli.test_cli import KEY, PID, Env, FakeApi, runner  # noqa: F401  (shared fakes)

SECRET_TEXT = "A-RESPONSE-THAT-MUST-NEVER-BE-PRINTED"


class FakeAgent:
    def __init__(self, replies=None, absent=False):
        self.replies = replies or {}
        self.absent = absent
        self.sent = []
        self.last_error = None

    def send(self, msg):
        self.sent.append(msg)
        if self.absent:
            self.last_error = "unavailable"
            return None
        reply = self.replies.get(msg["type"], {"ok": True})
        return reply(msg) if callable(reply) else reply

    def close(self):
        pass


STATUS = {
    "agent_version": "0.2.0",
    "pid": 4242,
    "uptime_seconds": 3725.0,
    "embedder": "ready",
    "clients": [
        {"pid": 111, "python": "3.14.2", "sdks": {"openai": {"version": "3.29.0", "status": "patched"},
                                                  "anthropic": {"version": "99.0.0", "status": "unsupported"}},
         "stats": {"captured": 40, "dropped": 2, "skipped_streaming": 3, "skipped_other": 1, "errors": 0}}
    ],
    "projects": {PID: {"baseline": {"frozen": False, "collected": 37, "target": 200, "window": 0}, "pending": 5, "parked": None}},
    "sync": {"sent_total": 12, "last_success_at": 1_700_000_000.0, "last_error": None, "pending": 5, "quarantined": 1,
             "parked": {}, "dropped_total": 0},
    "counters": {"captured": 40, "emitted": 12, "embed_errors": 0, "dropped_no_embedder": 0, "ignored_empty": 1},
}


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.agent = FakeAgent({"status": {"ok": True, "status": STATUS}})
    e.services.agent_client = lambda: e.agent
    e.hook_path = tmp_path / "site-packages" / "driftwatch_llm_autostart.pth"
    e.installed = []
    e.removed = []
    e.hook_state = {"path": None}

    def install():
        e.installed.append(1)
        e.hook_state["path"] = e.hook_path
        return e.hook_path

    def remove():
        e.removed.append(1)
        had = e.hook_state["path"]
        e.hook_state["path"] = None
        return [had] if had else []

    e.services.install_hook = install
    e.services.remove_hook = remove
    e.services.hook_installed = lambda: e.hook_state["path"]
    e.services.interactive = lambda: False
    return e


# ---- agent ------------------------------------------------------------------------------------------------
def test_agent_status_when_nothing_is_running(env):
    env.agent.absent = True
    r = env.run("agent", "status")
    assert r.exit_code == 0 and "not running" in r.output.lower()
    assert "starts by itself" in r.output


def test_agent_status_shows_the_useful_facts_and_nothing_secret(env):
    r = env.run("agent", "status")
    assert r.exit_code == 0, r.output
    out = r.output
    assert "running" in out and "4242" in out and "1h 2m" in out
    assert "embedder: ready" in out
    assert "openai 3.29.0 (patched)" in out and "anthropic 99.0.0 (unsupported)" in out
    assert "37/200" in out
    assert "pending 5" in out
    assert "captured 40" in out and "streaming" in out
    assert KEY not in out and SECRET_TEXT not in out


def test_agent_status_explains_a_failed_embedder_and_a_parked_project(env):
    bad = dict(STATUS, embedder="failed: ImportError")
    bad["projects"] = {PID: {"baseline": {"frozen": True, "collected": 200, "target": 200, "window": 4}, "pending": 9, "parked": "needs_login"}}
    env.agent.replies["status"] = {"ok": True, "status": bad}
    out = env.run("agent", "status").output
    assert "driftwatch-llm[agent]" in out
    assert "driftwatch login" in out and "frozen" in out.lower()


def test_agent_stop(env):
    r = env.run("agent", "stop")
    assert r.exit_code == 0 and env.agent.sent[-1] == {"type": "stop"}
    env.agent.absent = True
    assert "not running" in env.run("agent", "stop").output.lower()


# ---- autostart --------------------------------------------------------------------------------------------------
def test_autostart_enable_asks_first_and_explains_what_it_installs(env):
    declined = env.run("autostart", "enable", input="n\n")
    assert declined.exit_code == 1 and env.installed == []
    assert "driftwatch_llm_autostart.pth" in declined.output and "only numbers" in declined.output.lower()
    r = env.run("autostart", "enable", input="y\n")
    assert r.exit_code == 0 and env.installed == [1] and str(env.hook_path) in r.output
    assert "autostart disable" in r.output


def test_autostart_enable_yes_skips_the_question_and_points_at_the_agent_extra(env, monkeypatch):
    monkeypatch.setattr(cli_agent, "agent_extra_installed", lambda: False)
    r = env.run("autostart", "enable", "--yes")
    assert r.exit_code == 0 and env.installed == [1]
    assert 'pip install "driftwatch-llm[agent]"' in r.output


def test_autostart_enable_reports_a_permission_problem_plainly(env):
    def boom():
        raise OSError("read-only")

    env.services.install_hook = boom
    r = env.run("autostart", "enable", "--yes")
    assert r.exit_code == 1 and "driftwatch run" in r.output and "Traceback" not in r.output


def test_autostart_disable(env):
    env.hook_state["path"] = env.hook_path
    r = env.run("autostart", "disable")
    assert r.exit_code == 0 and env.removed == [1] and str(env.hook_path) in r.output
    assert "was not installed" in env.run("autostart", "disable").output


# ---- baseline ---------------------------------------------------------------------------------------------------
def test_baseline_needs_a_project_and_a_running_agent(env):
    assert env.run("baseline", "status").exit_code == 1  # no project here
    env.link()
    env.agent.absent = True
    r = env.run("baseline", "status")
    assert r.exit_code == 1 and "not running" in r.output.lower()


def test_baseline_status_freeze_and_reset(env):
    env.link()
    env.agent.replies["baseline"] = lambda m: {
        "status": {"ok": True, "baseline": {"frozen": False, "collected": 37, "target": 200, "window": 0}},
        "freeze": {"ok": True, "frozen": m["project_id"] == PID and len(env.agent.sent) > 2},
        "reset": {"ok": True},
    }[m["action"]]
    out = env.run("baseline", "status").output
    assert "37/200" in out and env.agent.sent[-1] == {"type": "baseline", "action": "status", "project_id": PID}
    early = env.run("baseline", "freeze")
    assert early.exit_code == 1 and "30" in early.output  # not enough responses yet
    ok = env.run("baseline", "freeze")
    assert ok.exit_code == 0 and "frozen" in ok.output.lower()
    declined = env.run("baseline", "reset", input="n\n")
    assert declined.exit_code == 1 and env.agent.sent[-1]["action"] == "freeze"
    done = env.run("baseline", "reset", "--yes")
    assert done.exit_code == 0 and env.agent.sent[-1] == {"type": "baseline", "action": "reset", "project_id": PID}


# ---- run --------------------------------------------------------------------------------------------------------
def test_run_executes_the_command_in_a_trusted_project_and_returns_its_exit_code(env):
    env.link()
    calls = []
    env.services.run_command = lambda cmd, cwd: calls.append((cmd, cwd)) or 7
    r = env.run("run", "--", "python", "app.py", "--flag")
    assert r.exit_code == 7
    assert calls == [(["python", "app.py", "--flag"], env.project)]


def test_run_refuses_an_untrusted_or_missing_project_and_runs_nothing(env):
    calls = []
    env.services.run_command = lambda cmd, cwd: calls.append(cmd) or 0
    assert env.run("run", "--", "python", "x.py").exit_code == 1  # no project
    env.link(trusted=False)
    r = env.run("run", "--", "python", "x.py")
    assert r.exit_code == 1 and "driftwatch trust" in r.output
    assert calls == []


def test_run_without_a_command_is_a_usage_error(env):
    env.link()
    assert env.run("run").exit_code != 0


# ---- init asks about autostart ----------------------------------------------------------------------------------
def test_init_does_not_ask_when_not_interactive_and_hints_how_to_turn_it_on(env):
    r = env.run("init", "--no-browser")
    assert r.exit_code == 0 and env.installed == []
    assert "driftwatch autostart enable" in r.output


def test_init_asks_when_interactive_and_installs_on_yes(env):
    env.services.interactive = lambda: True
    r = env.run("init", "--no-browser", input="y\n")
    assert r.exit_code == 0 and env.installed == [1]


def test_init_interactive_default_is_no(env):
    env.services.interactive = lambda: True
    r = env.run("init", "--no-browser", input="\n")
    assert r.exit_code == 0 and env.installed == []


def test_init_autostart_flags_skip_the_question(env):
    env.services.interactive = lambda: True
    assert env.run("init", "--no-browser", "--autostart").exit_code == 0 and env.installed == [1]


def test_init_no_autostart_flag_never_installs_or_asks(tmp_path):
    e = Env(tmp_path)
    installed = []
    e.services.install_hook = lambda: installed.append(1)
    e.services.interactive = lambda: True
    r = e.run("init", "--no-browser", "--no-autostart")
    assert r.exit_code == 0 and installed == []


# ---- status and uninstall ------------------------------------------------------------------------------------------
def test_status_shows_autostart_and_agent_state(env):
    env.link()
    env.hook_state["path"] = env.hook_path
    out = env.run("status").output
    assert "autostart: on" in out and "agent: running" in out
    env.hook_state["path"] = None
    env.agent.absent = True
    out2 = env.run("status").output
    assert "autostart: off" in out2 and "agent: not running" in out2


def test_uninstall_stops_the_agent_and_removes_its_files(env, monkeypatch):
    monkeypatch.setattr(cli_module, "remove_autostart_hook", lambda: [])
    env.link(key=KEY)
    (env.home / "agent" / "baselines").mkdir(parents=True)
    (env.home / "agent" / "baselines" / "x.npz").write_bytes(b"x")
    (env.home / "notice.json").write_text("{}")
    r = env.run("uninstall", "--yes")
    assert r.exit_code == 0, r.output
    assert {"type": "stop"} in env.agent.sent
    assert not (env.home / "agent").exists() and not (env.home / "notice.json").exists()
