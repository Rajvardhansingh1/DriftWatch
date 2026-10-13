"""The judge's settings: on or off, which credential, how much. Nothing secret lives here (keys are in providerkeys).

Off by default. A damaged or tampered file reads as off, never as on.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from driftwatch_llm import paths
from driftwatch_llm.fileutil import write_private

PROVIDER_NAMES = ("groq", "openai", "openai-compatible")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,79}$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class SettingsError(ValueError):
    """A setting was refused. Messages name the setting, never a value that could hold a secret."""


@dataclass(frozen=True)
class JudgeSettings:
    enabled: bool = False
    credential: str = "free"  # "free" (the relay) or "own" (a key from `driftwatch key set`)
    provider: str = "groq"  # which provider the own key is for
    model: str | None = None
    base_url: str | None = None  # only for openai-compatible
    sample_every: int = 25  # judge one response in this many
    max_per_day: int = 40


def validate(s: JudgeSettings) -> JudgeSettings:
    if s.credential not in ("free", "own"):
        raise SettingsError("credential must be free or own")
    if s.provider not in PROVIDER_NAMES:
        raise SettingsError("unknown provider")
    if isinstance(s.sample_every, bool) or not isinstance(s.sample_every, int) or not 1 <= s.sample_every <= 10_000:
        raise SettingsError("sample_every must be between 1 and 10000")
    if isinstance(s.max_per_day, bool) or not isinstance(s.max_per_day, int) or not 0 <= s.max_per_day <= 10_000:
        raise SettingsError("max_per_day must be between 0 and 10000")
    if s.model is not None and not (isinstance(s.model, str) and _MODEL.match(s.model)):
        raise SettingsError("model name is not valid")
    if s.base_url is not None:
        parts = urlsplit(s.base_url) if isinstance(s.base_url, str) else None
        ok = (
            parts is not None
            and not parts.username
            and not parts.password
            and bool(parts.hostname)
            and (parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in _LOOPBACK))
        )
        if not ok:
            raise SettingsError("base_url must be https (or http on this machine) with no credentials")
    return s


def _file(home: Path | None) -> Path:
    return (Path(home) if home is not None else paths.config_dir()) / "judge.json"


def read_settings(home: Path | None = None) -> JudgeSettings:
    try:
        raw = json.loads(_file(home).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("enabled"), bool):
            return JudgeSettings()
        names = ("enabled", "credential", "provider", "model", "base_url", "sample_every", "max_per_day")
        return validate(JudgeSettings(**{k: raw[k] for k in names if k in raw}))
    except (OSError, ValueError, TypeError, SettingsError):
        return JudgeSettings()


def write_settings(home: Path | None, s: JudgeSettings) -> None:
    validate(s)
    write_private(_file(home), json.dumps(asdict(s), indent=2) + "\n")
