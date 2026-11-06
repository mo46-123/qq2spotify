"""Create Spotify playlists and add songs to them."""

import re
from collections.abc import Iterable
from typing import Any, Protocol

CHUNK_SIZE = 100  # the most songs Spotify accepts in one request
PAGE_SIZE = 50


class Api(Protocol):
    def get(self, path: str, **kwargs: Any) -> dict: ...

    def post(self, path: str, **kwargs: Any) -> dict: ...


class PlaylistError(ValueError):
    """The Spotify playlist link or ID can't be used."""


def parse_playlist_ref(text: str) -> str:
    """Return the playlist ID from a Spotify link, a spotify:playlist: URI or an ID."""
    text = text.strip()
    found = re.search(r"playlist[/:]([A-Za-z0-9]{22})\b", text)
    if found:
        return found.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", text):
        return text
    raise PlaylistError(
        "That isn't a Spotify playlist link. In Spotify, use Share > Copy link "
        "to playlist."
    )


def playlist_url(playlist_id: str) -> str:
    return f"https://open.spotify.com/playlist/{playlist_id}"


def import_marker(qq_playlist_id: str) -> str:
    """Text put in the playlist's description, so a later run can find it again."""
    return f"QQ Music playlist {qq_playlist_id}"


def create_playlist(
    api: Api, name: str, qq_playlist_id: str, public: bool = False
) -> str:
    """Create a playlist in the signed-in account and return its ID."""
    data = api.post(
        "/me/playlists",
        json={
            "name": name,
            "public": public,
            "description": f"Imported from {import_marker(qq_playlist_id)} "
            "with qq2spotify",
        },
    )
    return data["id"]


def find_imported_playlist(api: Api, user_id: str, qq_playlist_id: str) -> str | None:
    """Find a playlist an earlier run made for this QQ playlist in this account."""
    marker = import_marker(qq_playlist_id)
    url: str | None = "/me/playlists"
    params: dict | None = {"limit": PAGE_SIZE}
    while url:
        page = api.get(url, params=params)
        for playlist in page.get("items") or []:
            if not playlist:
                continue
            owner = (playlist.get("owner") or {}).get("id")
            if owner == user_id and marker in (playlist.get("description") or ""):
                return playlist["id"]
        url, params = page.get("next"), None  # "next" is a full URL with paging
    return None


def existing_uris(api: Api, playlist_id: str) -> set[str]:
    """The songs already in a playlist."""
    uris: set[str] = set()
    url: str | None = f"/playlists/{playlist_id}/items"
    params: dict | None = {"limit": PAGE_SIZE}
    while url:
        page = api.get(url, params=params)
        for entry in page.get("items") or []:
            # The song sits under "item" since February 2026 ("track" before).
            song = (entry or {}).get("item") or (entry or {}).get("track") or {}
            if song.get("uri"):
                uris.add(song["uri"])
        url, params = page.get("next"), None
    return uris


def add_in_order(api: Api, playlist_id: str, uris: Iterable[str]) -> int:
    """Add songs at the end of the playlist, in order, 100 per request."""
    pending = list(uris)
    for start in range(0, len(pending), CHUNK_SIZE):
        api.post(
            f"/playlists/{playlist_id}/items",
            json={"uris": pending[start : start + CHUNK_SIZE]},
        )
    return len(pending)
