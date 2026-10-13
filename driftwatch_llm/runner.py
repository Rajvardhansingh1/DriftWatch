"""`driftwatch run -- <command>`: run one command with capture on, without installing any .pth file."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def run_command(command: list[str], cwd: Path | str | None = None) -> int:
    shim = str(Path(__file__).resolve().parent / "_run")
    existing = os.environ.get("PYTHONPATH")
    env = {**os.environ, "PYTHONPATH": shim + (os.pathsep + existing if existing else "")}
    # A bare name (`python`) is looked up on PATH, the way a shell does. Left to subprocess on Windows, the search starts
    # in the running executable's own folder, which for a virtual environment is the base Python's: the child could be
    # a Python that does not have this package, and monitoring would silently not start.
    program = command[0]
    if program and os.sep not in program and (os.altsep is None or os.altsep not in program):
        found = shutil.which(program, path=env.get("PATH"))
        if found:
            command = [found, *command[1:]]
    return subprocess.run(command, env=env, cwd=str(cwd) if cwd else None).returncode
