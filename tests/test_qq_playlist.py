import json
from pathlib import Path

import httpx
import pytest
import respx

from qq2spotify.qq.playlist import (
    ENDPOINTS,
    QQError,
    fetch_playlist,
    fetch_raw,
    parse_playlist,
)

FIXTURE = Path(__file__).parent / "fixtures" / "qq_playlist_sample.json"
MAIN, BACKUP = ENDPOINTS


def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_songs_in_order_without_repeats() -> None:
    name, tracks = parse_playlist(sample(), "7891234567")
    assert name == "夜跑 & 晨练"
    assert [t.qq_mid for t in tracks] == ["000AAA111", "000BBB222", "000CCC333"]
    assert [t.position for t in tracks] == [0, 1, 2]
    first, second, third = tracks
    assert first.title == "晴天"
    assert first.artists == ("周杰伦",)
    assert first.album == "叶惠美"
    assert first.duration_ms == 269_000
    assert second.artists == ("周杰伦", "阿信")
    assert third.title == "Rock & Roll [Live]"
    assert third.artists == ()
    assert third.album is None
    assert third.duration_ms is None


def test_reads_the_list_key_too() -> None:
    data = sample()
    playlist = data["cdlist"][0]
    playlist["list"] = playlist.pop("songlist")
    _, tracks = parse_playlist(data, "1")
    assert len(tracks) == 3


def test_missing_name_falls_back_to_the_id() -> None:
    data = sample()
    del data["cdlist"][0]["dissname"]
    name, _ = parse_playlist(data, "42")
    assert name == "QQ playlist 42"


def test_empty_playlist_is_an_error() -> None:
    with pytest.raises(QQError, match="empty"):
        parse_playlist({"code": 0, "cdlist": [{"songlist": []}]}, "1")


def test_sends_the_playlist_id_and_referer() -> None:
    with respx.mock:
        route = respx.get(MAIN).mock(return_value=httpx.Response(200, json=sample()))
        with httpx.Client() as client:
            _, tracks = fetch_playlist("7891234567", client)
    request = route.calls.last.request
    assert request.url.params["disstid"] == "7891234567"
    assert request.headers["Referer"] == "https://y.qq.com/n/ryqq/playlist/7891234567"
    assert "Cookie" not in request.headers
    assert len(tracks) == 3


def test_sends_the_cookie_when_given() -> None:
    with respx.mock:
        route = respx.get(MAIN).mock(return_value=httpx.Response(200, json=sample()))
        with httpx.Client() as client:
            fetch_playlist("7891234567", client, cookie="uin=123; qm_keyst=abc")
    assert route.calls.last.request.headers["Cookie"] == "uin=123; qm_keyst=abc"


def test_accepts_a_callback_wrapper() -> None:
    body = "jsonCallback(" + json.dumps(sample(), ensure_ascii=False) + ")"
    with respx.mock:
        respx.get(MAIN).mock(return_value=httpx.Response(200, text=body))
        with httpx.Client() as client:
            _, tracks = fetch_playlist("7891234567", client)
    assert len(tracks) == 3


def test_falls_back_to_the_backup_address() -> None:
    with respx.mock:
        respx.get(MAIN).mock(return_value=httpx.Response(503))
        backup = respx.get(BACKUP).mock(return_value=httpx.Response(200, json=sample()))
        with httpx.Client() as client:
            _, tracks = fetch_playlist("7891234567", client)
    assert backup.calls.last.request.url.params["nosign"] == "1"
    assert len(tracks) == 3


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (200, {"json": {"code": -1}}, "code -1"),
        (200, {"text": "<html>blocked</html>"}, "did not return JSON"),
        (200, {"text": "{not json}"}, "broken JSON"),
        (403, {}, "Couldn't get the playlist"),
    ],
)
def test_errors_say_what_went_wrong(status: int, body: dict, message: str) -> None:
    with respx.mock:
        for endpoint in ENDPOINTS:
            respx.get(endpoint).mock(return_value=httpx.Response(status, **body))
        with httpx.Client() as client, pytest.raises(QQError, match=message):
            fetch_raw("1", client)
