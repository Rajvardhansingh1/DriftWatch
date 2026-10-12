"""The optional autostart hook (installed by a later release; `uninstall` already knows how to remove it).

Only an explicit `driftwatch init` may ever install this file, and `driftwatch uninstall` removes it.
The wheel itself ships no .pth file.
"""

from __future__ import annotations

import site
from pathlib import Path
from typing import Iterable

AUTOSTART_PTH = "driftwatch_llm_autostart.pth"


def _site_dirs() -> list[Path]:
    dirs: list[str] = []
    for getter in (site.getsitepackages, lambda: [site.getusersitepackages()]):
        try:
            dirs.extend(getter())
        except Exception:  # noqa: BLE001 - some embedded or virtual environments lack these
            pass
    return [Path(d) for d in dirs]


def remove_autostart_hook(site_dirs: Iterable[Path] | None = None) -> list[Path]:
    """Delete our own .pth file from the given (or the current environment's) site directories."""
    removed: list[Path] = []
    for directory in site_dirs if site_dirs is not None else _site_dirs():
        target = Path(directory) / AUTOSTART_PTH
        try:
            if target.is_file():
                target.unlink()
                removed.append(target)
        except OSError:
            pass
    return removed
