import httpx
import pytest
import respx

from qq2spotify.qq.links import LinkError, extract_playlist_id

PLAYLIST_ID = "7891234567"
SHARE_PAGE = (
    f"https://i.y.qq.com/n2/m/share/details/taoge.html?id={PLAYLIST_ID}&ADTAG=wxfshare"
)
SHORT_LINK = "https://c6.y.qq.com/base/fcgi-bin/u?__=AbC123"
# The format the QQ Music app's share button produced in November 2026.
APP_SHARE_LINK = (
    f"https://y.qq.com/n/ryqq_v2/playlist/{PLAYLIST_ID}"
    "?ADTAG=h5_share_playlist&redirecttag=mn.redirect.custom&mnst=0.91"
)


@pytest.mark.parametrize(
    "text",
    [
        PLAYLIST_ID,
        f"  {PLAYLIST_ID}\n",
        f"https://y.qq.com/n/ryqq/playlist/{PLAYLIST_ID}",
        f"https://y.qq.com/n/yqq/playlist/{PLAYLIST_ID}.html",
        APP_SHARE_LINK,
        SHARE_PAGE,
        f"分享歌单《夜跑》{SHARE_PAGE} @QQ音乐",
        f"看看这个：https://y.qq.com/n/ryqq/playlist/{PLAYLIST_ID}，好听",
        f"https://y.qq.com/n/ryqq/playlist/{PLAYLIST_ID}好听",
    ],
)
def test_finds_the_playlist_id(text: str) -> None:
    with httpx.Client() as client:
        assert extract_playlist_id(text, client) == PLAYLIST_ID


def test_follows_short_links() -> None:
    with respx.mock:
        respx.get(SHORT_LINK).mock(
            return_value=httpx.Response(302, headers={"Location": SHARE_PAGE})
        )
        respx.get(SHARE_PAGE).mock(return_value=httpx.Response(200, text="<html>"))
        with httpx.Client() as client:
            text = f"分享歌单《夜跑》{SHORT_LINK} @QQ音乐"
            assert extract_playlist_id(text, client) == PLAYLIST_ID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no link here",
        "https://y.qq.com/n/ryqq/songDetail/001AbCdEfGhIjK",
        "https://y.qq.com/n/ryqq/albumDetail/002AbCdEfGhIjK",
        "https://y.qq.com/n/ryqq/toplist/26",
    ],
)
def test_rejects_input_without_a_playlist(text: str) -> None:
    with httpx.Client() as client, pytest.raises(LinkError):
        extract_playlist_id(text, client)
