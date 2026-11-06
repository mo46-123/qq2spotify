import json
from pathlib import Path

import httpx
import pytest
import respx
from rich.console import Console
from typer.testing import CliRunner

from qq2spotify import cli
from qq2spotify.qq.playlist import ENDPOINTS
from qq2spotify.spotify import auth

FIXTURE = Path(__file__).parent / "fixtures" / "qq_playlist_sample.json"
LINK = "https://y.qq.com/n/ryqq/playlist/7891234567"
API = auth.API_URL
MARKER = "Imported from QQ Music playlist 7891234567 with qq2spotify"
NEW_ID = "newPlaylist00000000000"
OLD_ID = "oldPlaylist00000000000"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QQ2SPOTIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client123")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(cli, "console", Console(width=200))
    monkeypatch.setattr(cli, "SEARCH_PAUSE", 0)
    auth.TokenStore(tmp_path / "home" / "tokens").save(
        "me",
        auth.TokenSet(
            access_token="access1",
            refresh_token="refresh1",
            expires_at=4_000_000_000.0,
            scope=auth.SCOPES,
            authorized_at="2026-11-05T12:00:00+00:00",
            spotify_user_id="user1",
            display_name="Mo",
        ),
    )


def track(number: int, name: str, artists: list[str], album: str, ms: int) -> dict:
    return {
        "uri": f"spotify:track:{number}",
        "name": name,
        "artists": [{"name": artist} for artist in artists],
        "album": {"name": album},
        "duration_ms": ms,
        "external_urls": {"spotify": f"https://open.spotify.com/track/{number}"},
    }


def spotify_search(request: httpx.Request) -> httpx.Response:
    query = request.url.params["q"]
    items = []
    if "晴天" in query:
        items = [track(1, "晴天", ["Jay Chou"], "葉惠美", 269_500)]
    elif "说好不哭" in query or "說好不哭" in query:
        items = [track(2, "說好不哭", ["Jay Chou"], "說好不哭", 222_000)]
    return httpx.Response(200, json={"tracks": {"items": items}})


def mock_qq_and_search(search=spotify_search) -> None:
    respx.get(ENDPOINTS[0]).mock(
        return_value=httpx.Response(200, text=FIXTURE.read_text(encoding="utf-8"))
    )
    respx.get(f"{API}/search").mock(side_effect=search)


def sent(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


def test_creates_a_private_playlist_and_adds_songs_in_order() -> None:
    with respx.mock:
        mock_qq_and_search()
        respx.get(f"{API}/me/playlists").mock(
            return_value=httpx.Response(200, json={"items": [], "next": None})
        )
        create = respx.post(f"{API}/me/playlists").mock(
            return_value=httpx.Response(201, json={"id": NEW_ID})
        )
        add = respx.post(f"{API}/playlists/{NEW_ID}/items").mock(
            return_value=httpx.Response(201, json={"snapshot_id": "s"})
        )
        result = runner.invoke(cli.app, ["transfer", LINK, "--account", "me"])
    assert result.exit_code == 0, result.output
    assert sent(create) == {
        "name": "夜跑 & 晨练 (from QQ Music)",
        "public": False,
        "description": MARKER,
    }
    assert sent(add) == {"uris": ["spotify:track:1", "spotify:track:2"]}
    assert (
        'Created the private playlist "夜跑 & 晨练 (from QQ Music)".' in result.output
    )
    assert "Added 2 songs." in result.output
    assert f"https://open.spotify.com/playlist/{NEW_ID}" in result.output


def test_a_second_run_reuses_the_playlist_and_adds_only_whats_missing() -> None:
    mine = {"id": OLD_ID, "owner": {"id": "user1"}, "description": MARKER}
    with respx.mock:
        mock_qq_and_search()
        respx.get(f"{API}/me/playlists").mock(
            return_value=httpx.Response(200, json={"items": [mine], "next": None})
        )
        respx.get(f"{API}/playlists/{OLD_ID}/items").mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"item": {"uri": "spotify:track:1"}}], "next": None},
            )
        )
        add = respx.post(f"{API}/playlists/{OLD_ID}/items").mock(
            return_value=httpx.Response(201, json={"snapshot_id": "s"})
        )
        result = runner.invoke(cli.app, ["transfer", LINK, "-a", "me"])
    assert result.exit_code == 0, result.output
    assert sent(add) == {"uris": ["spotify:track:2"]}
    assert "Found the playlist an earlier run made" in result.output
    assert "Added 1 song (1 already there)." in result.output


def test_another_accounts_playlist_is_not_reused() -> None:
    theirs = {"id": OLD_ID, "owner": {"id": "someone-else"}, "description": MARKER}
    with respx.mock:
        mock_qq_and_search()
        respx.get(f"{API}/me/playlists").mock(
            return_value=httpx.Response(200, json={"items": [theirs], "next": None})
        )
        create = respx.post(f"{API}/me/playlists").mock(
            return_value=httpx.Response(201, json={"id": NEW_ID})
        )
        respx.post(f"{API}/playlists/{NEW_ID}/items").mock(
            return_value=httpx.Response(201, json={"snapshot_id": "s"})
        )
        result = runner.invoke(cli.app, ["transfer", LINK, "-a", "me"])
    assert result.exit_code == 0, result.output
    assert create.called


def test_adds_to_an_existing_playlist_given_by_link() -> None:
    target = "37i9dQZF1DXcBWIGoYBM5M"
    with respx.mock:
        mock_qq_and_search()
        respx.get(f"{API}/playlists/{target}/items").mock(
            return_value=httpx.Response(200, json={"items": [], "next": None})
        )
        add = respx.post(f"{API}/playlists/{target}/items").mock(
            return_value=httpx.Response(201, json={"snapshot_id": "s"})
        )
        result = runner.invoke(
            cli.app,
            [
                "transfer",
                LINK,
                "-a",
                "me",
                "--to-playlist",
                f"https://open.spotify.com/playlist/{target}?si=abc",
            ],
        )
    assert result.exit_code == 0, result.output
    assert sent(add) == {"uris": ["spotify:track:1", "spotify:track:2"]}


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    with respx.mock:  # no POST routes: any change would fail the test
        mock_qq_and_search()
        respx.get(f"{API}/me/playlists").mock(
            return_value=httpx.Response(200, json={"items": [], "next": None})
        )
        result = runner.invoke(cli.app, ["transfer", LINK, "-a", "me", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run: nothing was changed on Spotify." in result.output
    assert (
        'It would create the private playlist "夜跑 & 晨练 (from QQ Music)" '
        "and add 2 songs." in result.output
    )
    assert (tmp_path / "report-7891234567.csv").exists()


def test_dry_run_leaves_out_songs_already_in_the_playlist() -> None:
    mine = {"id": OLD_ID, "owner": {"id": "user1"}, "description": MARKER}
    with respx.mock:  # no POST routes: any change would fail the test
        mock_qq_and_search()
        respx.get(f"{API}/me/playlists").mock(
            return_value=httpx.Response(200, json={"items": [mine], "next": None})
        )
        respx.get(f"{API}/playlists/{OLD_ID}/items").mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"item": {"uri": "spotify:track:1"}}], "next": None},
            )
        )
        result = runner.invoke(cli.app, ["transfer", LINK, "-a", "me", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert (
        "It would add 1 song (1 already there) to the playlist an earlier run made."
        in result.output
    )
    assert f"https://open.spotify.com/playlist/{OLD_ID}" in result.output


def test_dry_run_into_a_chosen_playlist() -> None:
    target = "37i9dQZF1DXcBWIGoYBM5M"
    with respx.mock:  # no POST routes: any change would fail the test
        mock_qq_and_search()
        respx.get(f"{API}/playlists/{target}/items").mock(
            return_value=httpx.Response(200, json={"items": [], "next": None})
        )
        result = runner.invoke(
            cli.app,
            ["transfer", LINK, "-a", "me", "--to-playlist", target, "--dry-run"],
        )
    assert result.exit_code == 0, result.output
    assert "It would add 2 songs to the playlist you chose." in result.output


def test_a_failed_add_is_not_sent_again() -> None:
    with respx.mock:
        mock_qq_and_search()
        respx.get(f"{API}/me/playlists").mock(
            return_value=httpx.Response(200, json={"items": [], "next": None})
        )
        respx.post(f"{API}/me/playlists").mock(
            return_value=httpx.Response(201, json={"id": NEW_ID})
        )
        add = respx.post(f"{API}/playlists/{NEW_ID}/items").mock(
            return_value=httpx.Response(502)
        )
        result = runner.invoke(cli.app, ["transfer", LINK, "-a", "me"])
    assert result.exit_code == 1
    assert add.call_count == 1  # it may have gone through, so it isn't resent
    assert "HTTP 502" in result.output
    assert "run the same command again" in result.output
    assert "won't be added twice" in result.output


def test_include_review_adds_songs_to_check_too() -> None:
    def search_with_a_doubtful_result(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        if "说好不哭" in query or "說好不哭" in query:
            doubtful = track(3, "说好不哭", ["张三"], "说好不哭", 222_000)
            return httpx.Response(200, json={"tracks": {"items": [doubtful]}})
        return spotify_search(request)

    with respx.mock:
        mock_qq_and_search(search_with_a_doubtful_result)
        respx.get(f"{API}/me/playlists").mock(
            return_value=httpx.Response(200, json={"items": [], "next": None})
        )
        respx.post(f"{API}/me/playlists").mock(
            return_value=httpx.Response(201, json={"id": NEW_ID})
        )
        add = respx.post(f"{API}/playlists/{NEW_ID}/items").mock(
            return_value=httpx.Response(201, json={"snapshot_id": "s"})
        )
        result = runner.invoke(
            cli.app, ["transfer", LINK, "-a", "me", "--include-review"]
        )
    assert result.exit_code == 0, result.output
    assert "Review 1" in result.output
    assert sent(add) == {"uris": ["spotify:track:1", "spotify:track:3"]}


def test_nothing_matched_means_no_playlist() -> None:
    def no_results(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tracks": {"items": []}})

    with respx.mock:
        mock_qq_and_search(no_results)
        result = runner.invoke(cli.app, ["transfer", LINK, "-a", "me"])
    assert result.exit_code == 0, result.output
    assert "No songs to add" in result.output


def test_explains_a_playlist_it_cannot_change() -> None:
    target = "37i9dQZF1DXcBWIGoYBM5M"
    with respx.mock:
        mock_qq_and_search()
        respx.get(f"{API}/playlists/{target}/items").mock(
            return_value=httpx.Response(200, json={"items": [], "next": None})
        )
        respx.post(f"{API}/playlists/{target}/items").mock(
            return_value=httpx.Response(403)
        )
        result = runner.invoke(
            cli.app, ["transfer", LINK, "-a", "me", "--to-playlist", target]
        )
    assert result.exit_code == 1
    assert "collaborator" in result.output


def test_rejects_a_link_that_is_not_a_playlist() -> None:
    result = runner.invoke(
        cli.app,
        [
            "transfer",
            LINK,
            "-a",
            "me",
            "--to-playlist",
            "https://open.spotify.com/track/0YgvF6fNWydNGzCY3pzK4Y",
        ],
    )
    assert result.exit_code == 1
    assert "isn't a Spotify playlist link" in result.output
