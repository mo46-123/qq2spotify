"""Command-line interface for qq2spotify."""

import json
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from qq2spotify import __version__
from qq2spotify.http import make_client
from qq2spotify.qq.links import LinkError, extract_playlist_id
from qq2spotify.qq.playlist import QQError, fetch_raw, parse_playlist

app = typer.Typer(no_args_is_help=True)
console = Console()


def _fail(message: str) -> typer.Exit:
    console.print(f"[red]Error:[/red] {escape(message)}")
    return typer.Exit(code=1)


def _length(duration_ms: int | None) -> str:
    if duration_ms is None:
        return ""
    seconds = duration_ms // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


@app.callback()
def main() -> None:
    """Copy a QQ Music playlist into a Spotify playlist."""


@app.command()
def version() -> None:
    """Print the qq2spotify version."""
    typer.echo(__version__)


@app.command("inspect")
def inspect_playlist(
    link: Annotated[
        str, typer.Argument(help="QQ Music playlist link, share text or playlist ID.")
    ],
    qq_cookie: Annotated[
        Path | None,
        typer.Option(
            help="File holding your y.qq.com cookie, for login-only playlists."
        ),
    ] = None,
    save_raw: Annotated[
        Path | None,
        typer.Option(help="Also save QQ Music's raw reply to this file."),
    ] = None,
) -> None:
    """Show the songs in a QQ Music playlist."""
    cookie = qq_cookie.read_text(encoding="utf-8").strip() if qq_cookie else None
    try:
        with make_client() as client:
            playlist_id = extract_playlist_id(link, client)
            data = fetch_raw(playlist_id, client, cookie=cookie)
    except (LinkError, QQError) as error:
        raise _fail(str(error)) from None
    except httpx.HTTPError as error:
        raise _fail(f"Couldn't reach QQ Music ({error}).") from None

    if save_raw:
        save_raw.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    try:
        name, tracks = parse_playlist(data, playlist_id)
    except QQError as error:
        raise _fail(str(error)) from None

    table = Table(title=Text(f"{name} ({len(tracks)} songs)"))
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Singers")
    table.add_column("Album")
    table.add_column("Length", justify="right")
    for track in tracks:
        table.add_row(
            str(track.position + 1),
            Text(track.title),
            Text(" / ".join(track.artists)),
            Text(track.album or ""),
            _length(track.duration_ms),
        )
    console.print(table)
