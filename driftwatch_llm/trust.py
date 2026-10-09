"""Trust-on-first-use for project folders (hardening item C1).

A folder is trusted only when the user ran `driftwatch init` or `driftwatch trust` there. The record
is keyed by a hash of the folder's real path AND holds the project id, so a cloned repository that
ships its own `.driftwatch/config.toml` stays inactive until the user says otherwise, and a trusted
repository whose config is later changed to another project is untrusted again.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from driftwatch_llm import paths
from driftwatch_llm.fileutil import write_private
from driftwatch_llm.validate import is_uuid


class TrustStore:
    def __init__(self, home: Path | None = None) -> None:
        self._home = Path(home) if home is not None else paths.config_dir()

    @property
    def _file(self) -> Path:
        return self._home / "trust.json"

    @staticmethod
    def _key(root: Path) -> str:
        normal = os.path.normcase(str(Path(root).resolve()))
        return hashlib.sha256(normal.encode("utf-8")).hexdigest()

    def _read(self) -> dict[str, str]:
        try:
            data: Any = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        folders = data.get("folders") if isinstance(data, dict) else None
        if not isinstance(folders, dict):
            return {}
        return {k: v for k, v in folders.items() if isinstance(k, str) and isinstance(v, str)}

    def _write(self, folders: dict[str, str]) -> None:
        write_private(self._file, json.dumps({"version": 1, "folders": folders}, indent=2) + "\n")

    def is_trusted(self, root: Path, project_id: str) -> bool:
        if not is_uuid(project_id):
            return False
        return self._read().get(self._key(root)) == project_id

    def trust(self, root: Path, project_id: str) -> None:
        if not is_uuid(project_id):
            raise ValueError("invalid project id")
        folders = self._read()
        folders[self._key(root)] = project_id
        self._write(folders)

    def untrust(self, root: Path) -> None:
        folders = self._read()
        if folders.pop(self._key(root), None) is not None:
            self._write(folders)

    def clear(self) -> None:
        try:
            self._file.unlink()
        except OSError:
            pass
