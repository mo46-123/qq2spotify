import json
from pathlib import Path

import httpx
import pytest
import respx
from rich.console import Console
from typer.testing import CliRunner

from qq2spotify import cli
from qq2spotify.spotify import auth

runner = CliRunner()
TOKEN_REPLY = {
    "access_token": "access1",
    "expires_in": 3600,
    "refresh_token": "refresh1",
    "scope": auth.SCOPES,
}
PROFILE = {"id": "user1", "display_name": "Mo"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QQ2SPOTIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client123")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(auth.secrets, "token_urlsafe", lambda nbytes=None: "state1")
    # A wide console, so long messages aren't wrapped in the middle of a phrase.
    monkeypatch.setattr(cli, "console", Console(width=200))


def token_file(tmp_path: Path, account: str) -> Path:
    return tmp_path / "home" / "tokens" / f"{account}.json"


def mock_spotify() -> None:
    respx.post(auth.TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_REPLY))
    respx.get(f"{auth.API_URL}/me").mock(return_value=httpx.Response(200, json=PROFILE))


def save_login(tmp_path: Path, account: str = "me", **changes: object) -> None:
    values = {
        "access_token": "access1",
        "refresh_token": "refresh1",
        "expires_at": 4_000_000_000.0,
        "scope": auth.SCOPES,
        "authorized_at": "2026-11-05T12:00:00+00:00",
        "spotify_user_id": "user1",
        "display_name": "Mo",
    }
    values.update(changes)
    store = auth.TokenStore(tmp_path / "home" / "tokens")
    store.save(account, auth.TokenSet(**values))  # type: ignore[arg-type]


def test_login_by_pasting_the_address(tmp_path: Path) -> None:
    pasted = "http://127.0.0.1:8888/callback?code=code1&state=state1\n"
    with respx.mock:
        mock_spotify()
        result = runner.invoke(
            cli.app, ["login", "--account", "me", "--no-browser"], input=pasted
        )
    assert result.exit_code == 0, result.output
    assert "client_id=client123" in result.output  # the login link is shown
    assert "Signed in as Mo (user1), saved as me." in result.output
    saved = json.loads(token_file(tmp_path, "me").read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "refresh1"


def test_login_in_the_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    monkeypatch.setattr(
        cli, "wait_for_callback", lambda port, path: {"code": "c", "state": "state1"}
    )
    with respx.mock:
        mock_spotify()
        result = runner.invoke(cli.app, ["login", "-a", "friend"])
    assert result.exit_code == 0, result.output
    assert opened and opened[0].startswith(auth.AUTH_URL)
    assert token_file(tmp_path, "friend").exists()


def test_login_needs_the_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID")
    result = runner.invoke(cli.app, ["login", "--no-browser"])
    assert result.exit_code == 1
    assert "SPOTIFY_CLIENT_ID" in result.output


def test_login_rejects_a_bad_account_name() -> None:
    result = runner.invoke(cli.app, ["login", "--account", "my friend"])
    assert result.exit_code == 1
    assert "letters, digits" in result.output


def test_login_reports_a_cancelled_login(tmp_path: Path) -> None:
    pasted = "http://127.0.0.1:8888/callback?error=access_denied&state=state1\n"
    result = runner.invoke(cli.app, ["login", "--no-browser"], input=pasted)
    assert result.exit_code == 1
    assert "access_denied" in result.output
    assert not token_file(tmp_path, "default").exists()


def test_accounts_lists_saved_logins(tmp_path: Path) -> None:
    save_login(tmp_path, "me")
    result = runner.invoke(cli.app, ["accounts"])
    assert result.exit_code == 0, result.output
    assert "me" in result.output
    assert "Mo (user1)" in result.output
    assert "days ago" in result.output


def test_accounts_when_there_are_none() -> None:
    result = runner.invoke(cli.app, ["accounts"])
    assert result.exit_code == 0
    assert "No saved Spotify logins yet" in result.output


def test_whoami_refreshes_an_old_token(tmp_path: Path) -> None:
    save_login(tmp_path, "me", expires_at=0.0)
    with respx.mock:
        refresh = respx.post(auth.TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "access2"})
        )
        me = respx.get(f"{auth.API_URL}/me").mock(
            return_value=httpx.Response(200, json=PROFILE)
        )
        result = runner.invoke(cli.app, ["whoami", "--account", "me"])
    assert result.exit_code == 0, result.output
    assert "me: logged in as Mo (user1)." in result.output
    assert refresh.called
    assert me.calls.last.request.headers["Authorization"] == "Bearer access2"


def test_whoami_without_a_login() -> None:
    result = runner.invoke(cli.app, ["whoami", "--account", "me"])
    assert result.exit_code == 1
    assert "No saved login named 'me'" in result.output


def test_whoami_explains_a_403(tmp_path: Path) -> None:
    save_login(tmp_path, "me")
    with respx.mock:
        respx.get(f"{auth.API_URL}/me").mock(return_value=httpx.Response(403))
        result = runner.invoke(cli.app, ["whoami", "--account", "me"])
    assert result.exit_code == 1
    assert "User Management" in result.output


def test_logout_forgets_the_login(tmp_path: Path) -> None:
    save_login(tmp_path, "me")
    first = runner.invoke(cli.app, ["logout", "--account", "me"])
    second = runner.invoke(cli.app, ["logout", "--account", "me"])
    assert "Removed the saved login me" in first.output
    assert not token_file(tmp_path, "me").exists()
    assert "no saved login named me" in second.output
