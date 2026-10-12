"""Where the CLI keeps its per-user files (trust record, fallback credentials)."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs


def config_dir() -> Path:
    """`DRIFTWATCH_HOME` wins (tests, containers); otherwise the platform user config directory."""
    override = os.environ.get("DRIFTWATCH_HOME")
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir("driftwatch-llm", appauthor=False))
