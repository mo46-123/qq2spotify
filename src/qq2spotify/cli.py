"""Command-line interface for qq2spotify."""

import json
import time
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import track as with_progress
from rich.table import Table
from rich.text import Text

from qq2spotify import __version__
from qq2spotify.config import ConfigError, Settings, data_dir, load_settings
from qq2spotify.http import make_client
from qq2spotify.matching.search import Matcher, load_aliases
from qq2spotify.models import MatchResult, SourceTrack
from qq2spotify.qq.links import LinkError, extract_playlist_id
from qq2spotify.qq.playlist import QQError, fetch_playlist, fetch_raw, parse_playlist
from qq2spotify.report import count_statuses, format_length, write_report
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
from qq2spotify.spotify.playlists import (
    PlaylistError,
    add_in_order,
    create_playlist,
    existing_uris,
    find_imported_playlist,
    parse_playlist_ref,
    playlist_url,
)

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


SEARCH_PAUSE = 0.1  # seconds between Spotify searches, to stay under rate limits


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
            format_length(track.duration_ms),
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


LinkArgument = Annotated[
    str, typer.Argument(help="QQ Music playlist link, share text or playlist ID.")
]
ReportOption = Annotated[
    Path | None,
    typer.Option(help="Where to save the report. Default: report-<playlist ID>.csv"),
]
CookieOption = Annotated[
    Path | None,
    typer.Option(help="File holding your y.qq.com cookie, for login-only playlists."),
]


@dataclass
class MatchRun:
    playlist_id: str
    name: str
    tracks: list[SourceTrack]
    results: list[MatchResult] = field(default_factory=list)
    stopped_by: str | None = None  # why matching stopped early, if it did


@contextmanager
def _friendly_errors() -> Iterator[None]:
    """Turn the errors people can run into into short messages."""
    try:
        yield
    except (LinkError, QQError, NeedsLogin, QuotaExceeded, PlaylistError) as error:
        raise _fail(str(error)) from None
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status == 403:
            raise _fail(
                f"{NOT_ALLOWED} When adding to an existing playlist, it must belong "
                "to this account or be shared with it as a collaborator."
            ) from None
        if status == 404:
            raise _fail("Spotify couldn't find that playlist.") from None
        raise _fail(f"Spotify said no (HTTP {status}).") from None
    except httpx.HTTPError as error:
        raise _fail(f"Couldn't reach Spotify or QQ Music ({error}).") from None


def _read_cookie(path: Path | None) -> str | None:
    return path.read_text(encoding="utf-8").strip() if path else None


def _match_songs(
    http: httpx.Client, api: SpotifyClient, link: str, cookie: str | None
) -> MatchRun:
    playlist_id = extract_playlist_id(link, http)
    name, tracks = fetch_playlist(playlist_id, http, cookie=cookie)
    aliases = load_aliases(data_dir() / "aliases.json")
    matcher = Matcher(api, aliases, pause=SEARCH_PAUSE)
    run = MatchRun(playlist_id, name, tracks)
    try:
        for song in with_progress(
            tracks, description="Searching Spotify", console=console, transient=True
        ):
            run.results.append(matcher.match(song))
    except QuotaExceeded as error:
        run.stopped_by = str(error)  # keep what was found so far
    return run


def _save_report(run: MatchRun, report: Path | None) -> None:
    report_path = report or Path(f"report-{run.playlist_id}.csv")
    write_report(report_path, run.results)
    counts = count_statuses(run.results)
    console.print(
        Text(f"{run.name}: checked {len(run.results)} of {len(run.tracks)} songs.")
    )
    console.print(
        f"Matched {counts['matched']} · Review {counts['review']} · "
        f"Not found {counts['not_found']}"
    )
    _print_songs_to_check(run.results)
    console.print(f"Report saved to {escape(str(report_path))}")
    if run.stopped_by:
        raise _fail(f"{run.stopped_by} The report has the songs checked so far.")


@app.command("match")
def match_playlist(
    link: LinkArgument,
    account: AccountOption = "default",
    report: ReportOption = None,
    qq_cookie: CookieOption = None,
) -> None:
    """Find each QQ Music song on Spotify and save a report. Changes nothing on Spotify."""
    store = _store(account)
    settings = _settings()
    cookie = _read_cookie(qq_cookie)
    with _friendly_errors(), make_client() as http:
        tokens = AccountTokens(store, account, settings.client_id, http)
        run = _match_songs(http, SpotifyClient(tokens, http), link, cookie)
    _save_report(run, report)


@app.command()
def transfer(
    link: LinkArgument,
    account: AccountOption = "default",
    playlist_name: Annotated[
        str | None,
        typer.Option(
            help='Name for a new playlist. Default: the QQ name + "(from QQ Music)".'
        ),
    ] = None,
    to_playlist: Annotated[
        str | None,
        typer.Option(help="Add to this existing Spotify playlist (link or ID)."),
    ] = None,
    public: Annotated[
        bool, typer.Option("--public/--private", help="Who can see a new playlist.")
    ] = False,
    include_review: Annotated[
        bool, typer.Option(help="Also add songs that scored from 0.60 to 0.80.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option(help="Search and save the report; change nothing.")
    ] = False,
    report: ReportOption = None,
    qq_cookie: CookieOption = None,
) -> None:
    """Copy a QQ Music playlist into a Spotify playlist."""
    store = _store(account)
    settings = _settings()
    cookie = _read_cookie(qq_cookie)
    with _friendly_errors():
        target = parse_playlist_ref(to_playlist) if to_playlist else None
    with _friendly_errors(), make_client() as http:
        tokens = AccountTokens(store, account, settings.client_id, http)
        api = SpotifyClient(tokens, http)
        run = _match_songs(http, api, link, cookie)
        _save_report(run, report)
        wanted = [
            result.best.uri
            for result in run.results
            if result.best
            and (
                result.status == "matched"
                or (include_review and result.status == "review")
            )
        ]
        uris = list(dict.fromkeys(wanted))  # a song listed twice is added once
        if dry_run:
            console.print(
                f"Dry run: {_songs(len(uris))} would be added. "
                "Nothing changed on Spotify."
            )
            return
        if not uris:
            console.print("No songs to add, so no Spotify playlist was changed.")
            return
        made_now = False
        playlist_id = target or find_imported_playlist(
            api, tokens.tokens.spotify_user_id, run.playlist_id
        )
        if playlist_id is None:
            name = playlist_name or f"{run.name} (from QQ Music)"
            playlist_id = create_playlist(api, name, run.playlist_id, public=public)
            made_now = True
            visibility = "public" if public else "private"
            console.print(Text(f'Created the {visibility} playlist "{name}".'))
        elif not target:
            console.print(
                "Found the playlist an earlier run made; adding what's missing."
            )
        already = set() if made_now else existing_uris(api, playlist_id)
        to_add = [uri for uri in uris if uri not in already]
        add_in_order(api, playlist_id, to_add)
    skipped = len(uris) - len(to_add)
    note = f" ({skipped} already there)" if skipped else ""
    console.print(f"Added {_songs(len(to_add))}{note}.")
    console.print(f"Open it in Spotify: {playlist_url(playlist_id)}")


def _songs(count: int) -> str:
    return "1 song" if count == 1 else f"{count} songs"


def _describe(track: SourceTrack) -> Text:
    return Text(f"{track.title} – {' / '.join(track.artists)}".rstrip(" –"))


def _print_songs_to_check(results: list[MatchResult]) -> None:
    to_check = [result for result in results if result.status != "matched"]
    if not to_check:
        return
    table = Table(title=Text("Songs to check"))
    table.add_column("#", justify="right")
    table.add_column("QQ Music")
    table.add_column("Best Spotify match")
    table.add_column("Score", justify="right")
    table.add_column("Result")
    for result in to_check:
        best = result.best
        found = f"{best.title} – {' / '.join(best.artists)}" if best else ""
        table.add_row(
            str(result.source.position + 1),
            _describe(result.source),
            Text(found),
            f"{result.score:.2f}",
            result.status.replace("_", " "),
        )
    console.print(table)
