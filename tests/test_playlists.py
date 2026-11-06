import pytest

from qq2spotify.spotify.playlists import (
    PlaylistError,
    add_in_order,
    create_playlist,
    existing_uris,
    find_imported_playlist,
    parse_playlist_ref,
    playlist_url,
)

PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"
MARKER = "Imported from QQ Music playlist 7891234567 with qq2spotify"


class FakeApi:
    def __init__(self, pages: dict | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[tuple] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        self.calls.append(("GET", path, params))
        return self.pages[path]

    def post(self, path: str, json: dict | None = None) -> dict:
        self.calls.append(("POST", path, json))
        return {"id": "new1"} if path == "/me/playlists" else {"snapshot_id": "s"}


@pytest.mark.parametrize(
    "text",
    [
        f"https://open.spotify.com/playlist/{PLAYLIST_ID}?si=abc123",
        f"spotify:playlist:{PLAYLIST_ID}",
        f"  {PLAYLIST_ID} ",
    ],
)
def test_parse_playlist_ref(text: str) -> None:
    assert parse_playlist_ref(text) == PLAYLIST_ID


@pytest.mark.parametrize(
    "text", ["https://open.spotify.com/track/0YgvF6fNWydNGzCY3pzK4Y", "hello", ""]
)
def test_parse_playlist_ref_rejects_other_input(text: str) -> None:
    with pytest.raises(PlaylistError, match="Spotify playlist link"):
        parse_playlist_ref(text)


def test_playlist_url() -> None:
    assert playlist_url("abc") == "https://open.spotify.com/playlist/abc"


def test_create_playlist_marks_it_for_later_runs() -> None:
    api = FakeApi()
    assert create_playlist(api, "夜跑 (from QQ Music)", "7891234567") == "new1"
    assert api.calls == [
        (
            "POST",
            "/me/playlists",
            {"name": "夜跑 (from QQ Music)", "public": False, "description": MARKER},
        )
    ]


def test_find_imported_playlist_pages_and_checks_the_owner() -> None:
    next_page = "https://api.spotify.com/v1/me/playlists?offset=50&limit=50"
    api = FakeApi(
        {
            "/me/playlists": {
                "items": [
                    {"id": "theirs", "owner": {"id": "other"}, "description": MARKER},
                    {"id": "unrelated", "owner": {"id": "user1"}, "description": ""},
                    None,
                ],
                "next": next_page,
            },
            next_page: {
                "items": [
                    {"id": "mine", "owner": {"id": "user1"}, "description": MARKER}
                ],
                "next": None,
            },
        }
    )
    assert find_imported_playlist(api, "user1", "7891234567") == "mine"
    assert api.calls[0] == ("GET", "/me/playlists", {"limit": 50})
    assert api.calls[1] == ("GET", next_page, None)


def test_find_imported_playlist_when_there_is_none() -> None:
    api = FakeApi({"/me/playlists": {"items": [], "next": None}})
    assert find_imported_playlist(api, "user1", "7891234567") is None


def test_existing_uris_reads_every_page() -> None:
    path = f"/playlists/{PLAYLIST_ID}/items"
    next_page = f"https://api.spotify.com/v1{path}?offset=50&limit=50"
    api = FakeApi(
        {
            path: {
                "items": [
                    {"item": {"uri": "spotify:track:1"}},
                    {"track": {"uri": "spotify:track:2"}},  # the older key
                    {"item": None},
                    None,
                ],
                "next": next_page,
            },
            next_page: {"items": [{"item": {"uri": "spotify:track:3"}}], "next": None},
        }
    )
    assert existing_uris(api, PLAYLIST_ID) == {
        "spotify:track:1",
        "spotify:track:2",
        "spotify:track:3",
    }


def test_add_in_order_sends_100_at_a_time() -> None:
    api = FakeApi()
    uris = [f"spotify:track:{number}" for number in range(250)]
    assert add_in_order(api, PLAYLIST_ID, uris) == 250
    sent = [body["uris"] for _, _, body in api.calls]
    assert [len(chunk) for chunk in sent] == [100, 100, 50]
    assert [uri for chunk in sent for uri in chunk] == uris
    assert {path for _, path, _ in api.calls} == {f"/playlists/{PLAYLIST_ID}/items"}


def test_add_in_order_with_nothing_to_add() -> None:
    api = FakeApi()
    assert add_in_order(api, PLAYLIST_ID, []) == 0
    assert api.calls == []
