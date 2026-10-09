from __future__ import annotations

import typer

from driftwatch_llm import __version__

app = typer.Typer(
    help="DriftWatch: link a project to drift monitoring.",
    no_args_is_help=True,
    add_completion=False,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"driftwatch-llm {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Show the version and exit."),
) -> None:
    """DriftWatch: link a project to drift monitoring."""
