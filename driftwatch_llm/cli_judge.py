"""`driftwatch key ...` and `driftwatch judge ...`: your own provider key, and the opt-in judge.

The judge grades a small sample of your app's responses. That means redacted text leaves the machine, so it is off
until you turn it on, and turning it on shows exactly what is sent and where. No command here prints a key.
"""

from __future__ import annotations

import sys
from typing import Any

import typer

from driftwatch_llm.cli import Services, _fail, _project, _svc, app
from driftwatch_llm.cli_agent import agent_for
from driftwatch_llm.judge_settings import PROVIDER_NAMES, JudgeSettings, SettingsError, read_settings, validate, write_settings
from driftwatch_llm.providerkeys import KeyError_, ProviderKeyStore

key_app = typer.Typer(help="Your own provider key, for grading with your own account.", no_args_is_help=True)
judge_app = typer.Typer(help="The opt-in judge: grades a small sample of your app's responses.", no_args_is_help=True)
app.add_typer(key_app, name="key")
app.add_typer(judge_app, name="judge")

_FREE_CONSENT = [
    "What turning the judge on does:",
    "  - about one in {every} of your app's responses (at most {per_day} a day) is redacted and cut to 1500 characters:",
    "    emails, API keys, tokens, card and phone numbers are replaced with [email], [secret] and [number] first",
    "  - that sample goes to the DriftWatch relay, which asks a small language model to grade it from 0 to 10 and",
    "    keeps nothing: not the text, not the answer",
    "  - prompts are never read or sent. Only the response sample leaves your machine.",
    "  - you get {cap} graded samples free. When they are used up the judge stops and tells you; it never switches to",
    "    another key by itself.",
    "  - the score becomes a trend line next to embedding drift; it does not raise alerts",
    "Turn it off any time with: driftwatch judge disable",
]
_OWN_CONSENT = [
    "What turning the judge on does:",
    "  - about one in {every} of your app's responses (at most {per_day} a day) is redacted and cut to 1500 characters:",
    "    emails, API keys, tokens, card and phone numbers are replaced with [email], [secret] and [number] first",
    "  - that sample is sent directly to {where} with YOUR key, so it counts against your account there; DriftWatch",
    "    does not see it",
    "  - prompts are never read or sent. Only the response sample leaves your machine.",
    "  - the score becomes a trend line next to embedding drift; it does not raise alerts",
    "Turn it off any time with: driftwatch judge disable",
]


def _keys(s: Services) -> ProviderKeyStore:
    return s.provider_keys if s.provider_keys is not None else ProviderKeyStore(home=s.home)


def _check_provider(provider: str) -> None:
    if provider not in PROVIDER_NAMES:
        _fail(f"Unknown provider. Choose one of: {', '.join(PROVIDER_NAMES)}.")


# -- key ---------------------------------------------------------------------------------------------------
@key_app.command("set")
def key_set(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="groq, openai or openai-compatible"),
    stdin: bool = typer.Option(False, "--stdin", help="Read the key from standard input (for scripts)."),
) -> None:
    """Store a provider key in your OS keychain. The key is typed or piped in, never given as an argument."""
    s = _svc(ctx)
    _check_provider(provider)
    if stdin:
        value = sys.stdin.readline().strip()
    else:
        value = typer.prompt(f"Paste your {provider} API key (input is hidden)", hide_input=True, default="", show_default=False).strip()
    try:
        where = _keys(s).save(provider, value)
    except KeyError_ as exc:
        _fail(f"Error: {exc}.")
    place = "your OS keychain" if where == "keychain" else "a private file in your user config folder"
    typer.echo(f"Stored the {provider} key in {place}. It is never printed or logged.")
    typer.echo("Use it with: driftwatch judge enable --own --provider " + provider)


@key_app.command("status")
def key_status(ctx: typer.Context) -> None:
    """Which provider keys are stored (never their values)."""
    for provider, where in _keys(_svc(ctx)).status().items():
        typer.echo(f"{provider:<18} " + ("not set" if where == "none" else f"stored in the {'keychain' if where == 'keychain' else 'private file'}"))


@key_app.command("remove")
def key_remove(ctx: typer.Context, provider: str = typer.Argument(..., help="groq, openai or openai-compatible")) -> None:
    """Delete a stored provider key."""
    _check_provider(provider)
    _keys(_svc(ctx)).delete(provider)
    typer.echo(f"Removed the {provider} key from this machine.")


# -- judge -------------------------------------------------------------------------------------------------
@judge_app.command("enable")
def judge_enable(
    ctx: typer.Context,
    own: bool = typer.Option(False, "--own", help="Grade with your own provider key instead of the free allowance."),
    provider: str = typer.Option("groq", "--provider", help="With --own: groq, openai or openai-compatible."),
    model: str | None = typer.Option(None, "--model", help="With --own: the model to grade with."),
    base_url: str | None = typer.Option(None, "--base-url", help="With --provider openai-compatible: the server address."),
    every: int = typer.Option(25, "--every", help="Grade one response in this many."),
    max_per_day: int = typer.Option(40, "--max-per-day", help="At most this many graded responses a day."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Turn the judge on. Shows exactly what leaves your machine first."""
    s = _svc(ctx)
    if own:
        _check_provider(provider)
        if provider == "openai-compatible" and (not base_url or not model):
            _fail("openai-compatible needs --base-url and --model, for example --base-url http://127.0.0.1:8080/v1 --model my-model.")
        if _keys(s).load(provider) is None:
            _fail(f"No {provider} key is stored. Run: driftwatch key set {provider}")
    else:
        root, cfg = _project(s)  # fails with "run driftwatch init" when this folder is not linked
        if s.secrets.load(cfg.project_id) is None:
            _fail("This project has no key on this machine. Run: driftwatch login")
    try:
        settings = validate(
            JudgeSettings(
                enabled=True,
                credential="own" if own else "free",
                provider=provider if own else "groq",
                model=model if own else None,
                base_url=base_url if own and provider == "openai-compatible" else None,
                sample_every=every,
                max_per_day=max_per_day,
            )
        )
    except SettingsError as exc:
        _fail(f"Error: {exc}.")
    where = {"groq": "Groq (api.groq.com)", "openai": "OpenAI (api.openai.com)"}.get(provider, settings.base_url or "your server")
    lines = _OWN_CONSENT if own else _FREE_CONSENT
    for line in lines:
        typer.echo(line.format(every=every, per_day=max_per_day, where=where, cap=50))
    if not yes:
        if not (s.interactive or sys.stdin.isatty)():
            _fail("Not turning the judge on without being asked. Run again with --yes to confirm.")
        if not typer.confirm("Turn the judge on?", default=False):
            typer.echo("Not changed.")
            raise typer.Exit(1)
    write_settings(s.home, settings)
    typer.echo("The judge is on. See what it is doing with: driftwatch judge status")


@judge_app.command("disable")
def judge_disable(ctx: typer.Context) -> None:
    """Turn the judge off. Nothing more is graded or sent."""
    s = _svc(ctx)
    current = read_settings(s.home)
    write_settings(s.home, JudgeSettings(**{**current.__dict__, "enabled": False}))
    typer.echo("The judge is off. Nothing is graded or sent.")


@judge_app.command("status")
def judge_status(ctx: typer.Context) -> None:
    """Is the judge on, with which credential, and what it has done today."""
    s = _svc(ctx)
    cfg = read_settings(s.home)
    if not cfg.enabled:
        typer.echo("judge: off (nothing is graded or sent)")
        typer.echo("Turn it on with: driftwatch judge enable")
        return
    typer.echo("judge: on")
    if cfg.credential == "free":
        typer.echo("credential: the free allowance (through the DriftWatch relay)")
    else:
        typer.echo(f"credential: your own {cfg.provider} key (sent straight to the provider)")
    typer.echo(f"sampling: one in {cfg.sample_every} responses, at most {cfg.max_per_day} a day")
    reply = agent_for(s).send({"type": "status"})
    live: Any = reply["status"].get("judge") if reply and reply.get("ok") and "status" in reply else None
    if reply is None or not reply.get("ok"):
        typer.echo("The agent is not running, so nothing is being graded right now. It starts with your app.")
        return
    if not live:
        typer.echo("The running agent is older than this command; run: driftwatch agent stop")
        return
    typer.echo(f"today: {live['scored_today']} of {live['max_per_day']} graded")
    if live.get("allowance") and cfg.credential == "free":
        typer.echo(f"free allowance left: {live['allowance']['remaining']}")
    typer.echo(f"state: {live['state']}")
    if live.get("last_error"):
        typer.echo(f"last problem: {live['last_error']}")
