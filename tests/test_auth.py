import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from qq2spotify.config import Settings
from qq2spotify.spotify import auth

SETTINGS = Settings(
    client_id="client123", redirect_uri="http://127.0.0.1:8888/callback"
)
TOKEN_REPLY = {
    "access_token": "access1",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "refresh1",
    "scope": auth.SCOPES,
}
PROFILE = {"id": "user1", "display_name": "Mo"}


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def saved_tokens(**changes: object) -> auth.TokenSet:
    values = {
        "access_token": "access1",
        "refresh_token": "refresh1",
        "expires_at": 10_000.0,
        "scope": auth.SCOPES,
        "authorized_at": "2026-11-05T12:00:00+00:00",
        "spotify_user_id": "user1",
        "display_name": "Mo",
    }
    values.update(changes)
    return auth.TokenSet(**values)  # type: ignore[arg-type]


# --- PKCE and the login link -------------------------------------------------


def test_code_challenge_matches_the_rfc_7636_example() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert auth.code_challenge(verifier) == expected


def test_pkce_pair_is_valid() -> None:
    verifier, challenge = auth.make_pkce_pair()
    assert len(verifier) == 64
    assert set(verifier) <= set(auth.VERIFIER_ALPHABET)
    assert challenge == auth.code_challenge(verifier)


def test_login_link_has_everything_spotify_needs() -> None:
    attempt = auth.start_login(SETTINGS)
    url = urlparse(attempt.url)
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == auth.AUTH_URL
    assert query == {
        "client_id": "client123",
        "response_type": "code",
        "redirect_uri": "http://127.0.0.1:8888/callback",
        "scope": auth.SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": auth.code_challenge(attempt.verifier),
        "state": attempt.state,
        "show_dialog": "true",
    }


@pytest.mark.parametrize(
    "text",
    [
        "http://127.0.0.1:8888/callback?code=abc&state=xyz",
        "  ?code=abc&state=xyz \n",
        "code=abc&state=xyz",
    ],
)
def test_parse_callback(text: str) -> None:
    assert auth.parse_callback(text) == {"code": "abc", "state": "xyz"}


# --- The local callback server -----------------------------------------------


def test_wait_for_callback_returns_spotifys_reply() -> None:
    port = free_port()
    reply: dict[str, str] = {}
    thread = threading.Thread(
        target=lambda: reply.update(auth.wait_for_callback(port, timeout=10))
    )
    thread.start()
    for _ in range(100):  # wait until the server is listening
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/favicon.ico", timeout=1)
        except urllib.error.HTTPError as error:
            assert error.code == 404  # other paths are ignored
            break
        except OSError:
            time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/callback?code=abc&state=xyz"
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.status == 200
    thread.join(10)
    assert reply == {"code": "abc", "state": "xyz"}


def test_wait_for_callback_gives_up_after_the_timeout() -> None:
    with pytest.raises(auth.LoginError, match="Timed out"):
        auth.wait_for_callback(free_port(), timeout=0.3)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows lets ports be shared")
def test_wait_for_callback_explains_a_busy_port() -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        with pytest.raises(auth.LoginError, match=f"port {port}"):
            auth.wait_for_callback(port, timeout=1)


# --- Finishing the login -----------------------------------------------------


def attempt() -> auth.LoginAttempt:
    return auth.LoginAttempt(url="https://example.com", verifier="v" * 64, state="s1")


def test_finish_login_swaps_the_code_and_reads_the_profile() -> None:
    with respx.mock:
        token_route = respx.post(auth.TOKEN_URL).mock(
            return_value=httpx.Response(200, json=TOKEN_REPLY)
        )
        me_route = respx.get(f"{auth.API_URL}/me").mock(
            return_value=httpx.Response(200, json=PROFILE)
        )
        with httpx.Client() as http:
            tokens = auth.finish_login(
                attempt(), {"code": "code1", "state": "s1"}, SETTINGS, http, now=1e6
            )
    assert form(token_route.calls.last.request) == {
        "grant_type": "authorization_code",
        "code": "code1",
        "redirect_uri": "http://127.0.0.1:8888/callback",
        "client_id": "client123",
        "code_verifier": "v" * 64,
    }
    assert me_route.calls.last.request.headers["Authorization"] == "Bearer access1"
    assert tokens == saved_tokens(
        expires_at=1e6 + 3600, authorized_at="1970-01-12T13:46:40+00:00"
    )


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"error": "access_denied", "state": "s1"}, "access_denied"),
        ({"code": "code1", "state": "someone-else"}, "doesn't belong"),
        ({"state": "s1"}, "no code"),
    ],
)
def test_finish_login_rejects_bad_replies(reply: dict, message: str) -> None:
    with httpx.Client() as http, pytest.raises(auth.LoginError, match=message):
        auth.finish_login(attempt(), reply, SETTINGS, http)


def test_finish_login_reports_spotifys_reason() -> None:
    refusal = {
        "error": "invalid_grant",
        "error_description": "Invalid authorization code",
    }
    with respx.mock:
        respx.post(auth.TOKEN_URL).mock(return_value=httpx.Response(400, json=refusal))
        with (
            httpx.Client() as http,
            pytest.raises(auth.LoginError, match="Invalid authorization code"),
        ):
            auth.finish_login(attempt(), {"code": "c", "state": "s1"}, SETTINGS, http)


def test_finish_login_explains_an_account_missing_from_the_allowlist() -> None:
    with respx.mock:
        respx.post(auth.TOKEN_URL).mock(
            return_value=httpx.Response(200, json=TOKEN_REPLY)
        )
        respx.get(f"{auth.API_URL}/me").mock(return_value=httpx.Response(403))
        with (
            httpx.Client() as http,
            pytest.raises(auth.LoginError, match="User Management"),
        ):
            auth.finish_login(attempt(), {"code": "c", "state": "s1"}, SETTINGS, http)


# --- Saved logins ------------------------------------------------------------


def test_store_saves_lists_loads_and_deletes(tmp_path: Path) -> None:
    store = auth.TokenStore(tmp_path / "tokens")
    assert store.accounts() == []
    store.save("me", saved_tokens())
    store.save("friend", saved_tokens(display_name="Friend"))
    assert store.accounts() == ["friend", "me"]
    assert store.load("me") == saved_tokens()
    assert not list((tmp_path / "tokens").glob("*.tmp"))
    assert store.delete("me") is True
    assert store.delete("me") is False
    with pytest.raises(auth.NeedsLogin, match="No saved login named 'me'"):
        store.load("me")


def test_store_reports_a_damaged_file(tmp_path: Path) -> None:
    store = auth.TokenStore(tmp_path)
    (tmp_path / "me.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(auth.NeedsLogin, match="damaged"):
        store.load("me")


@pytest.mark.parametrize("name", ["", "my friend", "../me", "x" * 41])
def test_store_rejects_bad_account_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="letters, digits"):
        auth.TokenStore(tmp_path).path(name)


def test_days_since_login() -> None:
    tokens = saved_tokens(authorized_at="2026-01-01T00:00:00+00:00")
    jan_31 = 1_769_817_600.0  # 2026-01-31T00:00:00Z
    assert tokens.days_since_login(jan_31) == 30


# --- Refreshing --------------------------------------------------------------


def account(tmp_path: Path, http: httpx.Client, now: float) -> auth.AccountTokens:
    store = auth.TokenStore(tmp_path)
    store.save("me", saved_tokens())
    return auth.AccountTokens(store, "me", "client123", http, clock=lambda: now)


def test_fresh_token_is_used_as_is(tmp_path: Path) -> None:
    with respx.mock, httpx.Client() as http:  # any request would fail the test
        assert account(tmp_path, http, now=5_000.0).access_token() == "access1"


@pytest.mark.parametrize(
    ("reply_refresh_token", "kept"), [(None, "refresh1"), ("refresh2", "refresh2")]
)
def test_old_token_is_refreshed_and_saved(
    tmp_path: Path, reply_refresh_token: str | None, kept: str
) -> None:
    reply = {"access_token": "access2", "expires_in": 3600}
    if reply_refresh_token:
        reply["refresh_token"] = reply_refresh_token
    with respx.mock:
        route = respx.post(auth.TOKEN_URL).mock(
            return_value=httpx.Response(200, json=reply)
        )
        with httpx.Client() as http:
            tokens = account(tmp_path, http, now=9_990.0)
            assert tokens.access_token() == "access2"
    assert form(route.calls.last.request) == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh1",
        "client_id": "client123",
    }
    saved = json.loads((tmp_path / "me.json").read_text(encoding="utf-8"))
    assert saved["access_token"] == "access2"
    assert saved["refresh_token"] == kept
    assert saved["expires_at"] == 9_990.0 + 3600


def test_expired_login_is_removed(tmp_path: Path) -> None:
    with respx.mock:
        respx.post(auth.TOKEN_URL).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        with httpx.Client() as http:
            tokens = account(tmp_path, http, now=9_990.0)
            with pytest.raises(auth.NeedsLogin, match="6 months"):
                tokens.access_token()
    assert not (tmp_path / "me.json").exists()
