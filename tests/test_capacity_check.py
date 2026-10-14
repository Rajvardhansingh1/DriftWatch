import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("capacity_check", ROOT / "scripts" / "capacity_check.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)
MB = 1024 * 1024
ENV = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon", "RUNNER_SECRET": "s3cret-value"}


def report(mb):
    return {"database_bytes": mb * MB, "signal_records": 1000, "users": 12, "projects": 20}


def test_under_seventy_percent_is_ok_and_over_is_a_problem():
    assert cc.assess(report(100))[0] is True
    assert cc.assess(report(349))[0] is True
    ok, line = cc.assess(report(350))
    assert ok is False and "70%" in line and "CAPACITY.md" in line
    assert cc.assess(report(499))[0] is False


def test_main_exit_codes_and_no_secret_in_output(capsys):
    assert cc.main(ENV, lambda env: report(100)) == 0
    assert cc.main(ENV, lambda env: report(400)) == 1
    out = capsys.readouterr().out
    assert "s3cret-value" not in out and "ok database" in out and "PROBLEM database" in out


def test_without_the_secrets_it_skips_quietly_and_a_broken_report_is_a_problem(capsys):
    assert cc.main({}, lambda env: report(1)) == 0
    assert cc.main(ENV, lambda env: {"unexpected": True}) == 1
    out = capsys.readouterr().out
    assert "skipped" in out and "PROBLEM" in out


def test_the_keepalive_workflow_runs_it_with_secrets_only_in_the_environment():
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "supabase-keepalive.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["capacity"]
    assert job["environment"] == "cloud-runner" and job["permissions"] == {}
    step = next(s for s in job["steps"] if "capacity_check.py" in s.get("run", ""))
    assert "${{" not in step["run"] and set(step["env"]) == {"SUPABASE_URL", "SUPABASE_ANON_KEY", "RUNNER_SECRET"}
