"""The per-project folder: `.driftwatch/config.toml` and the `.gitignore` entry.

The config file holds a project id and a mode, nothing else. It never holds an endpoint or a
secret (hardening item C1): a cloned repository can ship any config it likes, so this module
reads two keys, ignores the rest, and nothing else in the package reads the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from driftwatch_llm.validate import is_uuid

CONFIG_DIR_NAME = ".driftwatch"
CONFIG_FILE_NAME = "config.toml"
MAX_CONFIG_BYTES = 8192
_KNOWN = {"project_id", "mode"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_GITIGNORE_ENTRIES = {".driftwatch", ".driftwatch/", "/.driftwatch", "/.driftwatch/"}


class ConfigError(ValueError):
    """The project config is missing something or malformed. Messages never quote the file."""


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    mode: str
    ignored_keys: tuple[str, ...] = ()


def config_path(root: Path) -> Path:
    return Path(root) / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def write_config(root: Path, project_id: str) -> Path:
    if not is_uuid(project_id):
        raise ConfigError("project id must be a UUID")
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Written by `driftwatch init`.\n"
        "# This folder holds a project id and nothing else: no endpoint and no secret belongs here.\n"
        f'project_id = "{project_id}"\n'
        'mode = "cloud"\n',
        encoding="utf-8",
        newline="\n",
    )
    return path


def read_config(root: Path) -> ProjectConfig | None:
    path = config_path(root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise ConfigError("could not read the project config") from None
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigError("the project config is too large")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ConfigError("the project config is not valid TOML") from None
    project_id = data.get("project_id")
    if not is_uuid(project_id):
        raise ConfigError("the project config needs a project_id that is a UUID")
    if data.get("mode") != "cloud":
        raise ConfigError('the project config needs mode = "cloud"')
    ignored = sorted(
        {(k if _SAFE_NAME.match(k) else "<invalid name>") for k in data if k not in _KNOWN}
    )
    return ProjectConfig(project_id=str(project_id), mode="cloud", ignored_keys=tuple(ignored))


def find_project_root(start: Path) -> Path | None:
    """Walk up from `start` to the nearest folder that has `.driftwatch/config.toml`."""
    here = Path(start).resolve()
    for folder in (here, *here.parents):
        if config_path(folder).is_file():
            return folder
    return None


def ensure_gitignore(root: Path) -> bool:
    """Make sure `.driftwatch/` is git-ignored. Returns True if the file changed."""
    path = Path(root) / ".gitignore"
    try:
        existing = path.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        existing = ""
    if any(line.strip() in _GITIGNORE_ENTRIES for line in existing.splitlines()):
        return False
    eol = "\r\n" if "\r\n" in existing else "\n"
    prefix = "" if not existing or existing.endswith(("\n", "\r")) else eol
    path.write_bytes((existing + prefix + ".driftwatch/" + eol).encode("utf-8"))
    return True
