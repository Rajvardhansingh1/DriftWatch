"""Out-of-process evaluator runner (Spec_Upgrade.md section 11). Runs an
evaluator script in a child Python process - never inside the FastAPI
monitor process - with:

- wall-clock timeout (child killed on expiry),
- a scrubbed environment (no SUPABASE_*, GROQ_*, GOOGLE_*, *KEY*, *SECRET*,
  *TOKEN*, *PASSWORD* variables passed through),
- a temporary working directory,
- a stdout size cap; output must be a single JSON object and is treated
  as untrusted data (validated shape, never executed).

LIMITATION (stated, not hidden): this is process-level separation, not
strong isolation. The child still runs with the local account's filesystem
and network permissions. Spec 11.2 requires container/OS-level isolation
for cloud execution; that is NOT provided here, so cloud plugin execution
must stay disabled until a container runner exists (Phase 7 exit gate).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
SECRET_PREFIXES = ("SUPABASE_", "GROQ_", "GOOGLE_", "DATABASE_URL")
MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0


class EvaluatorError(Exception):
    """The evaluator timed out, crashed, or returned output that does not
    match the contract. Always a controlled failure, never an unhandled 500."""


@dataclass(frozen=True)
class EvaluatorResult:
    output: dict


def scrubbed_env(source: dict[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ if source is None else source)
    clean = {}
    for name, value in source.items():
        upper = name.upper()
        if upper.startswith(SECRET_PREFIXES):
            continue
        if any(marker in upper for marker in SECRET_MARKERS):
            continue
        clean[name] = value
    return clean


def run_evaluator(script: Path, payload: dict, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> EvaluatorResult:
    if not script.is_file():
        raise EvaluatorError("evaluator script not found")

    with tempfile.TemporaryDirectory(prefix="dw-eval-") as workdir:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                input=json.dumps(payload).encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                cwd=workdir,
                env=scrubbed_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise EvaluatorError("evaluator exceeded time limit") from exc

    if proc.returncode != 0:
        raise EvaluatorError(f"evaluator exited with status {proc.returncode}")
    if len(proc.stdout) > MAX_OUTPUT_BYTES:
        raise EvaluatorError("evaluator output exceeds size limit")

    try:
        output = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluatorError("evaluator output is not valid JSON") from exc
    if not isinstance(output, dict) or "score" not in output:
        raise EvaluatorError("evaluator output must be an object with a 'score' field")
    score = output["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not (0.0 <= float(score) <= 1.0):
        raise EvaluatorError("evaluator score must be a number in [0, 1]")
    return EvaluatorResult(output=output)
