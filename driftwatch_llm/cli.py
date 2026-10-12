"""The `driftwatch` command.

Nothing runs in the background yet. These commands link a project folder to a DriftWatch project
(init, login, logout, trust, status) and clean up (uninstall). Services (API client, keychain, trust
store, clock) are injected through the Typer context so tests need no network and no real keychain.
"""

from __future__ import annotations

import platform
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn

import typer

from driftwatch_llm import __version__, paths
from driftwatch_llm.api import Api, ApiError, PollResult
from driftwatch_llm.device_flow import LoginDenied, LoginExpired, LoginFailed, run_device_login
from driftwatch_llm.endpoints import EndpointError, Endpoints, resolve
from driftwatch_llm.hooks import remove_autostart_hook
from driftwatch_llm.project import (
    ConfigError,
    ProjectConfig,
    ensure_gitignore,
    find_project_root,
    read_config,
    write_config,
)
from driftwatch_llm.secrets import SecretStore
from driftwatch_llm.trust import TrustStore
from driftwatch_llm.validate import clean_text

app = typer.Typer(
    help="DriftWatch: link a project folder to drift monitoring.",
    no_args_is_help=True,
    add_completion=False,
)


@dataclass
class Services:
    endpoints: Endpoints
    api: Any
    secrets: SecretStore
    trust: TrustStore
    home: Path
    cwd: Callable[[], Path] = Path.cwd
    open_url: Callable[[str], object] | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    device_name: str | None = None
    device_os: str | None = None
    # Local agent and autostart (None means the real thing; tests inject fakes)
    agent_client: Callable[[], Any] | None = None
    install_hook: Callable[[], Path] | None = None
    remove_hook: Callable[[], list[Path]] | None = None
    hook_installed: Callable[[], Path | None] | None = None
    run_command: Callable[[list[str], Path | None], int] | None = None
    interactive: Callable[[], bool] | None = None


def build_services(dev: bool, env: Mapping[str, str] | None = None) -> Services:
    endpoints = resolve(dev, env)
    home = paths.config_dir()
    return Services(
        endpoints=endpoints,
        api=Api(endpoints),
        secrets=SecretStore(home=home),
        trust=TrustStore(home=home),
        home=home,
    )


def _version(value: bool) -> None:
    if value:
        typer.echo(f"driftwatch-llm {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Show the version and exit."),
    dev: bool = typer.Option(False, "--dev", hidden=True, help="Use DRIFTWATCH_DEV_* endpoints (development only)."),
) -> None:
    """DriftWatch: link a project folder to drift monitoring."""
    if ctx.obj is None:
        try:
            ctx.obj = build_services(dev)
        except EndpointError as exc:
            typer.echo(f"Error: {exc}.", err=True)
            raise typer.Exit(2) from None


def _svc(ctx: typer.Context) -> Services:
    return ctx.obj  # type: ignore[no-any-return]


def _fail(message: str, code: int = 1) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _device_name(s: Services) -> str:
    return s.device_name or clean_text(platform.node()) or "unknown device"


def _device_os(s: Services) -> str:
    return s.device_os or clean_text(f"{platform.system()} {platform.release()}") or "unknown OS"


def _device_login(s: Services, open_browser: bool) -> PollResult:
    try:
        return run_device_login(
            s.api,
            device_name=_device_name(s),
            device_os=_device_os(s),
            web_origin=s.endpoints.web_origin,
            open_browser=open_browser,
            echo=typer.echo,
            open_url=s.open_url,
            sleep=s.sleep,
            clock=s.clock,
        )
    except KeyboardInterrupt:
        typer.echo("Cancelled.")
        raise typer.Exit(130) from None
    except (LoginDenied, LoginExpired, LoginFailed, ApiError) as exc:
        _fail(f"Error: {exc}")


def _revoke_quietly(s: Services, key: str) -> None:
    try:
        s.api.revoke_api_key(key)
    except Exception:  # noqa: BLE001 - best effort; the key is also visible on the keys page
        pass


def _read_config(root: Path) -> ProjectConfig:
    try:
        cfg = read_config(root)
    except ConfigError as exc:
        _fail(f"Error: {exc}.")
    if cfg is None:
        _fail("Error: no .driftwatch/config.toml here.")
    return cfg


def _project(s: Services) -> tuple[Path, ProjectConfig]:
    root = find_project_root(s.cwd())
    if root is None:
        _fail("No DriftWatch project here. Run `driftwatch init` first.")
    return root, _read_config(root)


def _store_key(s: Services, project_id: str, key: str) -> str:
    """Save the new key, then revoke the key it replaces (never one that came from the environment)."""
    previous = s.secrets.load(project_id)
    where = s.secrets.save(project_id, key)
    if previous and previous[1] != "env" and previous[0] != key:
        _revoke_quietly(s, previous[0])
    return where


@app.command()
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Link this folder again, even if it already has a config."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the link instead of opening a browser."),
    autostart: bool | None = typer.Option(
        None, "--autostart/--no-autostart", help="Turn automatic monitoring on or off without asking."
    ),
) -> None:
    """Sign in through your browser and link this folder to a DriftWatch project."""
    s = _svc(ctx)
    root = s.cwd()
    try:
        cfg = read_config(root)
    except ConfigError as exc:
        _fail(f"Error: {exc}.")
    if cfg is not None and not force:
        if s.trust.is_trusted(root, cfg.project_id):
            typer.echo(f"Already linked to project {cfg.project_id}. Use --force to link again.")
            return
        _fail(
            f"This folder already has a .driftwatch/config.toml for project {cfg.project_id}, "
            "but you have not trusted it.\n"
            "  To use that project, run: driftwatch trust\n"
            "  To link this folder to a project of your own, run: driftwatch init --force"
        )

    typer.echo(
        "This will:\n"
        "  - sign you in through your browser\n"
        "  - write .driftwatch/config.toml (a project id, nothing else)\n"
        "  - add .driftwatch/ to .gitignore\n"
        "  - store a project key in your OS keychain (or a private file if there is none)\n"
        "  - mark this folder as trusted\n"
        "Nothing runs in the background yet."
    )
    result = _device_login(s, open_browser=not no_browser)
    assert result.api_key and result.project_id  # guaranteed by the client for "approved"

    try:
        write_config(root, result.project_id)
        ensure_gitignore(root)
        where = _store_key(s, result.project_id, result.api_key)
        s.trust.trust(root, result.project_id)
    except (OSError, ConfigError):
        _revoke_quietly(s, result.api_key)
        s.secrets.delete(result.project_id)
        _fail("Error: could not save the link on this machine. The new key was revoked. Check the folder permissions and try again.")

    place = "your OS keychain" if where == "keychain" else "a private file in your user config folder"
    typer.echo(f'Linked to project "{result.project_name}" ({result.project_id}).')
    typer.echo(f"Key stored in {place}.")
    offer_autostart(s, autostart)


@app.command()
def login(
    ctx: typer.Context,
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the link instead of opening a browser."),
) -> None:
    """Get a fresh key for this folder's project (for example on a new machine)."""
    s = _svc(ctx)
    root, cfg = _project(s)
    if not s.trust.is_trusted(root, cfg.project_id):
        _fail("This folder is not trusted yet. Run `driftwatch trust` first.")
    result = _device_login(s, open_browser=not no_browser)
    assert result.api_key and result.project_id
    if result.project_id != cfg.project_id:
        _revoke_quietly(s, result.api_key)
        _fail(
            "You approved a different project than the one this folder is linked to. Nothing changed.\n"
            "To link this folder to that project instead, run: driftwatch init --force"
        )
    _store_key(s, cfg.project_id, result.api_key)
    typer.echo("Signed in. A new key is stored on this machine.")


@app.command()
def logout(ctx: typer.Context) -> None:
    """Revoke this machine's key for the project and remove it."""
    s = _svc(ctx)
    _, cfg = _project(s)
    found = s.secrets.load(cfg.project_id)
    if found is None:
        typer.echo("No key is stored for this project on this machine.")
        return
    key, source = found
    if source == "env":
        typer.echo("The key comes from DRIFTWATCH_API_KEY, which logout does not change. Unset the variable yourself.")
        return
    try:
        s.api.revoke_api_key(key)
        typer.echo("Key revoked on the server.")
    except ApiError as exc:
        typer.echo(f"Could not revoke the key on the server ({exc}). Revoke it on the keys page of the website.")
    s.secrets.delete(cfg.project_id)
    typer.echo("Removed the key from this machine.")


@app.command()
def trust(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Trust this folder's .driftwatch config (needed for a folder you cloned)."""
    s = _svc(ctx)
    root = find_project_root(s.cwd())
    if root is None:
        _fail("Error: no .driftwatch/config.toml found in this folder or above.")
    cfg = _read_config(root)
    if s.trust.is_trusted(root, cfg.project_id):
        typer.echo("Already trusted.")
        return
    typer.echo(f"Folder:  {root}\nProject: {cfg.project_id}")
    if cfg.ignored_keys:
        typer.echo(f"Ignored settings in that file (DriftWatch never reads them): {', '.join(cfg.ignored_keys)}")
    if not yes and not typer.confirm("Trust this folder for this project?", default=False):
        typer.echo("Not trusted.")
        raise typer.Exit(1)
    s.trust.trust(root, cfg.project_id)
    typer.echo("Trusted. Run `driftwatch login` to get a key for this machine.")


@app.command()
def status(ctx: typer.Context) -> None:
    """Show what this folder is linked to. Never prints a key."""
    s = _svc(ctx)
    typer.echo(f"server: {s.endpoints.web_origin}")
    hook = hook_installed(s)
    typer.echo(f"autostart: {'on' if hook else 'off'}")
    typer.echo(f"agent: {agent_summary(s)}")
    root = find_project_root(s.cwd())
    if root is None:
        typer.echo("No DriftWatch project found from here. Run `driftwatch init` to link this folder.")
        return
    cfg = _read_config(root)
    trusted = s.trust.is_trusted(root, cfg.project_id)
    typer.echo(f"project: {cfg.project_id}")
    typer.echo(f"folder: {root}")
    typer.echo(f"trusted: {'yes' if trusted else 'no'}")
    typer.echo(f"key: {s.secrets.source(cfg.project_id)}")
    if cfg.ignored_keys:
        typer.echo(f"ignored settings in the config: {', '.join(cfg.ignored_keys)}")
    if not trusted:
        typer.echo("This folder is not trusted. Run `driftwatch trust` if you want to use it.")


@app.command()
def uninstall(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
    project: bool = typer.Option(False, "--project", help="Also remove this folder's .driftwatch directory."),
) -> None:
    """Remove everything this tool stored on this machine."""
    s = _svc(ctx)
    typer.echo("This will remove, from this machine only:")
    typer.echo("  - every stored project key (keychain and private file)")
    typer.echo("  - the list of trusted folders")
    typer.echo("  - the autostart hook, if one was installed")
    if project:
        typer.echo("  - this folder's .driftwatch directory")
    if not yes and not typer.confirm("Continue?", default=False):
        typer.echo("Cancelled.")
        raise typer.Exit(1)
    s.secrets.delete_all()
    s.trust.clear()
    (s.remove_hook or remove_autostart_hook)()
    try:
        agent_for(s).send({"type": "stop"})
        time.sleep(0.5)  # let it release its files
    except Exception:  # noqa: BLE001 - best effort
        pass
    shutil.rmtree(s.home / "agent", ignore_errors=True)
    try:
        (s.home / "notice.json").unlink()
    except OSError:
        pass
    try:
        s.home.rmdir()  # only succeeds when nothing else lives there
    except OSError:
        pass
    if project:
        root = find_project_root(s.cwd())
        if root is not None:
            shutil.rmtree(root / ".driftwatch", ignore_errors=True)
    typer.echo("Removed.")
    typer.echo("To finish, run: pip uninstall driftwatch-llm")
    typer.echo("Keys you created stay valid on the server until you revoke them on the keys page of the website.")


# Registers the agent / autostart / baseline / run commands on `app` (imports names defined above).
from driftwatch_llm.cli_agent import (  # noqa: E402
    agent_for,
    agent_summary,
    hook_installed,
    offer_autostart,
)
