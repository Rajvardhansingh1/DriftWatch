"""Provider API keys the user chose to give DriftWatch for grading (`driftwatch key set groq`).

Stored like the project key: OS keychain first, a private file (0600) when there is no keychain. The environment is
NOT consulted: grading sends text to a provider, so a key is only ever used because the user gave it here on purpose.
Nothing in this module prints, logs or raises with a key in its message.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from driftwatch_llm import paths
from driftwatch_llm.fileutil import write_private
from driftwatch_llm.judge_settings import PROVIDER_NAMES
from driftwatch_llm.secrets import _default_backend

SERVICE = "driftwatch-llm-provider"
PROVIDERS = PROVIDER_NAMES
_KEY_RE = re.compile(r"^[\x21-\x7e]{8,256}$")  # printable ASCII, no spaces


class KeyError_(ValueError):  # noqa: N801 - not named KeyError, to avoid shadowing the builtin
    """A key or provider name was refused. The message never contains the value."""


class ProviderKeyStore:
    def __init__(self, home: Path | None = None, backend: Any | None = None, env: Mapping[str, str] | None = None) -> None:
        self._home = Path(home) if home is not None else paths.config_dir()
        self._injected = backend is not None
        self._backend = backend
        # `env` is accepted so callers (and tests) can show it is ignored; it is never read.

    def __repr__(self) -> str:
        return f"ProviderKeyStore(home={str(self._home)!r})"

    @property
    def _file(self) -> Path:
        return self._home / "provider_keys.json"

    def _read(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"version": 1, "keys": {}, "keychain": []}
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return empty
        if not isinstance(data, dict):
            return empty
        keys, index = data.get("keys"), data.get("keychain")
        return {
            "version": 1,
            "keys": {k: v for k, v in keys.items() if k in PROVIDERS and isinstance(v, str)} if isinstance(keys, dict) else {},
            "keychain": [p for p in index if p in PROVIDERS] if isinstance(index, list) else [],
        }

    def _write(self, data: dict[str, Any]) -> None:
        if not data["keys"] and not data["keychain"]:
            try:
                self._file.unlink()
            except OSError:
                pass
            return
        write_private(self._file, json.dumps(data, indent=2) + "\n")

    def _kr(self) -> Any | None:
        if self._injected:
            return self._backend
        if self._backend is None:
            self._backend = _default_backend()
        return self._backend

    @staticmethod
    def _check(provider: str) -> None:
        if provider not in PROVIDERS:
            raise KeyError_("unknown provider")

    def save(self, provider: str, key: str) -> str:
        """Returns where the key went: "keychain" or "file"."""
        self._check(provider)
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise KeyError_("that does not look like an API key (8-256 visible characters, no spaces)")
        data = self._read()
        kr = self._kr()
        if kr is not None:
            try:
                kr.set_password(SERVICE, provider, key)
                data["keys"].pop(provider, None)
                if provider not in data["keychain"]:
                    data["keychain"].append(provider)
                self._write(data)
                return "keychain"
            except Exception:  # noqa: BLE001 - keychain errors can echo the value
                pass
        data["keys"][provider] = key
        data["keychain"] = [p for p in data["keychain"] if p != provider]
        self._write(data)
        return "file"

    def load(self, provider: str) -> tuple[str, str] | None:
        if provider not in PROVIDERS:
            return None
        kr = self._kr()
        if kr is not None:
            try:
                value = kr.get_password(SERVICE, provider)
                if isinstance(value, str) and _KEY_RE.match(value):
                    return value, "keychain"
            except Exception:  # noqa: BLE001
                pass
        value = self._read()["keys"].get(provider)
        if isinstance(value, str) and _KEY_RE.match(value):
            return value, "file"
        return None

    def source(self, provider: str) -> str:
        found = self.load(provider)
        return found[1] if found else "none"

    def status(self) -> dict[str, str]:
        return {p: self.source(p) for p in PROVIDERS}

    def delete(self, provider: str) -> None:
        self._check(provider)
        kr = self._kr()
        if kr is not None:
            try:
                kr.delete_password(SERVICE, provider)
            except Exception:  # noqa: BLE001
                pass
        data = self._read()
        data["keys"].pop(provider, None)
        data["keychain"] = [p for p in data["keychain"] if p != provider]
        self._write(data)
