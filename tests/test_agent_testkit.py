"""The agent test kit (examples/agent_testkit) runs green against the real agent, with the hash embedder.

This is the same sequence people run by hand, so the kit cannot rot: if the agent's behaviour changes, this fails."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from driftwatch_llm.project import ensure_gitignore, write_config
from driftwatch_llm.trust import TrustStore

REPO = Path(__file__).resolve().parents[1]
KIT = REPO / "examples" / "agent_testkit"
PID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def project(tmp_path):
    home = tmp_path / "home"
    proj = tmp_path / "project"
    home.mkdir()
    proj.mkdir()
    write_config(proj, PID)
    ensure_gitignore(proj)
    TrustStore(home=home).trust(proj, PID)
    env = {
        **os.environ,
        "DRIFTWATCH_HOME": str(home),
        "DRIFTWATCH_AGENT_EMBEDDER": "hash",
        "PYTHONPATH": str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "DRIFTWATCH_AGENT_LINGER": "30",  # the kit checks the agent between steps; the fixture stops it explicitly at the end
    }
    env.pop("DRIFTWATCH_API_KEY", None)
    yield proj, env
    subprocess.run([sys.executable, "-m", "driftwatch_llm", "agent", "stop"], cwd=proj, env=env, timeout=30, capture_output=True)


def test_the_kit_passes_end_to_end(project):
    proj, env = project
    r = subprocess.run(
        [sys.executable, str(KIT / "run_all.py"), "--quick"],
        cwd=proj, env=env, capture_output=True, text=True, timeout=600,
    )
    tail = "\n".join(r.stdout.splitlines()[-40:])
    assert r.returncode == 0, f"kit failed:\n{tail}\n{r.stderr[-2000:]}"
    assert "All good" in r.stdout


def test_offline_then_online_delivers_everything_once(project):
    proj, env = project
    r = subprocess.run([sys.executable, str(KIT / "offline.py")], cwd=proj, env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"offline scenario failed:\n{r.stdout[-3000:]}\n{r.stderr[-1500:]}"
    assert "ALL GOOD" in r.stdout


def test_burst_soak_and_compare_windows_run_clean(project):
    proj, env = project
    py = sys.executable

    def run(*cmd, timeout=400):
        return subprocess.run([py, *cmd], cwd=proj, env=env, capture_output=True, text=True, timeout=timeout)

    assert run(str(KIT / "check_agent.py"), "wait-embedder").returncode == 0
    burst = run(str(KIT / "burst.py"), "--n", "400", "--threads", "4")
    assert burst.returncode == 0, burst.stdout[-2500:]
    soak = run("-m", "driftwatch_llm", "run", "--", py, str(KIT / "soak.py"), "--minutes", "0.2", "--every", "0.2")
    assert soak.returncode == 0, soak.stdout[-2500:] + soak.stderr[-1500:]
    table = run(str(KIT / "compare_windows.py"))
    assert table.returncode == 0, table.stdout + table.stderr
    assert "SECRET" not in table.stdout


def test_the_local_dashboard_matches_what_the_cloud_received(project):
    proj, env = project
    r = subprocess.run([sys.executable, str(KIT / "parity.py")], cwd=proj, env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"parity failed:\n{r.stdout[-3000:]}\n{r.stderr[-1500:]}"
    assert "ALL GOOD" in r.stdout


def test_the_judge_scenario_runs_clean(project):
    proj, env = project
    r = subprocess.run([sys.executable, str(KIT / "judge.py")], cwd=proj, env=env, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, f"judge scenario failed:\n{r.stdout[-3500:]}\n{r.stderr[-1500:]}"
    assert "ALL GOOD" in r.stdout
