"""Static checks on the CLI release workflow: PyPI trusted publishing only, nothing long-lived."""
import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-cli.yml"


def _wf() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # PyYAML reads the bare key `on` as boolean True
    return data


def test_runs_only_on_cli_tags_or_by_hand():
    on = _wf()["on"]
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"tags": ["cli-v*"]}


def test_default_permissions_are_read_only_and_only_publish_and_attest_get_the_oidc_token():
    wf = _wf()
    assert wf["permissions"] == {"contents": "read"}
    assert "id-token" not in str(wf["jobs"]["build"].get("permissions", ""))  # the job that runs tests and builds has no token
    assert wf["jobs"]["publish"]["permissions"]["id-token"] == "write"
    assert {j for j, v in wf["jobs"].items() if "id-token" in str(v.get("permissions", ""))} == {"publish", "attest"}


def test_publish_uses_a_sha_pinned_action_from_the_pypi_environment_with_no_token():
    publish = _wf()["jobs"]["publish"]
    assert publish["environment"]["name"] == "pypi"
    uses = [s["uses"] for s in publish["steps"] if "uses" in s]
    pypi = [u for u in uses if u.startswith("pypa/gh-action-pypi-publish@")]
    assert len(pypi) == 1 and re.fullmatch(r"pypa/gh-action-pypi-publish@[0-9a-f]{40}", pypi[0]), pypi
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"password\s*:|PYPI_API_TOKEN|PYPI_TOKEN|secrets\.", text, re.I)
    assert publish["needs"] == "build"


def test_build_runs_the_cli_tests_before_building_and_uploads_dist():
    steps = _wf()["jobs"]["build"]["steps"]
    runs = [s.get("run", "") for s in steps]
    test_at = next(i for i, r in enumerate(runs) if "pytest tests/cli" in r)
    build_at = next(i for i, r in enumerate(runs) if "python -m build" in r)
    assert test_at < build_at
    assert any(s.get("uses", "").startswith("actions/upload-artifact@") for s in steps)


def test_the_tag_must_match_the_package_version_before_anything_is_published():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "driftwatch_llm/__init__.py" in text and "GITHUB_REF_NAME" in text


def test_every_release_job_after_the_build_uses_only_sha_pinned_actions():
    wf = _wf()
    for name in ("publish", "attest"):
        for step in wf["jobs"][name]["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), f"{name}: {step['uses']} is not pinned to a commit"


def test_the_release_makes_an_sbom_attests_provenance_and_audits_the_wheel_dependencies():
    wf = _wf()
    runs = " ".join(s.get("run", "") for s in wf["jobs"]["build"]["steps"])
    assert "cyclonedx-py" in runs and "sbom.cdx.json" in runs and "pip-audit" in runs
    uploads = [s["with"]["name"] for s in wf["jobs"]["build"]["steps"] if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert uploads == ["dist", "sbom"]
    attest = wf["jobs"]["attest"]
    assert attest["needs"] == "build" and attest["permissions"]["attestations"] == "write"
    assert any(s.get("uses", "").startswith("actions/attest-build-provenance@") for s in attest["steps"])
    audit = next(s for s in wf["jobs"]["build"]["steps"] if "pip-audit" in s.get("run", "") and "install" not in s.get("run", ""))
    assert audit.get("continue-on-error") is True  # reported, never a reason to block a fix
