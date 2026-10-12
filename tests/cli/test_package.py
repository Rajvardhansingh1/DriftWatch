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
    assert r.stdout.strip() == "0.1.0"
    assert list(home.iterdir()) == []
