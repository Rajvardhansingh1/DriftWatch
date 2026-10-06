"""Tests must never spend real provider quota (D-035). Set before any
monitor module is imported: monitor.main builds `app = create_app()` at
import time, which would otherwise construct a real Groq client whenever
a key is present in .env."""
import os

os.environ["DRIFTWATCH_FORCE_SIMULATED"] = "true"

import pytest  # noqa: E402

from monitor.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _no_supabase_url(monkeypatch):
    """Keep auth tests independent of a developer .env (issuer/JWKS paths)."""
    monkeypatch.setattr(settings, "supabase_url", "")
