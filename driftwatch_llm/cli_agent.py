"""CLI commands for the local agent: `agent`, `autostart`, `baseline` and `run`.

Registered on the same Typer app as the rest of the CLI (see the bottom of cli.py). The agent connection and
the autostart installer come from `Services`, so tests never touch a real agent or the real Python
environment.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import typer

from driftwatch_llm.cli import Services, _fail, _project, _svc, app
from driftwatch_llm.hooks import autostart_installed, install_autostart_hook, remove_autostart_hook

agent_app = typer.Typer(help="The background agent that scores your LLM calls locally.", no_args_is_help=True)
autostart_app = typer.Typer(help="Start monitoring automatically when your app runs.", no_args_is_help=True)
baseline_app = typer.Typer(help="The reference window that drift is measured against.", no_args_is_help=True)
app.add_typer(agent_app, name="agent")
app.add_typer(autostart_app, name="autostart")
app.add_typer(baseline_app, name="baseline")

EXPLAINER = [
    "This installs one small file, driftwatch_llm_autostart.pth, into this Python environment.",
    "From then on, Python programs started from a folder you have trusted watch their LLM calls:",
    "  - the text of each response goes only to a local agent on this machine, and is never stored",
    "  - only numbers (a drift score) are sent to your DriftWatch project",
    "  - prompts are never read",
    "  - nothing happens outside folders you trusted; remove it any time with `driftwatch autostart disable`",
]
NOT_RUNNING = (
    "The agent is not running. It starts by itself when an app in a trusted project makes its first LLM call "
    "(with autostart on, or under `driftwatch run`)."
)
EXTRA_HINT = 'The agent needs extra packages: pip install "driftwatch-llm[agent]"'


# -- helpers ---------------------------------------------------------------------------------------------
def agent_for(s: Services) -> Any:
    if s.agent_client is not None:
        return s.agent_client()
    from driftwatch_llm.agent.ipc import IpcClient  # deferred: keeps `driftwatch --help` quick

    return IpcClient(s.home)


def install_hook(s: Services) -> Path:
    return (s.install_hook or install_autostart_hook)()


def remove_hook(s: Services) -> list[Path]:
    return (s.remove_hook or remove_autostart_hook)()


def hook_installed(s: Services) -> Path | None:
    return (s.hook_installed or autostart_installed)()


def agent_extra_installed() -> bool:
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in ("numpy", "fastembed"))


def _uptime(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def agent_summary(s: Services) -> str:
    """One line for `driftwatch status`."""
    reply = agent_for(s).send({"type": "status"})
    if reply and reply.get("ok") and "status" in reply:
        return f"running (pid {reply['status'].get('pid')})"
    return "not running"


def offer_autostart(s: Services, flag: bool | None) -> None:
    """The question at the end of `init`. Default is no; never asked when not interactive."""
    if flag is False:
        return
    if flag is None:
        interactive = (s.interactive or sys.stdin.isatty)()
        if not interactive:
            typer.echo(
                "Monitoring is not on yet. To watch this app's LLM calls, run: driftwatch autostart enable "
                "(or: driftwatch run -- python your_app.py)"
            )
            return
        for line in EXPLAINER:
            typer.echo(line)
        if not typer.confirm("Start monitoring automatically when your Python app runs from this folder?", default=False):
            typer.echo("Skipped. You can turn it on later with: driftwatch autostart enable")
            return
    try:
        path = install_hook(s)
    except OSError:
        typer.echo("Could not turn autostart on here. You can still use: driftwatch run -- python your_app.py")
        return
    typer.echo(f"Autostart is on ({path}). Turn it off with: driftwatch autostart disable")
    if not agent_extra_installed():
        typer.echo(EXTRA_HINT)


# -- agent -----------------------------------------------------------------------------------------------
@agent_app.command("status")
def agent_status(ctx: typer.Context) -> None:
    """Show what the agent is doing. Never prints a key or any response text."""
    s = _svc(ctx)
    reply = agent_for(s).send({"type": "status"})
    if not reply or not reply.get("ok") or "status" not in reply:
        typer.echo(NOT_RUNNING)
        return
    st = reply["status"]
    typer.echo(f"agent: running (pid {st['pid']}, up {_uptime(st['uptime_seconds'])}, v{st['agent_version']})")
    embedder = st["embedder"]
    waited = st.get("embedder_loading_seconds")
    typer.echo(f"embedder: {embedder}" + (f" ({_uptime(waited)} so far)" if embedder == "loading" and waited else ""))
    if embedder == "loading" and waited and waited >= 60:
        typer.echo(
            "  Still loading. The first run downloads about 90 MB from huggingface.co; on a slow connection that can take "
            "minutes. Once the model is cached you can set HF_HUB_OFFLINE=1 to skip the network check."
        )
    if embedder.startswith("failed"):
        typer.echo(EXTRA_HINT)
    clients = st["clients"]
    typer.echo(f"clients: {len(clients)}")
    for c in clients:
        sdks = ", ".join(f"{name} {info['version']} ({info['status']})" for name, info in sorted(c["sdks"].items()))
        typer.echo(f"  pid {c['pid']}, python {c['python']}: {sdks or 'no SDKs seen yet'}")
        stats = c.get("stats") or {}
        if stats:
            typer.echo(
                f"    captured {stats.get('captured', 0)}, dropped {stats.get('dropped', 0)}, "
                f"skipped streaming {stats.get('skipped_streaming', 0)}, left early {stats.get('skipped_partial', 0)}, skipped other {stats.get('skipped_other', 0)}, "
                f"errors {stats.get('errors', 0)}"
            )
    for pid, info in st["projects"].items():
        b = info["baseline"]
        state = "frozen" if b["frozen"] else "collecting"
        typer.echo(f"project {pid}: baseline {b['collected']}/{b['target']} ({state}), window {b['window']}, pending {info['pending']}")
        if info.get("parked") == "needs_login":
            typer.echo("  waiting for a key: run `driftwatch login` in this project")
        elif info.get("parked") == "auth_failed":
            typer.echo("  the key was rejected: run `driftwatch login` to get a new one")
    sync = st["sync"]
    last = "never" if not sync.get("last_success_at") else f"{int(max(0, time.time() - sync['last_success_at']))}s ago"
    typer.echo(f"sync: sent {sync['sent_total']}, last success {last}, quarantined {sync['quarantined']}")
    if sync.get("last_error"):
        typer.echo(f"  last error: {sync['last_error']}")
    counters = st["counters"]
    typer.echo("counters: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(counters.items())))


@agent_app.command("stop")
def agent_stop(ctx: typer.Context) -> None:
    """Ask the agent to stop (it starts again by itself when needed)."""
    reply = agent_for(_svc(ctx)).send({"type": "stop"})
    typer.echo("Asked the agent to stop." if reply else "The agent is not running.")


# -- autostart -------------------------------------------------------------------------------------------
@autostart_app.command("enable")
def autostart_enable(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Install the small file that starts monitoring when your app runs."""
    s = _svc(ctx)
    for line in EXPLAINER:
        typer.echo(line)
    if not yes and not typer.confirm("Turn on autostart?", default=False):
        typer.echo("Not changed.")
        raise typer.Exit(1)
    try:
        path = install_hook(s)
    except OSError:
        _fail(
            "Could not write the autostart file here (the Python environment may be read-only). "
            "You can still monitor one run: driftwatch run -- python your_app.py"
        )
    typer.echo(f"Installed: {path}")
    typer.echo("Turn it off with: driftwatch autostart disable")
    if not agent_extra_installed():
        typer.echo(EXTRA_HINT)


@autostart_app.command("disable")
def autostart_disable(ctx: typer.Context) -> None:
    """Remove the autostart file."""
    removed = remove_hook(_svc(ctx))
    if removed:
        typer.echo("Removed: " + ", ".join(str(p) for p in removed))
    else:
        typer.echo("Autostart was not installed.")


# -- baseline --------------------------------------------------------------------------------------------
def _baseline(ctx: typer.Context, action: str) -> dict[str, Any]:
    s = _svc(ctx)
    _, cfg = _project(s)
    reply = agent_for(s).send({"type": "baseline", "action": action, "project_id": cfg.project_id})
    if reply is None:
        _fail(NOT_RUNNING)
    if not reply.get("ok"):
        _fail("The agent refused that request.")
    return reply


@baseline_app.command("status")
def baseline_status(ctx: typer.Context) -> None:
    """Show how far the baseline is."""
    b = _baseline(ctx, "status")["baseline"]
    state = "frozen" if b["frozen"] else "collecting"
    typer.echo(f"baseline: {b['collected']}/{b['target']} ({state}), window {b['window']}")


@baseline_app.command("freeze")
def baseline_freeze(ctx: typer.Context) -> None:
    """Freeze the baseline now, with the responses collected so far (at least 30)."""
    if _baseline(ctx, "freeze").get("frozen"):
        typer.echo("Baseline frozen with the responses collected so far.")
    else:
        _fail("Not enough responses yet: at least 30 are needed. Check `driftwatch agent status`.")


@baseline_app.command("reset")
def baseline_reset(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Throw the baseline away and start collecting again."""
    if not yes and not typer.confirm("Clear the baseline and start collecting again?", default=False):
        typer.echo("Cancelled.")
        raise typer.Exit(1)
    _baseline(ctx, "reset")
    typer.echo("Baseline cleared. It starts collecting again with the next responses.")


# -- run -------------------------------------------------------------------------------------------------
@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(
    ctx: typer.Context,
    command: list[str] = typer.Argument(..., help="The command to run, after `--`."),
) -> None:
    """Run one command with monitoring on (no autostart file needed)."""
    s = _svc(ctx)
    root, cfg = _project(s)
    if not s.trust.is_trusted(root, cfg.project_id):
        _fail("This folder is not trusted yet. Run `driftwatch trust` first.")
    if s.run_command is not None:
        code = s.run_command(command, s.cwd())
    else:
        from driftwatch_llm.runner import run_command

        code = run_command(command, s.cwd())
    raise typer.Exit(code)
