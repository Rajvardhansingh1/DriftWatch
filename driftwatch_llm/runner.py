"""`driftwatch run -- <command>`: run one command with capture on, without installing any .pth file."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_command(command: list[str], cwd: Path | str | None = None) -> int:
    shim = str(Path(__file__).resolve().parent / "_run")
    existing = os.environ.get("PYTHONPATH")
    env = {**os.environ, "PYTHONPATH": shim + (os.pathsep + existing if existing else "")}
    return subprocess.run(command, env=env, cwd=str(cwd) if cwd else None).returncode
