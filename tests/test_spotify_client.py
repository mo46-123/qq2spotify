import httpx
import pytest
import respx

from qq2spotify.spotify.auth import API_URL
from qq2spotify.spotify.client import QuotaExceeded, SpotifyClient

ME = f"{API_URL}/me"


class FakeTokens:
    def __init__(self) -> None:
        self.refreshes = 0

    def access_token(self) -> str:
        return f"token{self.refreshes}"

    def refresh(self) -> None:
        self.refreshes += 1


def call(*responses: httpx.Response) -> tuple[dict, FakeTokens, list[float], list]:
    """Send GET /me while Spotify answers with ``responses`` in turn."""
    tokens, waits = FakeTokens(), []
    with respx.mock:
        route = respx.get(ME).mock(side_effect=list(responses))
        with httpx.Client() as http:
            result = SpotifyClient(tokens, http, sleep=waits.append).get("/me")
        return result, tokens, waits, list(route.calls)


def test_plain_success() -> None:
    result, tokens, waits, calls = call(httpx.Response(200, json={"id": "user1"}))
    assert result == {"id": "user1"}
    assert calls[0].request.headers["Authorization"] == "Bearer token0"
    assert (tokens.refreshes, waits) == (0, [])


def test_401_refreshes_once_and_retries() -> None:
    result, tokens, _, calls = call(
        httpx.Response(401), httpx.Response(200, json={"id": "user1"})
    )
    assert result == {"id": "user1"}
    assert tokens.refreshes == 1
    assert calls[1].request.headers["Authorization"] == "Bearer token1"


def test_second_401_is_an_error() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        call(httpx.Response(401), httpx.Response(401))


def test_429_waits_as_long_as_spotify_asks() -> None:
    result, _, waits, _ = call(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json={"id": "user1"}),
    )
    assert result == {"id": "user1"}
    assert waits == [7]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            429, json={"error": {"status": 429, "reason": "QUOTA_EXCEEDED"}}
        ),
        httpx.Response(429, headers={"Retry-After": "900"}),
    ],
)
def test_quota_or_long_waits_stop_the_run(response: httpx.Response) -> None:
    with pytest.raises(QuotaExceeded, match="again later"):
        call(response)


def test_server_errors_are_retried_three_times() -> None:
    result, _, waits, _ = call(
        httpx.Response(503),
        httpx.Response(502),
        httpx.Response(500),
        httpx.Response(200, json={"id": "user1"}),
    )
    assert result == {"id": "user1"}
    assert waits == [1, 2, 4]


def test_fourth_server_error_is_an_error() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        call(*[httpx.Response(503) for _ in range(4)])


def test_full_urls_are_used_as_they_are() -> None:
    next_page = f"{API_URL}/playlists/p1/items?offset=50&limit=50"
    with respx.mock:
        route = respx.get(next_page).mock(return_value=httpx.Response(200, json={}))
        with httpx.Client() as http:
            SpotifyClient(FakeTokens(), http).get(next_page)
    assert str(route.calls.last.request.url) == next_page


def test_empty_reply_becomes_an_empty_dict() -> None:
    result, *_ = call(httpx.Response(201))
    assert result == {}
