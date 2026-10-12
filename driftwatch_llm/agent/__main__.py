"""`python -m driftwatch_llm.agent`: the per-user agent process."""

from __future__ import annotations

import os
import sys
import time

from driftwatch_llm.agent.ipc import agent_dir
from driftwatch_llm.agent.lock import FileLock


def _record_start(directory) -> None:
    """Keep a short list of start times and pids (diagnostics). Only the lock holder writes here."""
    path = directory / "started.log"
    try:
        lines = path.read_text(encoding="utf-8").split() if path.exists() else []
        path.write_text("\n".join((lines + [str(os.getpid())])[-50:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    os.environ["DRIFTWATCH_DISABLE"] = "1"  # nothing the agent does may be captured as user traffic
    directory = agent_dir()
    lock = FileLock(directory / "agent.lock")
    if not lock.acquire():
        return 0  # another agent already runs; losing the race is normal
    try:
        from driftwatch_llm.agent.runtime import AgentRuntime, _default_embedder

        test_mode = os.environ.get("DRIFTWATCH_AGENT_TEST") == "1"
        runtime = AgentRuntime(
            embedder_factory=None if test_mode else _default_embedder,
            linger=float(os.environ.get("DRIFTWATCH_AGENT_LINGER", "30")),
        )
        _record_start(directory)  # before serving: anyone who can reach the agent can already see this entry
        runtime.start()
        try:
            while not runtime.tick():
                time.sleep(1.0)
        finally:
            runtime.shutdown()
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
