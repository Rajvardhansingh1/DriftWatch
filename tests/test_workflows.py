"""The cloud runner's workflow is the one place that handles secrets next to users' sealed keys. Pin down its shape."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def uses(doc):
    out = []
    for job in doc["jobs"].values():
        out += [s["uses"] for s in job.get("steps", []) if "uses" in s]
    return out


def triggers(doc):
    return doc.get("on") or doc.get(True)  # YAML reads a bare `on` as True


def test_the_runner_only_runs_on_a_schedule_or_by_hand_never_from_a_pull_request():
    on = triggers(load("cloud-runner.yml"))
    assert set(on) == {"schedule", "workflow_dispatch"}
    text = (WF / "cloud-runner.yml").read_text(encoding="utf-8")
    assert "pull_request" not in text and "workflow_run" not in text


def test_the_runner_has_no_default_token_permissions_one_run_at_a_time_and_a_time_limit():
    doc = load("cloud-runner.yml")
    job = doc["jobs"]["run"]
    assert doc["permissions"] == {}
    assert doc["concurrency"]["group"] == "cloud-runner" and doc["concurrency"]["cancel-in-progress"] is False
    assert job["timeout-minutes"] <= 15
    assert job["environment"] == "cloud-runner"


def test_the_runner_does_nothing_unless_the_owner_turned_it_on():
    assert "vars.CLOUD_CONNECT == 'on'" in load("cloud-runner.yml")["jobs"]["run"]["if"]
    assert "vars.CLOUD_CONNECT == 'on'" in load("supabase-keepalive.yml")["jobs"]["runner-health"]["if"]


@pytest.mark.parametrize("name", ["cloud-runner.yml"])
def test_every_action_in_the_runner_workflow_is_pinned_to_a_full_commit(name):
    for ref in uses(load(name)):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{ref} is not pinned to a commit SHA"


def test_secrets_reach_the_runner_only_through_environment_variables_never_inside_a_command():
    doc = load("cloud-runner.yml")
    for job in doc["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), "an expression inside a run: line can be injected"
            for value in (step.get("with") or {}).values():
                assert "secrets." not in str(value)
    health = load("supabase-keepalive.yml")["jobs"]["runner-health"]
    assert health["permissions"] == {} and health["environment"] == "cloud-runner"
    for step in health["steps"]:
        assert "${{" not in step["run"]


def test_the_runner_installs_only_exactly_pinned_requirements():
    lines = [l for l in (ROOT / "requirements-runner.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert lines and all(re.fullmatch(r"[A-Za-z0-9_.\-]+==[0-9][\w.]*", l) for l in lines)
    runner_wf = (WF / "cloud-runner.yml").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir -r requirements-runner.txt" in runner_wf


def test_the_runner_prints_nothing_but_fixed_lines_and_the_workflow_does_not_echo_secrets():
    text = (WF / "cloud-runner.yml").read_text(encoding="utf-8")
    assert "echo" not in text and "set -x" not in text and "ACTIONS_STEP_DEBUG" not in text


def test_codeowners_covers_everything_that_can_touch_the_stored_keys():
    owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    for path in ("/.github/workflows/", "/monitor/cloud/", "/supabase/", "/requirements-runner.txt", "/frontend/lib/connect/"):
        assert path in owners
