"""The autostart hook, each case in a fresh interpreter (the hook runs at interpreter start, in every process)."""

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from driftwatch_llm import autostart
from driftwatch_llm.agent import ipc
from driftwatch_llm.hooks import AUTOSTART_PTH, install_autostart_hook, remove_autostart_hook
from driftwatch_llm.project import write_config
from driftwatch_llm.trust import TrustStore

ROOT = Path(__file__).resolve().parent.parent.parent
PID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("DRIFTWATCH_HOME", str(home))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setenv("DRIFTWATCH_AGENT_TEST", "1")
    monkeypatch.setenv("DRIFTWATCH_AGENT_LINGER", "20")
    monkeypatch.delenv("DRIFTWATCH_DISABLE", raising=False)
    yield home
    ipc.IpcClient(home).send({"type": "stop"})
    time.sleep(0.4)


def project(tmp_path, trusted):
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    write_config(proj, PID)
    if trusted:
        TrustStore().trust(proj, PID)
    return proj


def run(code, cwd, extra_env=None, timeout=60):
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], cwd=cwd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, **(extra_env or {})},
    )


def has_finder():
    return "any(type(f).__name__ == '_Finder' for f in sys.meta_path)"


# ---- the pure decision about which processes are left alone -----------------------------------------
@pytest.mark.parametrize(
    "orig_argv,skipped",
    [
        (["python", "-m", "pip", "install", "x"], True),
        (["python", "-m", "driftwatch_llm", "status"], True),
        (["python", "-m", "driftwatch_llm.agent"], True),
        (["python", r"C:\venv\Scripts\driftwatch.exe", "init"], True),
        (["python", "/venv/bin/driftwatch", "init"], True),
        (["python", "/venv/bin/pip3", "list"], True),
        (["python", "app.py"], False),
        (["python", "-c", "print(1)"], False),
        (["python", "-m", "uvicorn", "app:app"], False),
        (["python"], False),
        ([], False),
    ],
)
def test_the_cli_pip_and_the_agent_are_never_hooked(orig_argv, skipped):
    assert autostart._skipped(orig_argv) is skipped


# ---- hostile repository (C1) --------------------------------------------------------------------------
def test_an_untrusted_folder_starts_nothing_sends_nothing_and_says_so_once_a_day(env, tmp_path):
    proj = project(tmp_path, trusted=False)
    code = f"""
        import socket, subprocess, sys, threading
        def no(*a, **k): raise AssertionError('the hook touched the network or spawned a process')
        socket.socket.connect = no
        subprocess.Popen = no
        before = threading.active_count()
        import driftwatch_llm.autostart as a
        a.boot()
        assert not {has_finder()}, 'import hook installed for an untrusted folder'
        assert threading.active_count() == before
        print('quiet')
    """
    first = run(code, proj)
    assert first.returncode == 0 and first.stdout.strip() == "quiet", first.stderr
    assert len(first.stderr.strip().splitlines()) == 1 and "driftwatch trust" in first.stderr
    assert not (env / "agent").exists()  # nothing was created for an agent
    second = run(code, proj)
    assert second.returncode == 0 and second.stderr == ""  # at most one notice per day per folder


def test_a_trusted_folder_installs_the_hook_but_starts_no_thread_and_no_agent(env, tmp_path):
    proj = project(tmp_path, trusted=True)
    code = f"""
        import socket, subprocess, sys, threading
        def no(*a, **k): raise AssertionError('started something at boot')
        socket.socket.connect = no
        subprocess.Popen = no
        before = threading.active_count()
        import driftwatch_llm.autostart as a
        a.boot()
        assert {has_finder()}
        assert threading.active_count() == before
        print('hooked')
    """
    r = run(code, proj)
    assert r.returncode == 0 and r.stdout.strip() == "hooked", r.stderr
    assert r.stderr == ""


def test_a_config_pointing_somewhere_else_after_trust_is_untrusted_again(env, tmp_path):
    proj = project(tmp_path, trusted=True)
    write_config(proj, "22222222-2222-4222-8222-222222222222")  # the repo swapped the project id
    r = run(f"import driftwatch_llm.autostart as a, sys; a.boot(); print({has_finder()})", proj)
    assert r.stdout.strip() == "False"


# ---- other folders, kill switch, resilience ------------------------------------------------------------
def test_a_process_outside_any_project_is_left_completely_alone_and_cheaply(env, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    code = """
        import sys, time
        t = time.perf_counter()
        import driftwatch_llm.autostart as a
        a.boot()
        ms = (time.perf_counter() - t) * 1000
        heavy = [m for m in ('numpy', 'httpx', 'multiprocessing', 'driftwatch_llm.trust', 'driftwatch_llm.project', 'driftwatch_llm.capture.wrappers') if m in sys.modules]
        print(round(ms, 1), heavy)
    """
    r = run(code, other)
    ms, heavy = r.stdout.strip().split(" ", 1)
    assert r.returncode == 0 and float(ms) < 40 and heavy == "[]", r.stdout + r.stderr


def test_boot_in_a_trusted_project_stays_under_the_budget_and_imports_nothing_heavy(env, tmp_path):
    proj = project(tmp_path, trusted=True)
    code = """
        import sys, time
        t = time.perf_counter()
        import driftwatch_llm.autostart as a
        a.boot()
        ms = (time.perf_counter() - t) * 1000
        heavy = [m for m in ('numpy', 'httpx', 'multiprocessing', 'multiprocessing.connection', 'sqlite3') if m in sys.modules]
        print(round(ms, 1), heavy)
    """
    r = run(code, proj)
    ms, heavy = r.stdout.strip().split(" ", 1)
    assert r.returncode == 0 and float(ms) < 200 and heavy == "[]", r.stdout + r.stderr


def test_the_kill_switch_makes_boot_a_no_op(env, tmp_path):
    proj = project(tmp_path, trusted=True)
    r = run(f"import driftwatch_llm.autostart as a, sys; a.boot(); print({has_finder()})", proj, {"DRIFTWATCH_DISABLE": "1"})
    assert r.stdout.strip() == "False" and r.stderr == ""


@pytest.mark.parametrize("damage", ["trust", "config", "config-binary", "both"])
def test_boot_never_raises_even_with_corrupt_files(env, tmp_path, damage):
    proj = project(tmp_path, trusted=True)
    if damage in ("trust", "both"):
        (env / "trust.json").write_text("{{{ not json")
    if damage in ("config", "both"):
        (proj / ".driftwatch" / "config.toml").write_text("this is [ not toml")
    if damage == "config-binary":
        (proj / ".driftwatch" / "config.toml").write_bytes(b"\xff\xfe\x00\x01" * 100)
    r = run("import driftwatch_llm.autostart as a; a.boot(); print('survived')", proj)
    assert r.returncode == 0 and r.stdout.strip() == "survived", r.stderr


def test_a_project_found_from_a_subfolder_and_from_the_script_directory(env, tmp_path):
    proj = project(tmp_path, trusted=True)
    sub = proj / "src" / "pkg"
    sub.mkdir(parents=True)
    r = run(f"import driftwatch_llm.autostart as a, sys; a.boot(); print({has_finder()})", sub)
    assert r.stdout.strip() == "True"
    script = proj / "app.py"
    script.write_text(f"import driftwatch_llm.autostart as a, sys\na.boot()\nprint({has_finder()})\n")
    far = tmp_path / "far"
    far.mkdir()
    r2 = subprocess.run([sys.executable, str(script)], cwd=far, capture_output=True, text=True, env=os.environ.copy())
    assert r2.stdout.strip() == "True", r2.stderr  # cwd is elsewhere, but the script lives in the project


# ---- the .pth file ----------------------------------------------------------------------------------------
def test_install_writes_one_safe_line_and_remove_deletes_it(tmp_path):
    path = install_autostart_hook([tmp_path])
    assert path == tmp_path / AUTOSTART_PTH
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].startswith("import ")
    assert install_autostart_hook([tmp_path]) == path  # idempotent
    assert path.read_text(encoding="utf-8").splitlines() == lines
    assert remove_autostart_hook([tmp_path]) == [path] and not path.exists()


def test_the_pth_line_really_runs_the_hook_at_site_processing(env, tmp_path):
    proj = project(tmp_path, trusted=True)
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    install_autostart_hook([site_dir])
    code = f"""
        import site, sys
        site.addsitedir(r'{site_dir}')
        print({has_finder()})
    """
    r = run(code, proj)
    assert r.returncode == 0 and r.stdout.strip() == "True", r.stderr


def test_a_stale_pth_after_the_package_is_gone_is_silent(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    install_autostart_hook([site_dir])
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run(
        [sys.executable, "-S", "-c", f"import site; site.addsitedir(r'{site_dir}'); print('ok')"],
        capture_output=True, text=True, env=clean_env, cwd=tmp_path,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok" and r.stderr == ""


# ---- end to end: fake SDK -> hook -> client -> real agent process -> status ----------------------------------
def make_fake_sdk(site_dir: Path, version="3.29.0"):
    pkg = site_dir / "openai" / "resources" / "chat"
    pkg.mkdir(parents=True)
    for p in (site_dir / "openai", site_dir / "openai" / "resources", pkg):
        (p / "__init__.py").write_text("")
    (pkg / "completions.py").write_text(
        "from types import SimpleNamespace as NS\n"
        "class Completions:\n"
        "    def create(self, **kw):\n"
        "        return NS(choices=[NS(message=NS(content='an answer from the fake sdk'))], model='gpt-fake')\n"
        "class AsyncCompletions:\n"
        "    pass\n"
    )
    dist = site_dir / f"openai-{version}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: openai\nVersion: {version}\n")


def test_end_to_end_a_call_in_a_hooked_app_reaches_a_real_agent(env, tmp_path):
    proj = project(tmp_path, trusted=True)
    sdk_dir = tmp_path / "sdkpkgs"
    make_fake_sdk(sdk_dir)
    code = f"""
        import sys, time
        sys.path.insert(0, r'{sdk_dir}')
        import driftwatch_llm.autostart as a
        a.boot()
        import openai.resources.chat.completions as c   # imported AFTER boot: the import hook patches it
        out = c.Completions().create(model='asked', messages=[{{'role': 'user', 'content': 'SECRET-PROMPT-1234'}}])
        assert out.choices[0].message.content == 'an answer from the fake sdk'  # the app sees the real result
        from driftwatch_llm.capture import wrappers
        client = wrappers._sink.__self__
        deadline = time.time() + 40
        while client.stats()['sent'] < 1 and time.time() < deadline:   # a cold agent start takes a few seconds
            time.sleep(0.2)
        assert client.stats()['sent'] >= 1, client.stats()
    """
    r = run(code, proj, timeout=90)
    assert r.returncode == 0, r.stderr
    deadline = time.time() + 15
    status = None
    while time.time() < deadline:
        reply = ipc.IpcClient(env).send({"type": "status"})
        if reply and reply["status"]["counters"].get("captured", 0) >= 1:
            status = reply["status"]
            break
        time.sleep(0.3)
    assert status, "the agent never saw the call"
    # The agent knows which SDKs were patched in the app process
    assert any(c["sdks"].get("openai", {}).get("status") == "patched" for c in status["clients"]), status["clients"]
    blob = json.dumps(status)
    assert "SECRET-PROMPT-1234" not in blob and "an answer from the fake sdk" not in blob
    assert status["counters"]["buffered_while_loading"] >= 1  # test-mode agent has no embedder: kept for later, counted


def test_driftwatch_run_hooks_one_command_without_a_pth_and_chains_the_users_sitecustomize(env, tmp_path, monkeypatch):
    from driftwatch_llm.runner import run_command

    proj = project(tmp_path, trusted=True)
    user_dir = tmp_path / "user_site"
    user_dir.mkdir()
    marker = tmp_path / "user_sitecustomize_ran"
    (user_dir / "sitecustomize.py").write_text(f"open(r'{marker}', 'w').write('yes')\n")
    monkeypatch.setenv("PYTHONPATH", str(ROOT) + os.pathsep + str(user_dir))
    out = tmp_path / "child_out.txt"
    code = (
        "import sys\n"
        f"open(r'{out}', 'w').write(str(any(type(f).__name__ == '_Finder' for f in sys.meta_path)))\n"
        "sys.exit(7)\n"
    )
    assert run_command([sys.executable, "-c", code], cwd=proj) == 7  # the child's exit code comes back
    assert out.read_text() == "True"  # hooked, although no .pth is installed
    assert marker.exists()  # and the user's own sitecustomize still ran


def test_driftwatch_run_in_an_untrusted_folder_hooks_nothing(env, tmp_path):
    from driftwatch_llm.runner import run_command

    proj = project(tmp_path, trusted=False)
    out = tmp_path / "child_out.txt"
    code = f"import sys; open(r'{out}', 'w').write(str(any(type(f).__name__ == '_Finder' for f in sys.meta_path)))"
    assert run_command([sys.executable, "-c", code], cwd=proj) == 0
    assert out.read_text() == "False"
