"""Shared HTTP settings."""

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def make_client() -> httpx.Client:
    """Return an HTTP client with a browser User-Agent and a 15-second timeout."""
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0)
