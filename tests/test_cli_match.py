import csv
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
SEARCH_URL = f"{auth.API_URL}/search"
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
        items = [
            track(2, "說好不哭 (with 五月天阿信)", ["Jay Chou"], "說好不哭", 222_000)
        ]
    return httpx.Response(200, json={"tracks": {"items": items}})


def read_report(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_match_writes_a_report_and_lists_songs_to_check(tmp_path: Path) -> None:
    with respx.mock:
        respx.get(ENDPOINTS[0]).mock(
            return_value=httpx.Response(200, text=FIXTURE.read_text(encoding="utf-8"))
        )
        respx.get(SEARCH_URL).mock(side_effect=spotify_search)
        result = runner.invoke(cli.app, ["match", LINK, "--account", "me"])
    assert result.exit_code == 0, result.output
    assert "checked 3 of 3 songs" in result.output
    assert "Matched 2 · Review 0 · Not found 1" in result.output
    assert "Songs to check" in result.output
    assert "Rock & Roll [Live]" in result.output
    rows = read_report(tmp_path / "report-7891234567.csv")
    assert [row["status"] for row in rows] == ["matched", "matched", "not_found"]
    assert rows[0]["spotify_url"] == "https://open.spotify.com/track/1"


def test_match_saves_what_it_found_when_the_quota_runs_out(tmp_path: Path) -> None:
    def quota_after_first_song(request: httpx.Request) -> httpx.Response:
        if "晴天" in request.url.params["q"]:
            return spotify_search(request)
        return httpx.Response(
            429, json={"error": {"status": 429, "reason": "QUOTA_EXCEEDED"}}
        )

    report = tmp_path / "partial.csv"
    with respx.mock:
        respx.get(ENDPOINTS[0]).mock(
            return_value=httpx.Response(200, text=FIXTURE.read_text(encoding="utf-8"))
        )
        respx.get(SEARCH_URL).mock(side_effect=quota_after_first_song)
        result = runner.invoke(
            cli.app, ["match", LINK, "-a", "me", "--report", str(report)]
        )
    assert result.exit_code == 1
    assert "quota" in result.output
    assert "checked 1 of 3 songs" in result.output
    assert [row["status"] for row in read_report(report)] == ["matched"]


def test_match_needs_a_login() -> None:
    with respx.mock:
        respx.get(ENDPOINTS[0]).mock(
            return_value=httpx.Response(200, text=FIXTURE.read_text(encoding="utf-8"))
        )
        result = runner.invoke(cli.app, ["match", LINK, "--account", "friend"])
    assert result.exit_code == 1
    assert "No saved login named 'friend'" in result.output
