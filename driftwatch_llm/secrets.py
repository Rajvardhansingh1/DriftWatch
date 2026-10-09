"""Where the project API key lives on this machine.

Lookup order: OS keychain, then the `DRIFTWATCH_API_KEY` environment variable, then a private
file (`credentials.json`, mode 0600) in the user config dir. Saving tries the keychain first and
falls back to the file when no keychain exists (Docker, CI, WSL, headless Linux).

Nothing here ever prints, logs or raises with a key in its message.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from driftwatch_llm import paths
from driftwatch_llm.fileutil import write_private

SERVICE = "driftwatch-llm"
ENV_VAR = "DRIFTWATCH_API_KEY"
KEY_RE = re.compile(r"^dw_[0-9a-f]{10}_[0-9a-f]{64}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class SecretError(ValueError):
    """Invalid input to the secret store. Messages never contain the value."""


def _default_backend() -> Any | None:
    try:
        import keyring
        from keyring.backends import fail

        kr = keyring.get_keyring()
        if isinstance(kr, fail.Keyring) or getattr(kr, "priority", 1) <= 0:
            return None
        return keyring
    except Exception:  # noqa: BLE001 - any keychain problem means "no keychain"
        return None


class SecretStore:
    def __init__(
        self,
        home: Path | None = None,
        backend: Any | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._home = Path(home) if home is not None else paths.config_dir()
        self._injected = backend is not None
        self._backend = backend
        self._env = os.environ if env is None else env

    def __repr__(self) -> str:
        return f"SecretStore(home={str(self._home)!r})"

    # -- file -----------------------------------------------------------------
    @property
    def _file(self) -> Path:
        return self._home / "credentials.json"

    def _read(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"version": 1, "keys": {}, "keychain_projects": []}
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return empty
        if not isinstance(data, dict):
            return empty
        keys = data.get("keys")
        index = data.get("keychain_projects")
        return {
            "version": 1,
            "keys": (
                {k: v for k, v in keys.items() if isinstance(k, str) and isinstance(v, str)}
                if isinstance(keys, dict)
                else {}
            ),
            "keychain_projects": [p for p in index if isinstance(p, str)] if isinstance(index, list) else [],
        }

    def _write(self, data: dict[str, Any]) -> None:
        if not data["keys"] and not data["keychain_projects"]:
            try:
                self._file.unlink()
            except OSError:
                pass
            return
        write_private(self._file, json.dumps(data, indent=2) + "\n")

    # -- keychain -------------------------------------------------------------
    def _kr(self) -> Any | None:
        if self._injected:
            return self._backend
        if self._backend is None:
            self._backend = _default_backend()
        return self._backend

    # -- public API -----------------------------------------------------------
    def save(self, project_id: str, key: str) -> str:
        """Store `key` for the project. Returns where it went: "keychain" or "file"."""
        if not isinstance(project_id, str) or not _UUID_RE.match(project_id):
            raise SecretError("invalid project id")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise SecretError("invalid API key format")
        data = self._read()
        kr = self._kr()
        if kr is not None:
            try:
                kr.set_password(SERVICE, project_id, key)
                data["keys"].pop(project_id, None)  # drop a stale file copy
                if project_id not in data["keychain_projects"]:
                    data["keychain_projects"].append(project_id)
                self._write(data)
                return "keychain"
            except Exception:  # noqa: BLE001 - never surface keychain errors: they can echo the value
                pass
        data["keys"][project_id] = key
        data["keychain_projects"] = [p for p in data["keychain_projects"] if p != project_id]
        self._write(data)
        return "file"

    def load(self, project_id: str) -> tuple[str, str] | None:
        """Return (key, source) with source in {"keychain", "env", "file"}, or None."""
        if not isinstance(project_id, str) or not _UUID_RE.match(project_id):
            return None
        kr = self._kr()
        if kr is not None:
            try:
                value = kr.get_password(SERVICE, project_id)
                if isinstance(value, str) and KEY_RE.match(value):
                    return value, "keychain"
            except Exception:  # noqa: BLE001
                pass
        env_key = (self._env.get(ENV_VAR) or "").strip()
        if KEY_RE.match(env_key):
            return env_key, "env"
        value = self._read()["keys"].get(project_id)
        if isinstance(value, str) and KEY_RE.match(value):
            return value, "file"
        return None

    def source(self, project_id: str) -> str:
        found = self.load(project_id)
        return found[1] if found else "none"

    def delete(self, project_id: str) -> None:
        """Remove this machine's stored key for the project (never touches the environment)."""
        if not isinstance(project_id, str) or not _UUID_RE.match(project_id):
            return
        kr = self._kr()
        if kr is not None:
            try:
                kr.delete_password(SERVICE, project_id)
            except Exception:  # noqa: BLE001
                pass
        data = self._read()
        data["keys"].pop(project_id, None)
        data["keychain_projects"] = [p for p in data["keychain_projects"] if p != project_id]
        self._write(data)

    def delete_all(self) -> None:
        """Remove every key this machine stored, for every project."""
        data = self._read()
        for project_id in set(data["keychain_projects"]) | set(data["keys"]):
            self.delete(project_id)
        try:
            self._file.unlink()
        except OSError:
            pass
