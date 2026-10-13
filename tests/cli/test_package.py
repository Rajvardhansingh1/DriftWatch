import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-q", "-w", str(out)],
        cwd=ROOT, check=True, capture_output=True,
    )
    wheels = list(out.glob("driftwatch_llm-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def test_wheel_contains_only_the_package_and_no_pth_file(wheel):
    names = zipfile.ZipFile(wheel).namelist()
    assert names
    for n in names:
        assert n.startswith("driftwatch_llm/") or n.startswith("driftwatch_llm-"), n
        assert not n.endswith(".pth"), n
    assert "driftwatch_llm/__init__.py" in names
    assert "driftwatch_llm/cli.py" in names


def test_wheel_metadata_entry_point_and_licence(wheel):
    z = zipfile.ZipFile(wheel)
    meta = next(n for n in z.namelist() if n.endswith("/METADATA"))
    text = z.read(meta).decode("utf-8")
    assert "Name: driftwatch-llm" in text
    assert "MIT" in text
    entry = z.read(next(n for n in z.namelist() if n.endswith("entry_points.txt"))).decode("utf-8")
    assert "driftwatch = driftwatch_llm.cli:app" in entry
    assert any(n.endswith("licenses/LICENSE") for n in z.namelist()), "LICENSE not shipped in the wheel"


def test_importing_the_package_touches_no_files_and_no_network(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    code = (
        "import socket\n"
        "def _no(*a, **k): raise AssertionError('network access at import')\n"
        "socket.socket.connect = _no\n"
        "import driftwatch_llm, driftwatch_llm.cli, driftwatch_llm.endpoints\n"
        "print(driftwatch_llm.__version__)\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "DRIFTWATCH_HOME": str(home)},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == __import__("driftwatch_llm").__version__
    assert list(home.iterdir()) == []


def _is_agent_extra(line: str) -> bool:
    return "extra == 'agent'" in line or 'extra == "agent"' in line


def test_wheel_ships_the_agent_capture_and_core_packages_and_declares_the_extra(wheel):
    z = zipfile.ZipFile(wheel)
    names = z.namelist()
    for needed in (
        "driftwatch_llm/agent/runtime.py", "driftwatch_llm/agent/launcher.py", "driftwatch_llm/agent/ipc.py",
        "driftwatch_llm/capture/wrappers.py", "driftwatch_llm/capture/client.py", "driftwatch_llm/autostart.py",
        "driftwatch_llm/core/events.py", "driftwatch_llm/core/scoring.py", "driftwatch_llm/_run/sitecustomize.py",
    ):
        assert needed in names, needed
    assert not any(n.endswith(".pth") for n in names)  # installing the package still adds no hook
    meta = z.read(next(n for n in names if n.endswith("/METADATA"))).decode("utf-8")
    assert "Provides-Extra: agent" in meta
    assert any(line.startswith("Requires-Dist: numpy") and _is_agent_extra(line) for line in meta.splitlines())
    assert any(line.startswith("Requires-Dist: fastembed") and _is_agent_extra(line) for line in meta.splitlines())
    # the light install must not pull the heavy packages
    core = [l for l in meta.splitlines() if l.startswith("Requires-Dist:") and "extra ==" not in l]
    assert not any("numpy" in l or "fastembed" in l for l in core)


def test_the_capture_and_hook_modules_need_only_the_standard_library():
    code = (
        "import sys\n"
        "for name in ('numpy', 'httpx', 'sqlite3', 'typer', 'keyring', 'fastembed'):\n"
        "    sys.modules[name] = None\n"
        "import driftwatch_llm.autostart, driftwatch_llm.capture.wrappers, driftwatch_llm.capture.client\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_a_built_dashboard_is_shipped_in_the_wheel_even_though_it_is_git_ignored(tmp_path):
    static = Path(__file__).resolve().parents[2] / "driftwatch_llm" / "dashboard_static"
    existed = static.exists()
    static.mkdir(exist_ok=True)
    marker = static / "index.html"
    kept = marker.read_bytes() if marker.exists() else None
    marker.write_text("<html>dashboard</html>", encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-q", "-w", str(tmp_path)],
            check=True, cwd=Path(__file__).resolve().parents[2],
        )
        names = zipfile.ZipFile(next(tmp_path.glob("driftwatch_llm-*.whl"))).namelist()
        assert "driftwatch_llm/dashboard_static/index.html" in names
    finally:
        if kept is None:
            marker.unlink()
            if not existed:
                static.rmdir()
        else:
            marker.write_bytes(kept)


def test_the_release_workflow_builds_the_dashboard_before_the_wheel():
    text = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release-cli.yml").read_text(encoding="utf-8")
    assert text.index("npm run build:local") < text.index("python -m build")
