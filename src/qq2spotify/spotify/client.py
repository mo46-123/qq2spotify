"""Calls to the Spotify Web API, with retries."""

import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from qq2spotify.spotify.auth import API_URL

MAX_SERVER_RETRIES = 3
MAX_WAIT_SECONDS = 120


class TokenProvider(Protocol):
    def access_token(self) -> str: ...

    def refresh(self) -> None: ...


class QuotaExceeded(RuntimeError):
    """Spotify's limits stopped the run; trying again later will work."""


def _reason(response: httpx.Response) -> str | None:
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return None
    return error.get("reason") if isinstance(error, dict) else None


def _retry_after(response: httpx.Response) -> int:
    try:
        return max(0, int(response.headers.get("Retry-After", "5")))
    except ValueError:
        return 5


class SpotifyClient:
    """Sends Web API requests and handles expired tokens, rate limits and outages."""

    def __init__(
        self,
        tokens: TokenProvider,
        http: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.tokens = tokens
        self.http = http
        self.sleep = sleep

    def request(self, method: str, path: str, **kwargs: Any) -> dict:
        # Paging links ("next") are full URLs; everything else is a path.
        url = path if path.startswith("https://") else API_URL + path
        refreshed = False
        server_errors = 0
        while True:
            headers = {"Authorization": f"Bearer {self.tokens.access_token()}"}
            response = self.http.request(method, url, headers=headers, **kwargs)
            if response.status_code == 401 and not refreshed:
                self.tokens.refresh()
                refreshed = True
                continue
            if response.status_code == 429:
                if _reason(response) == "QUOTA_EXCEEDED":
                    raise QuotaExceeded(
                        "Spotify's quota for your app is used up for now. Run the "
                        "same command again later."
                    )
                wait = _retry_after(response)
                if wait > MAX_WAIT_SECONDS:
                    raise QuotaExceeded(
                        f"Spotify asked qq2spotify to wait {wait} seconds. Run the "
                        "same command again later."
                    )
                self.sleep(wait)
                continue
            if response.status_code >= 500 and server_errors < MAX_SERVER_RETRIES:
                self.sleep(2**server_errors)
                server_errors += 1
                continue
            response.raise_for_status()
            return response.json() if response.content else {}

    def get(self, path: str, **kwargs: Any) -> dict:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> dict:
        return self.request("POST", path, **kwargs)
