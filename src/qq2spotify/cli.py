"""Command-line interface for qq2spotify."""

import typer

from qq2spotify import __version__

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Copy a QQ Music playlist into a Spotify playlist."""


@app.command()
def version() -> None:
    """Print the qq2spotify version."""
    typer.echo(__version__)
