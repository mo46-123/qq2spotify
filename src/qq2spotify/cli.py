"""Command-line interface for qq2spotify."""

import json
import time
import webbrowser
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from qq2spotify import __version__
from qq2spotify.config import ConfigError, Settings, data_dir, load_settings
from qq2spotify.http import make_client
from qq2spotify.qq.links import LinkError, extract_playlist_id
from qq2spotify.qq.playlist import QQError, fetch_raw, parse_playlist
from qq2spotify.spotify.auth import (
    LOGIN_WARNING_DAYS,
    AccountTokens,
    LoginError,
    NeedsLogin,
    TokenStore,
    finish_login,
    parse_callback,
    start_login,
    wait_for_callback,
)
from qq2spotify.spotify.client import QuotaExceeded, SpotifyClient

app = typer.Typer(no_args_is_help=True)
console = Console()

AccountOption = Annotated[
    str,
    typer.Option(
        "--account", "-a", help="Nickname for the Spotify account, like me or friend."
    ),
]
NOT_ALLOWED = (
    "Spotify won't let this account use your app. Add it under User Management "
    "in your Spotify app's settings (the app owner also needs Premium)."
)


def _fail(message: str) -> typer.Exit:
    console.print(f"[red]Error:[/red] {escape(message)}")
    return typer.Exit(code=1)


def _store(account: str) -> TokenStore:
    store = TokenStore(data_dir() / "tokens")
    try:
        store.path(account)
    except ValueError as error:
        raise _fail(str(error)) from None
    return store


def _settings() -> Settings:
    try:
        return load_settings()
    except ConfigError as error:
        raise _fail(str(error)) from None


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


@app.command()
def login(
    account: AccountOption = "default",
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser",
            help="Don't open a browser here; paste the final address instead. "
            "Use this when the account owner signs in on another device.",
        ),
    ] = False,
) -> None:
    """Log in to a Spotify account and save the login on this computer."""
    store = _store(account)
    settings = _settings()
    attempt = start_login(settings)
    console.print(
        "Log in to Spotify as the account you want to save as "
        f"[bold]{escape(account)}[/bold]. If Spotify shows a different account, "
        "switch accounts on its page or open the link in a private window."
    )
    typer.echo(f"\n{attempt.url}\n")
    try:
        if no_browser:
            console.print(
                "Open that link on any device. After you agree, the page won't load; "
                "that's expected. Copy the address from the address bar within a "
                "few minutes."
            )
            reply = parse_callback(typer.prompt("Paste the address here"))
        else:
            webbrowser.open(attempt.url)
            console.print("Waiting for you in the browser (press Ctrl+C to stop)...")
            reply = wait_for_callback(settings.callback_port, settings.callback_path)
        with make_client() as http:
            tokens = finish_login(attempt, reply, settings, http)
    except LoginError as error:
        raise _fail(str(error)) from None
    except httpx.HTTPError as error:
        raise _fail(f"Couldn't reach Spotify ({error}).") from None
    store.save(account, tokens)
    console.print(
        f"Signed in as [bold]{escape(tokens.display_name)}[/bold] "
        f"({escape(tokens.spotify_user_id)}), saved as {escape(account)}."
    )


@app.command("accounts")
def list_accounts() -> None:
    """List the Spotify logins saved on this computer."""
    store = TokenStore(data_dir() / "tokens")
    names = store.accounts()
    if not names:
        console.print("No saved Spotify logins yet. Run: qq2spotify login --account me")
        return
    table = Table(title=Text("Saved Spotify logins"))
    for column in ("Account", "Spotify user", "Logged in", "Note"):
        table.add_column(column)
    now = time.time()
    for name in names:
        try:
            tokens = store.load(name)
        except NeedsLogin:
            table.add_row(Text(name), "", "", Text("damaged; log in again"))
            continue
        days = tokens.days_since_login(now)
        note = (
            "log in again soon; logins last about 6 months"
            if days >= LOGIN_WARNING_DAYS
            else ""
        )
        table.add_row(
            Text(name),
            Text(f"{tokens.display_name} ({tokens.spotify_user_id})"),
            f"{days} days ago",
            Text(note),
        )
    console.print(table)


@app.command()
def whoami(account: AccountOption = "default") -> None:
    """Check that a saved login still works by asking Spotify who it is."""
    store = _store(account)
    settings = _settings()
    try:
        with make_client() as http:
            tokens = AccountTokens(store, account, settings.client_id, http)
            me = SpotifyClient(tokens, http).get("/me")
    except (NeedsLogin, QuotaExceeded) as error:
        raise _fail(str(error)) from None
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 403:
            raise _fail(NOT_ALLOWED) from None
        raise _fail(f"Spotify said no (HTTP {error.response.status_code}).") from None
    except httpx.HTTPError as error:
        raise _fail(f"Couldn't reach Spotify ({error}).") from None
    name = me.get("display_name") or me["id"]
    console.print(
        f"{escape(account)}: logged in as [bold]{escape(name)}[/bold] "
        f"({escape(me['id'])})."
    )


@app.command()
def logout(account: AccountOption = "default") -> None:
    """Forget a saved Spotify login on this computer."""
    store = _store(account)
    if store.delete(account):
        console.print(
            f"Removed the saved login {escape(account)}. To cut off access "
            "completely, also remove the app under Manage apps in that Spotify "
            "account's settings."
        )
    else:
        console.print(f"There's no saved login named {escape(account)}.")
