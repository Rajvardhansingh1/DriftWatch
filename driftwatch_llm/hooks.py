"""The optional autostart hook: one .pth file that runs `driftwatch_llm.autostart.boot()` at interpreter start.

Only an explicit opt-in (`driftwatch init` prompt or `driftwatch autostart enable`) installs it, and
`driftwatch autostart disable` / `driftwatch uninstall` remove it. The wheel itself ships no .pth file.
"""

from __future__ import annotations

import site
from pathlib import Path
from typing import Iterable

AUTOSTART_PTH = "driftwatch_llm_autostart.pth"
# One line, run by site.py at interpreter start. The try/except makes a stale file harmless: after
# `pip uninstall driftwatch-llm` the import fails silently instead of printing a traceback at every start.
PTH_LINE = (
    "import sys; exec(" + chr(34) + "try:" + chr(92) + "n import driftwatch_llm.autostart as a; a.boot()"
    + chr(92) + "nexcept Exception:" + chr(92) + "n pass" + chr(34) + ")"
)  # chr(92) is a backslash: the FILE must contain backslash-n (two characters) inside the exec string


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


def _own_site_dirs() -> list[Path]:
    """This environment's own site-packages only (never the shared user site)."""
    try:
        return [Path(d) for d in site.getsitepackages()]
    except Exception:  # noqa: BLE001
        return []


def install_autostart_hook(site_dirs: Iterable[Path] | None = None) -> Path:
    """Write the .pth file. Only called after the user explicitly opted in. Returns its path."""
    for directory in site_dirs if site_dirs is not None else _own_site_dirs():
        target = Path(directory) / AUTOSTART_PTH
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(PTH_LINE + "\n", encoding="utf-8")
            return target
        except OSError:
            continue
    raise OSError("could not write to this Python environment's site-packages directory")


def autostart_installed(site_dirs: Iterable[Path] | None = None) -> Path | None:
    for directory in site_dirs if site_dirs is not None else _own_site_dirs() + [Path(site.getusersitepackages())]:
        target = Path(directory) / AUTOSTART_PTH
        if target.is_file():
            return target
    return None
